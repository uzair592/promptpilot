from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .dependencies import current_user
from .github_repository import connect_repository, publish_task, repository_response, reviewed_files
from .models import AgentTask, ProjectPlan, ProjectRepository, ProviderConnection, User
from .orchestration_service import (
    create_project_plan,
    create_provider_connection,
    execute_agent_task,
    plan_response,
    provider_response,
    record_connection_test,
    run_response,
    task_response,
    test_provider_connection,
    user_connection,
)
from .project_policy import ProjectRole, require_project_access
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
    ProviderTestResponse,
    PublishTaskResponse,
)

provider_router = APIRouter(prefix="/api/v1/provider-connections", tags=["providers"])
plan_router = APIRouter(prefix="/api/v1", tags=["orchestration"])


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
    if task.role not in {"frontend", "backend", "api"} or task.status != "review":
        raise HTTPException(status_code=409, detail="A reviewed code task is required")
    if task.pull_request_url:
        raise HTTPException(status_code=409, detail="Code was already published")
    reviewed_files(payload.output_text)
    task.output_text = payload.output_text
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
    except HTTPException:
        record_connection_test(db, connection, "failed", "Connection test failed")
        raise
    record_connection_test(db, connection, "passed", f"Connected; {len(models)} models visible")
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
    require_project_access(db, task.project_id, user.id, ProjectRole.EDITOR)
    return task


@plan_router.patch("/agent-tasks/{task_id}", response_model=AgentTaskResponse)
def update_task(
    task_id: UUID,
    payload: AgentTaskUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AgentTaskResponse:
    task = _editable_task(db, task_id, user)
    supplied = payload.model_fields_set
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
        task.status = payload.status
    db.commit()
    db.refresh(task)
    return task_response(db, task)


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
