from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conversation_routes import conversation_access
from .db import get_db
from .dependencies import current_user
from .models import Question, QuestionSession, User
from .project_policy import ProjectRole
from .question_service import answer_question, next_question, reanalyze_after_answer
from .schemas import AnswerCreateRequest, QuestionResponse, QuestionSessionResponse

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}", tags=["questions"])


def authorized_session(db: Session, conversation_id: UUID, user: User) -> QuestionSession:
    conversation, project, _ = conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    session = db.scalar(
        select(QuestionSession)
        .where(
            QuestionSession.conversation_id == conversation.id, QuestionSession.status == "active"
        )
        .order_by(QuestionSession.created_at.desc())
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Question session not found")
    return session


@router.get("/questions/next", response_model=QuestionSessionResponse)
def get_next(
    conversation_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> QuestionSessionResponse:
    session = authorized_session(db, conversation_id, user)
    question = next_question(db, session)
    return QuestionSessionResponse(
        id=session.id,
        status=session.status,
        stop_reason=session.stop_reason,
        next_question=QuestionResponse.model_validate(question) if question else None,
    )


@router.post(
    "/questions/{question_id}/answers",
    response_model=QuestionSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_answer(
    conversation_id: UUID,
    question_id: UUID,
    payload: AnswerCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QuestionSessionResponse:
    session = authorized_session(db, conversation_id, user)
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.session_id == session.id)
    )
    if question is None or question.status != "presented":
        raise HTTPException(status_code=404, detail="Question not found or no longer answerable")
    answer = answer_question(db, question, payload.content)
    reanalyze_after_answer(db, session, answer)
    question = next_question(db, session)
    return QuestionSessionResponse(
        id=session.id,
        status=session.status,
        stop_reason=session.stop_reason,
        next_question=QuestionResponse.model_validate(question) if question else None,
    )


@router.post("/questions/{question_id}/skip", response_model=QuestionSessionResponse)
def skip_question(
    conversation_id: UUID,
    question_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QuestionSessionResponse:
    session = authorized_session(db, conversation_id, user)
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.session_id == session.id)
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    question.status = "skipped"
    db.commit()
    next_item = next_question(db, session)
    return QuestionSessionResponse(
        id=session.id,
        status=session.status,
        stop_reason=session.stop_reason,
        next_question=QuestionResponse.model_validate(next_item) if next_item else None,
    )
