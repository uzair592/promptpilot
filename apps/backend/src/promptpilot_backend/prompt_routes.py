import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conversation_routes import conversation_access
from .db import get_db
from .dependencies import current_user
from .models import Message, PromptAnalysis, PromptVersion, User
from .project_policy import ProjectRole
from .prompt_generation import PromptGenerator, build_generation_input, persist_generation
from .schemas import PromptGenerateRequest, PromptGenerationResponse

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}/prompts", tags=["prompts"])


def prompt_response(version: PromptVersion) -> PromptGenerationResponse:
    metadata = json.loads(version.metadata_json)
    metadata.update(
        {
            "provider": version.provider,
            "model": version.model,
            "generation_mode": version.generation_mode,
            "fallback_used": version.fallback_used,
        }
    )
    return PromptGenerationResponse(
        version_id=version.id,
        version_number=version.version_number,
        source_message_id=version.source_message_id,
        created_at=version.created_at,
        original_prompt=version.original_prompt,
        optimized_prompt=version.optimized_prompt,
        task_summary=str(metadata.get("task_summary", "")),
        assumptions=list(metadata.get("assumptions", [])),
        incorporated_context=list(metadata.get("incorporated_context", [])),
        incorporated_requirements=list(metadata.get("incorporated_requirements", [])),
        output_format=str(metadata.get("output_format", "")),
        quality_notes=list(metadata.get("quality_notes", [])),
        warnings=list(metadata.get("warnings", [])),
        generation_metadata=metadata,
    )


@router.get("", response_model=list[PromptGenerationResponse])
def list_prompts(
    conversation_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[PromptGenerationResponse]:
    conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    versions = db.scalars(
        select(PromptVersion)
        .where(PromptVersion.conversation_id == conversation_id)
        .order_by(PromptVersion.version_number.desc())
    ).all()
    return [prompt_response(version) for version in versions]


@router.post("/generate", response_model=PromptGenerationResponse)
def generate_prompt(
    conversation_id: UUID,
    payload: PromptGenerateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PromptGenerationResponse:
    conversation, _, _ = conversation_access(db, conversation_id, user, ProjectRole.EDITOR)
    message = db.get(Message, payload.message_id)
    if message is None or message.conversation_id != conversation.id or message.role != "user":
        raise HTTPException(status_code=404, detail="Source user message not found")
    analysis = db.scalar(
        select(PromptAnalysis)
        .where(PromptAnalysis.message_id == message.id)
        .order_by(PromptAnalysis.created_at.desc())
    )
    try:
        input_data, package = build_generation_input(
            db, message, analysis, payload.mode, payload.regeneration_instruction
        )
        outcome = PromptGenerator().generate(input_data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except Exception:
        raise HTTPException(
            status_code=503, detail="Prompt generation is temporarily unavailable"
        ) from None
    version = persist_generation(
        db, message, analysis, outcome, message.content, payload.mode, package
    )
    metadata = json.loads(version.metadata_json)
    metadata.update(
        {
            "output_format": outcome.result.output_format,
            "quality_notes": outcome.result.quality_notes,
        }
    )
    version.metadata_json = json.dumps(metadata)
    db.commit()
    db.refresh(version)
    return prompt_response(version)
