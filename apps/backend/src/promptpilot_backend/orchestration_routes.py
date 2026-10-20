import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .dependencies import current_user
from .github_repository import connect_repository, publish_task, repository_response, reviewed_files
from .llm_provider import ProviderUnavailable
from .models import (
    AgentRun,
    AgentTask,
    PlanMilestone,
    ProjectPlan,
    ProjectRepository,
    ProviderConnection,
    User,
)
from .orchestration_service import (
    create_project_plan,
    create_provider_connection,
    execute_agent_task,
    plan_response,
    provider_response,
    record_connection_test,
    replace_provider_key,
    run_response,
    task_response,
    test_provider_connection,
    user_connection,
)
from .project_policy import ProjectRole, require_project_access
from .provider_gateway import ProviderGateway
from .provider_registry import PROVIDERS
from .schemas import (
    AgentDraftUpdateRequest,
    AgentRunResponse,
    AgentTaskResponse,
    AgentTaskUpdateRequest,
    ProjectPlanCreateRequest,
    ProjectPlanListResponse,
    ProjectPlanResponse,
    ProjectRepositoryRequest,
    ProjectRepositoryResponse,
    ProviderConnectionCreateRequest,
    ProviderConnectionListResponse,
    ProviderConnectionResponse,
    ProviderConnectionUpdateRequest,
    ProviderDiscoveryRequest,
    ProviderTestResponse,
    PublishTaskResponse,
)
from .workflow_service import AgentTaskCreateRequest, validate_task_dependencies

provider_router = APIRouter(prefix="/api/v1/provider-connections", tags=["providers"])
plan_router = APIRouter(prefix="/api/v1", tags=["orchestration"])


@provider_router.get("/catalog")
def provider_catalog(user: User = Depends(current_user)) -> dict[str, object]:
    return {"items": [definition.__dict__ for definition in PROVIDERS.values()]}


@provider_router.post("/discover")
def discover_models(
    payload: ProviderDiscoveryRequest, user: User = Depends(current_user)
) -> dict[str, list[str]]:
    try:
        return {
            "models": ProviderGateway(
                payload.provider, "discovery", payload.api_key, payload.base_url
            ).list_models()
        }
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except ProviderUnavailable as error:
        raise HTTPException(status_code=502, detail=error.reason) from None


@provider_router.patch("/{connection_id}", response_model=ProviderConnectionResponse)
def update_connection(
    connection_id: UUID,
    payload: ProviderConnectionUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProviderConnectionResponse:
    connection = user_connection(db, connection_id, user.id)
    if payload.default_model is not None:
        connection.default_model = payload.default_model.removeprefix("models/")
    if payload.api_key is not None:
        replace_provider_key(connection, payload.api_key)
    db.commit()
    return provider_response(connection)


@plan_router.get("/projects/{project_id}/repository", response_model=ProjectRepositoryResponse)
def get_repository(
    project_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectRepositoryResponse:
    require_project_access(db, project_id, user.id)
    repository = db.get(ProjectRepository, project_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="No GitHub repository is connected")
    return repository_response(repository)


@plan_router.put("/projects/{project_id}/repository", response_model=ProjectRepositoryResponse)
def set_repository(
    project_id: UUID,
    payload: ProjectRepositoryRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectRepositoryResponse:
    require_project_access(db, project_id, user.id, ProjectRole.OWNER)
    return repository_response(connect_repository(db, project_id, payload))


@plan_router.post("/agent-tasks/{task_id}/publish", response_model=PublishTaskResponse)
def publish_code_task(
    task_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PublishTaskResponse:
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    require_project_access(db, task.project_id, user.id, ProjectRole.OWNER)
    repository = db.get(ProjectRepository, task.project_id)
    if repository is None:
        raise HTTPException(status_code=409, detail="Connect a GitHub repository first")
    return publish_task(db, task, repository)


@plan_router.patch("/agent-tasks/{task_id}/draft", response_model=AgentTaskResponse)
def update_code_draft(
    task_id: UUID,
    payload: AgentDraftUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AgentTaskResponse:
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    require_project_access(db, task.project_id, user.id, ProjectRole.OWNER)
    if task.role not in {"frontend", "backend", "api"} or task.status not in {
        "review",
        "completed",
    }:
        raise HTTPException(status_code=409, detail="A reviewed code task is required")
    if task.pull_request_url:
        raise HTTPException(status_code=409, detail="Code was already published")
    reviewed_files(payload.output_text)
    task.output_text = payload.output_text
    task.status = "review"
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@provider_router.get("", response_model=ProviderConnectionListResponse)
def list_connections(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProviderConnectionListResponse:
    connections = list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.user_id == user.id)
            .order_by(ProviderConnection.created_at)
        )
    )
    return ProviderConnectionListResponse(items=[provider_response(item) for item in connections])


@provider_router.post(
    "", response_model=ProviderConnectionResponse, status_code=status.HTTP_201_CREATED
)
def add_connection(
    payload: ProviderConnectionCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProviderConnectionResponse:
    return provider_response(create_provider_connection(db, user, payload))


@provider_router.post("/{connection_id}/test", response_model=ProviderTestResponse)
def test_connection(
    connection_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProviderTestResponse:
    connection = user_connection(db, connection_id, user.id)
    try:
        models = test_provider_connection(connection)
    except HTTPException as error:
        record_connection_test(db, connection, "failed", str(error.detail))
        raise
    if (
        models
        and connection.default_model.removeprefix("models/") not in models
        and not (
            connection.provider == "openrouter"
            and connection.default_model in {"openrouter/free", "openrouter/auto"}
        )
    ):
        record_connection_test(
            db, connection, "failed", "Choose a model from the available catalog", models
        )
        raise HTTPException(
            status_code=422,
            detail="The selected model is not in this provider's catalog. "
            "Choose an available model and test again.",
        )
    record_connection_test(
        db, connection, "passed", f"Connected; {len(models)} models visible", models
    )
    db.refresh(connection)
    return ProviderTestResponse(connection=provider_response(connection), available_models=models)


@provider_router.post("/{connection_id}/disable", response_model=ProviderConnectionResponse)
def disable_connection(
    connection_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProviderConnectionResponse:
    connection = user_connection(db, connection_id, user.id)
    connection.status = "disabled"
    db.commit()
    db.refresh(connection)
    return provider_response(connection)


@plan_router.get("/projects/{project_id}/plans", response_model=ProjectPlanListResponse)
def list_plans(
    project_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectPlanListResponse:
    require_project_access(db, project_id, user.id)
    plans = list(
        db.scalars(
            select(ProjectPlan)
            .where(ProjectPlan.project_id == project_id)
            .order_by(ProjectPlan.created_at.desc())
        )
    )
    return ProjectPlanListResponse(items=[plan_response(db, plan) for plan in plans])


@plan_router.post(
    "/projects/{project_id}/plans",
    response_model=ProjectPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_plan(
    project_id: UUID,
    payload: ProjectPlanCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectPlanResponse:
    require_project_access(db, project_id, user.id, ProjectRole.EDITOR)
    plan = create_project_plan(db, project_id, user, payload)
    return plan_response(db, plan)


def _editable_task(db: Session, task_id: UUID, user: User) -> AgentTask:
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    project, _ = require_project_access(db, task.project_id, user.id, ProjectRole.EDITOR)
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="Archived projects cannot be modified")
    return task


@plan_router.patch("/agent-tasks/{task_id}", response_model=AgentTaskResponse)
def update_task(
    task_id: UUID,
    payload: AgentTaskUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AgentTaskResponse:
    task = _editable_task(db, task_id, user)
    if task.status == "running":
        raise HTTPException(status_code=409, detail="Wait for the running task to finish")
    supplied = payload.model_fields_set
    if payload.title is not None:
        if not payload.title.strip():
            raise HTTPException(status_code=422, detail="Task title cannot be blank")
        task.title = payload.title.strip()
    if payload.description is not None:
        if not payload.description.strip():
            raise HTTPException(status_code=422, detail="Task description cannot be blank")
        task.description = payload.description.strip()
    if payload.dependencies is not None:
        validate_task_dependencies(db, task, payload.dependencies)
        task.dependencies_json = json.dumps([str(value) for value in payload.dependencies])
    if payload.acceptance_criteria is not None:
        task.acceptance_criteria_json = json.dumps(payload.acceptance_criteria)
    if "review_notes" in supplied:
        task.review_notes = payload.review_notes
    if "assigned_connection_id" in supplied:
        if payload.assigned_connection_id is None:
            task.assigned_connection_id = None
            task.assigned_model = None
            task.assignment_reason = "No provider is assigned."
        else:
            connection = user_connection(db, payload.assigned_connection_id, user.id)
            if connection.status != "active":
                raise HTTPException(status_code=409, detail="Provider connection is not active")
            task.assigned_connection_id = connection.id
            task.assigned_model = payload.assigned_model or connection.default_model
            task.assignment_reason = "Manually assigned by the project editor."
    elif "assigned_model" in supplied and payload.assigned_model:
        task.assigned_model = payload.assigned_model.strip()
    if "scheduled_for" in supplied:
        task.scheduled_for = payload.scheduled_for
        if payload.scheduled_for is not None:
            task.status = "scheduled"
    if payload.status is not None:
        if payload.status == "completed" and (not task.output_text or task.status != "review"):
            raise HTTPException(
                status_code=409, detail="Run the task and review its output before approving"
            )
        task.status = payload.status
    db.commit()
    db.refresh(task)
    return task_response(db, task)


@plan_router.get("/agent-tasks/{task_id}/runs", response_model=list[AgentRunResponse])
def task_runs(
    task_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[AgentRunResponse]:
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    require_project_access(db, task.project_id, user.id)
    return [
        run_response(run)
        for run in db.scalars(
            select(AgentRun).where(AgentRun.task_id == task.id).order_by(AgentRun.started_at.desc())
        )
    ]


@plan_router.post("/plans/{plan_id}/tasks", response_model=AgentTaskResponse, status_code=201)
def add_workflow_task(
    plan_id: UUID,
    payload: AgentTaskCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AgentTaskResponse:
    plan = db.get(ProjectPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    project, _ = require_project_access(db, plan.project_id, user.id, ProjectRole.EDITOR)
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="Archived projects cannot be modified")
    tasks = list(db.scalars(select(AgentTask).where(AgentTask.plan_id == plan.id)))
    if len(tasks) >= 30:
        raise HTTPException(status_code=422, detail="Use at most 30 nodes in a workflow")
    milestone = (
        db.get(PlanMilestone, payload.milestone_id)
        if payload.milestone_id
        else db.scalar(
            select(PlanMilestone)
            .where(PlanMilestone.plan_id == plan.id)
            .order_by(PlanMilestone.position)
        )
    )
    if milestone is None or milestone.plan_id != plan.id:
        raise HTTPException(status_code=422, detail="Choose a phase from this workflow")
    task = AgentTask(
        id=uuid4(),
        project_id=plan.project_id,
        plan_id=plan.id,
        milestone_id=milestone.id,
        created_by_id=user.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        role=payload.role,
        assignment_reason="Choose a connected model for this node.",
        dependencies_json="[]",
        acceptance_criteria_json=json.dumps(payload.acceptance_criteria),
        status="backlog",
    )
    if not task.title or not task.description:
        raise HTTPException(status_code=422, detail="Task title and instructions cannot be blank")
    validate_task_dependencies(db, task, payload.dependencies)
    task.dependencies_json = json.dumps([str(value) for value in payload.dependencies])
    db.add(task)
    db.commit()
    return task_response(db, task)


@plan_router.delete("/agent-tasks/{task_id}", status_code=204)
def delete_workflow_task(
    task_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    task = _editable_task(db, task_id, user)
    if task.status == "running":
        raise HTTPException(status_code=409, detail="Wait for the running task to finish")
    for other in db.scalars(select(AgentTask).where(AgentTask.plan_id == task.plan_id)):
        if str(task.id) in json.loads(other.dependencies_json):
            raise HTTPException(
                status_code=409, detail="Remove outgoing dependencies before deleting this node"
            )
    db.delete(task)
    db.commit()


@plan_router.post("/agent-tasks/{task_id}/run", response_model=AgentRunResponse)
def run_task(
    task_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AgentRunResponse:
    task = _editable_task(db, task_id, user)
    if task.status in {"running", "completed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Task cannot run while {task.status}")
    if task.assigned_connection_id is None:
        raise HTTPException(status_code=409, detail="Assign an active provider before running")
    connection = user_connection(db, task.assigned_connection_id, user.id)
    if connection.status != "active":
        raise HTTPException(status_code=409, detail="Assigned provider connection is not active")
    return run_response(execute_agent_task(db, task, connection))
