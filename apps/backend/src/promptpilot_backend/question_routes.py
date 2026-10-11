from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conversation_routes import conversation_access
from .db import get_db
from .dependencies import current_user
from .memory_service import ProjectMemoryService
from .models import Answer, Question, QuestionSession, User
from .project_policy import ProjectRole
from .question_service import (
    answer_question,
    next_question,
    reanalyze_after_answer,
    skip_and_next_question,
)
from .schemas import (
    AnswerCreateRequest,
    ClarificationAnswerResponse,
    ProjectMemoryResponse,
    PromptAnalysisResponse,
    QuestionResponse,
    QuestionSessionResponse,
)

router = APIRouter(prefix="/api/v1/conversations/{conversation_id}", tags=["questions"])


def answered_questions(
    db: Session, session: QuestionSession
) -> list[ClarificationAnswerResponse]:
    rows = db.execute(
        select(Answer, Question)
        .join(Question, Question.id == Answer.question_id)
        .where(Question.session_id == session.id, Answer.source == "user")
        .order_by(Answer.created_at)
    ).all()
    return [
        ClarificationAnswerResponse(
            id=answer.id,
            question_id=question.id,
            question=question.text,
            content=answer.content,
            created_at=answer.created_at,
        )
        for answer, question in rows
    ]


def authorized_session(db: Session, conversation_id: UUID, user: User) -> QuestionSession:
    conversation, project, _ = conversation_access(db, conversation_id, user, ProjectRole.MEMBER)
    session = db.scalar(
        select(QuestionSession)
        .where(QuestionSession.conversation_id == conversation.id)
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
        answered_questions=answered_questions(db, session),
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
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Question session is already complete")
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.session_id == session.id)
    )
    if question is None or question.status != "presented":
        raise HTTPException(status_code=404, detail="Question not found or no longer answerable")
    answer = answer_question(db, question, payload.content)
    ProjectMemoryService().add_user_answer(db, session.project_id, question.text, answer.content)
    analysis = reanalyze_after_answer(db, session, answer)
    question = next_question(db, session)
    return QuestionSessionResponse(
        id=session.id,
        status=session.status,
        stop_reason=session.stop_reason,
        next_question=QuestionResponse.model_validate(question) if question else None,
        analysis=PromptAnalysisResponse.model_validate(analysis),
        answered_questions=answered_questions(db, session),
        memory_updates=[
            ProjectMemoryResponse.model_validate(item)
            for item in ProjectMemoryService().active(db, session.project_id)
        ],
    )


@router.post("/questions/{question_id}/skip", response_model=QuestionSessionResponse)
def skip_question(
    conversation_id: UUID,
    question_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> QuestionSessionResponse:
    session = authorized_session(db, conversation_id, user)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Question session is already complete")
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.session_id == session.id)
    )
    if question is None or question.status != "presented":
        raise HTTPException(status_code=404, detail="Question not found or no longer skippable")
    next_item = skip_and_next_question(db, session, question)
    return QuestionSessionResponse(
        id=session.id,
        status=session.status,
        stop_reason=session.stop_reason,
        next_question=QuestionResponse.model_validate(next_item) if next_item else None,
        answered_questions=answered_questions(db, session),
    )
