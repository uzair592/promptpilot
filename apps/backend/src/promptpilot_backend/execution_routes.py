import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conversation_routes import conversation_access
from .db import get_db
from .dependencies import current_user
from .execution_service import LLMExecutionService, load_execution_targets
from .models import ModelRun, User
from .project_policy import ProjectRole
from .schemas import ExecutePromptRequest, ModelRunResponse

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}/prompts", tags=["execution"])


def response(run: ModelRun) -> ModelRunResponse:
    return ModelRunResponse(id=run.id, prompt_version_id=run.prompt_version_id, execution_strategy=run.execution_strategy, optimized_prompt=run.optimized_prompt, response_text=run.response_text, provider=run.provider, model=run.model, status=run.status, finish_reason=run.finish_reason, usage=json.loads(run.usage_json), latency_ms=run.latency_ms, error_message=run.error_message, created_at=run.created_at)


@router.post("/{prompt_version_id}/execute", response_model=ModelRunResponse)
def execute_prompt(conversation_id: UUID, prompt_version_id: UUID, payload: ExecutePromptRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ModelRunResponse:
    conversation, _, _ = conversation_access(db, conversation_id, user, ProjectRole.EDITOR)
    try:
        version, message = load_execution_targets(db, conversation.id, prompt_version_id if payload.strategy == "promptpilot" else None, payload.message_id, payload.strategy)
        run, _ = LLMExecutionService().execute(db, version, message, payload.system_instruction, payload.parameters, payload.strategy)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except Exception:
        raise HTTPException(status_code=503, detail="Target model execution is unavailable") from None
    return response(run)


@router.get("/runs", response_model=list[ModelRunResponse])
def list_runs(conversation_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[ModelRunResponse]:
    conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    runs = db.scalars(select(ModelRun).where(ModelRun.conversation_id == conversation_id).order_by(ModelRun.created_at.desc())).all()
    return [response(run) for run in runs]
