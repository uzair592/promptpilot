from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Conversation, ConversationMessageCounter, Message, Project
from .schemas import ConversationCreateRequest, ConversationUpdateRequest, MessageCreateRequest


def create_conversation(
    db: Session, project: Project, payload: ConversationCreateRequest
) -> Conversation:
    conversation = Conversation(
        project_id=project.id,
        title=payload.title.strip(),
        status="active",
    )
    db.add(conversation)
    db.flush()
    db.add(ConversationMessageCounter(conversation_id=conversation.id, last_sequence=0))
    db.commit()
    db.refresh(conversation)
    return conversation


def list_conversations(
    db: Session, project_id: UUID, offset: int, limit: int
) -> tuple[list[Conversation], int]:
    query = select(Conversation).where(Conversation.project_id == project_id).order_by(
        Conversation.updated_at.desc(), Conversation.id.desc()
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.project_id == project_id)
        )
        or 0
    )
    return list(db.scalars(query.offset(offset).limit(limit)).all()), total


def update_conversation(
    db: Session, conversation: Conversation, payload: ConversationUpdateRequest
) -> Conversation:
    if payload.title is not None:
        conversation.title = payload.title.strip()
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation(db: Session, conversation_id: UUID) -> Conversation | None:
    return db.get(Conversation, conversation_id)


def add_message(
    db: Session,
    conversation: Conversation,
    payload: MessageCreateRequest,
    idempotency_key: str | None,
) -> Message:
    if idempotency_key:
        existing = db.scalar(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
    counter = db.scalar(
        select(ConversationMessageCounter)
        .where(ConversationMessageCounter.conversation_id == conversation.id)
        .with_for_update()
    )
    if counter is None:
        counter = ConversationMessageCounter(conversation_id=conversation.id, last_sequence=0)
        db.add(counter)
        db.flush()
    counter.last_sequence += 1
    message = Message(
        conversation_id=conversation.id,
        role=payload.role,
        content=payload.content.strip(),
        sequence=counter.last_sequence,
        idempotency_key=idempotency_key,
    )
    db.add(message)
    conversation.updated_at = func.now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.idempotency_key == idempotency_key,
                )
            )
            if existing:
                return existing
        raise
    db.refresh(message)
    return message


def list_messages(
    db: Session, conversation_id: UUID, offset: int, limit: int
) -> tuple[list[Message], int]:
    query = select(Message).where(Message.conversation_id == conversation_id).order_by(
        Message.sequence.asc()
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        or 0
    )
    return list(db.scalars(query.offset(offset).limit(limit)).all()), total
