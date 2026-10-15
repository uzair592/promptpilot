import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from .config import get_settings
from .llm_provider import ProviderUnavailable
from .models import (
    AgentRun,
    AgentTask,
    PlanMilestone,
    ProjectPlan,
    ProjectRepository,
    ProviderConnection,
    User,
    utc_now,
)
from .provider_gateway import ProviderGateway
from .schemas import (
    AgentRunResponse,
    AgentTaskResponse,
    PlanMilestoneResponse,
    ProjectPlanCreateRequest,
    ProjectPlanResponse,
    ProviderConnectionCreateRequest,
    ProviderConnectionResponse,
)

ROLE_PREFERENCES = {
    "orchestrator": ("openrouter", "openai", "anthropic", "gemini"),
    "product_manager": ("openrouter", "openai", "gemini", "anthropic"),
    "researcher": ("gemini", "openai", "openrouter", "anthropic"),
    "frontend": ("gemini", "anthropic", "openai", "openrouter"),
    "backend": ("anthropic", "openai", "openrouter", "gemini"),
    "api": ("anthropic", "openai", "gemini", "openrouter"),
    "tester": ("openai", "anthropic", "gemini", "openrouter"),
}

PLAN_TEMPLATE = (
    (
        "Discovery and architecture",
        "Turn the idea into an agreed scope, architecture, risks, and delivery contract.",
        (
            (
                "Define product requirements",
                "Write user stories and acceptance criteria for the project goal and its constraints.",
                "product_manager",
                ["User stories cover the primary flow", "Acceptance criteria are testable"],
            ),
            (
                "Define scope and success criteria",
                "Convert the product idea into user journeys, constraints, exclusions, and measurable success criteria.",
                "orchestrator",
                [
                    "Primary users and journeys are explicit",
                    "Out-of-scope work is recorded",
                    "Success is measurable",
                ],
            ),
            (
                "Research technical choices",
                "Compare the important platform, framework, data, integration, and hosting choices for this product.",
                "researcher",
                [
                    "Options and trade-offs are documented",
                    "A recommendation is justified",
                    "Key risks are identified",
                ],
            ),
        ),
    ),
    (
        "Application foundation",
        "Build the secure data, API, authentication, and integration foundation.",
        (
            (
                "Design API contracts",
                "Specify endpoints, request and response formats, authentication, and error cases.",
                "api",
                ["Contracts are testable", "Authorization is specified"],
            ),
            (
                "Design backend and data contracts",
                "Specify the backend modules, persistent entities, API contracts, authorization rules, and migrations.",
                "backend",
                [
                    "API contracts are testable",
                    "Authorization is defined",
                    "Migration and rollback paths exist",
                ],
            ),
            (
                "Implement backend foundation",
                "Implement the approved backend slice with validation, error handling, migrations, and unit tests.",
                "backend",
                [
                    "Automated tests pass",
                    "Secrets never reach clients or logs",
                    "Failure states are handled",
                ],
            ),
        ),
    ),
    (
        "User experience",
        "Deliver the main user journey as a clear, responsive, accessible interface.",
        (
            (
                "Implement the primary interface",
                "Build the end-to-end frontend journey against the approved API contracts, including loading and error states.",
                "frontend",
                [
                    "Primary journey works end to end",
                    "Empty/loading/error states exist",
                    "Keyboard navigation is usable",
                ],
            ),
        ),
    ),
    (
        "Verification and release",
        "Independently challenge the implementation and prepare an evidence-based release decision.",
        (
            (
                "Run independent quality review",
                "Review requirements, security boundaries, edge cases, regressions, and end-to-end behavior independently from implementation.",
                "tester",
                [
                    "Critical journeys have acceptance tests",
                    "Security boundaries are tested",
                    "Defects include reproducible evidence",
                ],
            ),
            (
                "Prepare release decision",
                "Summarize test evidence, unresolved risks, operational needs, and the go/no-go recommendation.",
                "orchestrator",
                [
                    "Required checks are green",
                    "Known risks have owners",
                    "Rollback and monitoring are documented",
                ],
            ),
        ),
    ),
)

TASK_PREREQUISITES = {
    "Define scope and success criteria": ("Define product requirements",),
    "Research technical choices": ("Define scope and success criteria",),
    "Design API contracts": ("Research technical choices",),
    "Design backend and data contracts": ("Design API contracts",),
    "Implement backend foundation": ("Design backend and data contracts",),
    "Implement the primary interface": ("Design API contracts",),
    "Run independent quality review": (
        "Implement backend foundation",
        "Implement the primary interface",
    ),
    "Prepare release decision": ("Run independent quality review",),
}


def _cipher() -> Fernet:
    settings = get_settings()
    value = settings.provider_key_encryption_key
    if not value and settings.app_env == "development":
        storage = settings.ensure_storage_directory()
        key_file = Path(storage) / ".provider-vault.key"
        if not key_file.exists():
            with tempfile.NamedTemporaryFile(
                dir=storage, prefix=".vault-", delete=False
            ) as key_stream:
                temporary_key = Path(key_stream.name)
                key_stream.write(Fernet.generate_key())
            try:
                try:
                    os.link(temporary_key, key_file)
                except FileExistsError:
                    pass
            finally:
                temporary_key.unlink(missing_ok=True)
        try:
            value = key_file.read_text(encoding="ascii").strip()
        except OSError as error:
            raise HTTPException(
                status_code=503, detail="Local provider vault key could not be read"
            ) from error
    if not value:
        raise HTTPException(
            status_code=503,
            detail="Set PROVIDER_KEY_ENCRYPTION_KEY on the backend to enable the provider vault.",
        )
    try:
        return Fernet(value.encode())
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=503, detail="Provider vault encryption key is invalid"
        ) from error


def provider_response(connection: ProviderConnection) -> ProviderConnectionResponse:
    return ProviderConnectionResponse(
        id=connection.id,
        provider=connection.provider,
        label=connection.label,
        masked_key=f"••••{connection.key_last_four}",
        default_model=connection.default_model,
        base_url=connection.base_url,
        available_models=json.loads(connection.models_json or "[]"),
        status=connection.status,
        last_tested_at=connection.last_tested_at,
        last_test_status=connection.last_test_status,
        last_test_message=connection.last_test_message,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def create_provider_connection(
    db: Session, user: User, payload: ProviderConnectionCreateRequest
) -> ProviderConnection:
    api_key = payload.api_key.strip()
    connection = ProviderConnection(
        user_id=user.id,
        provider=payload.provider,
        label=payload.label.strip(),
        encrypted_api_key=_cipher().encrypt(api_key.encode()).decode(),
        key_fingerprint=hashlib.sha256(api_key.encode()).hexdigest(),
        key_last_four=api_key[-4:],
        default_model=payload.default_model.strip(),
        base_url=payload.base_url,
    )
    db.add(connection)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A connection with this label already exists"
        ) from None
    db.refresh(connection)
    return connection


def decrypt_api_key(connection: ProviderConnection) -> str:
    try:
        return _cipher().decrypt(connection.encrypted_api_key.encode()).decode()
    except InvalidToken as error:
        raise HTTPException(
            status_code=503, detail="Provider credential cannot be decrypted"
        ) from error


def user_connection(db: Session, connection_id: UUID, user_id: UUID) -> ProviderConnection:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == connection_id, ProviderConnection.user_id == user_id
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Provider connection not found")
    return connection


def test_provider_connection(connection: ProviderConnection) -> list[str]:
    try:
        return ProviderGateway(
            connection.provider,
            connection.default_model,
            decrypt_api_key(connection),
            connection.base_url,
        ).list_models()
    except ProviderUnavailable as error:
        raise HTTPException(status_code=502, detail=error.reason) from None


def record_connection_test(
    db: Session,
    connection: ProviderConnection,
    status: str,
    message: str,
    models: list[str] | None = None,
) -> None:
    connection.last_tested_at = utc_now()
    connection.last_test_status = status
    connection.last_test_message = message[:500]
    connection.status = "active" if status == "passed" else "invalid"
    if models is not None:
        connection.models_json = json.dumps(models)
    db.commit()


def _choose_connection(
    connections: list[ProviderConnection], role: str
) -> tuple[ProviderConnection | None, str]:
    active = [item for item in connections if item.status == "active"]
    for provider in ROLE_PREFERENCES[role]:
        match = next((item for item in active if item.provider == provider), None)
        if match:
            return (
                match,
                f"{match.provider.title()} is the highest available preference for the {role} role.",
            )
    if active:
        return active[
            0
        ], "Assigned an available model; you can choose a specialist in the node inspector."
    return None, "No active provider is connected; assign one before running this task."


def create_project_plan(
    db: Session, project_id: UUID, user: User, payload: ProjectPlanCreateRequest
) -> ProjectPlan:
    from .workflow_service import generate_workflow

    generated = None
    if payload.planner_connection_id:
        planner = user_connection(db, payload.planner_connection_id, user.id)
        if planner.status != "active":
            raise HTTPException(status_code=409, detail="Test the planner connection first")
        try:
            generated = generate_workflow(planner, payload.idea)
        except ProviderUnavailable as error:
            raise HTTPException(status_code=503, detail=error.reason) from None
    plan = ProjectPlan(
        project_id=project_id,
        created_by_id=user.id,
        title=payload.title.strip(),
        summary=payload.idea.strip(),
        status="active",
        planning_mode="ai" if generated else "template",
    )
    db.add(plan)
    db.flush()
    connections = list(
        db.scalars(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user.id, ProviderConnection.status == "active"
            )
        )
    )
    task_ids: dict[str, str] = {}
    if generated:
        for section in generated.milestones:
            for spec in section.tasks:
                task_ids[spec.key] = str(uuid4())
    else:
        for _, _, specs in PLAN_TEMPLATE:
            for task_title, _, _, _ in specs:
                task_ids[task_title] = str(uuid4())
    task_number = 0
    sections: list[tuple[str, str, list[tuple[str, str, str, list[str], str, list[str]]]]] = (
        [
            (
                section.title,
                section.description,
                [
                    (
                        spec.title,
                        spec.description,
                        spec.role,
                        spec.acceptance_criteria,
                        spec.key,
                        spec.dependencies,
                    )
                    for spec in section.tasks
                ],
            )
            for section in generated.milestones
        ]
        if generated
        else [
            (
                title,
                description,
                [
                    (
                        task_title,
                        task_description,
                        role,
                        list(criteria),
                        task_title,
                        list(TASK_PREREQUISITES.get(task_title, ())),
                    )
                    for task_title, task_description, role, criteria in specs
                ],
            )
            for title, description, specs in PLAN_TEMPLATE
        ]
    )
    for position, (title, description, task_specs) in enumerate(sections, start=1):
        due_at = payload.start_at + timedelta(days=position * 7) if payload.start_at else None
        milestone = PlanMilestone(
            plan_id=plan.id,
            title=title,
            description=description,
            position=position,
            status="pending",
            due_at=due_at,
        )
        db.add(milestone)
        db.flush()
        for task_title, task_description, role, criteria, key, dependencies in task_specs:
            connection, reason = _choose_connection(connections, role)
            scheduled_for = (
                payload.start_at + timedelta(days=task_number * 3) if payload.start_at else None
            )
            task = AgentTask(
                id=UUID(task_ids[key]),
                project_id=project_id,
                plan_id=plan.id,
                milestone_id=milestone.id,
                created_by_id=user.id,
                assigned_connection_id=connection.id if connection else None,
                assigned_model=connection.default_model if connection else None,
                title=task_title,
                description=task_description,
                role=role,
                assignment_reason=reason,
                acceptance_criteria_json=json.dumps(criteria),
                dependencies_json=json.dumps([task_ids[name] for name in dependencies]),
                status="scheduled" if scheduled_for else "backlog",
                scheduled_for=scheduled_for,
            )
            db.add(task)
            db.flush()
            task_number += 1
    db.commit()
    db.refresh(plan)
    return plan


def task_response(db: Session, task: AgentTask) -> AgentTaskResponse:
    connection = (
        db.get(ProviderConnection, task.assigned_connection_id)
        if task.assigned_connection_id
        else None
    )
    return AgentTaskResponse(
        id=task.id,
        project_id=task.project_id,
        plan_id=task.plan_id,
        milestone_id=task.milestone_id,
        title=task.title,
        description=task.description,
        role=task.role,
        assignment_reason=task.assignment_reason,
        assigned_connection_id=task.assigned_connection_id,
        assigned_provider=connection.provider if connection else None,
        assigned_model=task.assigned_model,
        review_notes=task.review_notes,
        acceptance_criteria=json.loads(task.acceptance_criteria_json),
        dependencies=json.loads(task.dependencies_json),
        status=task.status,
        scheduled_for=task.scheduled_for,
        output_text=task.output_text,
        pull_request_url=task.pull_request_url,
        last_error=task.last_error,
        attempt_count=task.attempt_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def plan_response(db: Session, plan: ProjectPlan) -> ProjectPlanResponse:
    milestones = list(
        db.scalars(
            select(PlanMilestone)
            .where(PlanMilestone.plan_id == plan.id)
            .order_by(PlanMilestone.position)
        )
    )
    milestone_responses = []
    for milestone in milestones:
        tasks = list(
            db.scalars(
                select(AgentTask)
                .where(AgentTask.milestone_id == milestone.id)
                .order_by(AgentTask.created_at)
            )
        )
        milestone_responses.append(
            PlanMilestoneResponse(
                id=milestone.id,
                plan_id=milestone.plan_id,
                title=milestone.title,
                description=milestone.description,
                position=milestone.position,
                status=milestone.status,
                due_at=milestone.due_at,
                tasks=[task_response(db, task) for task in tasks],
            )
        )
    return ProjectPlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        title=plan.title,
        summary=plan.summary,
        planning_mode=plan.planning_mode,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        milestones=milestone_responses,
    )


def execute_agent_task(db: Session, task: AgentTask, connection: ProviderConnection) -> AgentRun:
    from .github_repository import repository_context

    api_key = decrypt_api_key(connection)
    model = task.assigned_model or connection.default_model
    plan = db.get(ProjectPlan, task.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Project plan not found")
    chain: list[AgentTask] = []
    visited: set[UUID] = set()
    visiting = {task.id}

    def gather_prerequisites(current: AgentTask) -> None:
        for value in json.loads(current.dependencies_json):
            prerequisite_id = UUID(value)
            if prerequisite_id in visited:
                continue
            predecessor = db.get(AgentTask, prerequisite_id)
            if (
                predecessor is None
                or predecessor.id in visiting
                or predecessor.plan_id != task.plan_id
                or predecessor.status not in {"review", "completed"}
                or len(visited) + len(visiting) >= 30
            ):
                raise HTTPException(
                    status_code=409, detail="Finish prerequisite tasks before running this one"
                )
            visiting.add(predecessor.id)
            gather_prerequisites(predecessor)
            visiting.remove(predecessor.id)
            visited.add(predecessor.id)
            chain.append(predecessor)

    gather_prerequisites(task)
    handoff = "\n\n".join(
        f"{item.role}: {item.title}\n{item.output_text[:12000]}"
        for item in chain
        if item.output_text
    )[-45000:]
    repository = db.get(ProjectRepository, task.project_id)
    source_context = repository_context(repository, task.role) if repository else ""
    instruction = (
        f"You are the {task.role} specialist in a supervised software delivery team. "
        "Produce a reviewable work product; do not claim you changed files or ran tests.\n\n"
        f"Project goal and improved prompt:\n{plan.summary[:20000]}\n\n"
        f"Upstream model outputs:\n{handoff or 'This is the first task.'}\n\n"
        f"Repository source snapshot (default branch):\n{source_context or 'No source files available.'}\n\n"
        f"Task: {task.title}\n{task.description}\n\n"
        f"Acceptance criteria: {task.acceptance_criteria_json}"
    )
    if task.role in {"frontend", "backend", "api"}:
        instruction += (
            "\n\nFor code work, return ONLY JSON with a 'files' array of objects "
            "containing 'path' and 'content' text fields. Use relative paths and "
            "complete files. The user will inspect this draft before publication."
        )
    claimed = db.execute(
        update(AgentTask)
        .where(
            AgentTask.id == task.id,
            AgentTask.status.in_(("backlog", "ready", "scheduled", "failed", "review")),
        )
        .values(status="running", attempt_count=AgentTask.attempt_count + 1)
    )
    if cast(CursorResult[Any], claimed).rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This node is already running or has been closed"
        )
    run = AgentRun(
        task_id=task.id,
        connection_id=connection.id,
        provider=connection.provider,
        model=model,
        status="running",
    )
    db.add(run)
    db.commit()
    try:
        output, usage = ProviderGateway(
            connection.provider, model, api_key, connection.base_url
        ).complete(instruction)
        if not output.strip():
            raise ValueError("Provider returned no text")
        run.status = "succeeded"
        run.output_text = output
        run.usage_json = json.dumps(usage)
        run.completed_at = datetime.now(UTC)
        task.status = "review"
        task.output_text = output
        task.last_error = None
    except Exception as error:
        run.status = "failed"
        run.error_message = (
            error.reason if isinstance(error, ProviderUnavailable) else "Provider request failed"
        )
        run.completed_at = datetime.now(UTC)
        task.status = "failed"
        task.last_error = run.error_message
        db.commit()
        raise HTTPException(status_code=502, detail=task.last_error) from error
    db.commit()
    db.refresh(run)
    return run


def run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        task_id=run.task_id,
        provider=run.provider,
        model=run.model,
        status=run.status,
        output_text=run.output_text,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )
