from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer_v2 import analyze_hybrid
from .conversation_routes import conversation_access
from .db import get_db
from .dependencies import current_user
from .llm_provider import ProviderError
from .models import Message, QuestionSession, User
from .project_policy import ProjectRole
from .schemas import PromptAnalysisResponse

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}/messages", tags=["analysis"])


@router.post(
    "/{message_id}/analysis",
    response_model=PromptAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis(
    conversation_id: UUID,
    message_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    mode: str = Query(default="hybrid"),
) -> PromptAnalysisResponse:
    conversation, project, _ = conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    message = db.scalar(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role != "user":
        raise HTTPException(status_code=422, detail="Only user messages can be analyzed")
    try:
        analysis = analyze_hybrid(db, project.id, conversation.id, message, mode)
        db.add(
            QuestionSession(
                project_id=project.id, conversation_id=conversation.id, analysis_id=analysis.id
            )
        )
        db.commit()
        return PromptAnalysisResponse.model_validate(analysis)
    except ProviderError as error:
        raise HTTPException(status_code=503, detail=error.reason) from None
