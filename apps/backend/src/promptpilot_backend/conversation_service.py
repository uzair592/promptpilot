from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Conversation, Message, Project
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
    db.commit()
    db.refresh(conversation)
    return conversation


def list_conversations(
    db: Session, project_id: UUID, offset: int, limit: int
) -> tuple[list[Conversation], int]:
    query = select(Conversation).where(Conversation.project_id == project_id).order_by(
        Conversation.updated_at.desc(), Conversation.id.desc()
    )
    total = len(db.scalars(query).all())
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
    current_sequence = db.scalar(
        select(func.max(Message.sequence)).where(Message.conversation_id == conversation.id)
    ) or 0
    message = Message(
        conversation_id=conversation.id,
        role=payload.role,
        content=payload.content.strip(),
        sequence=current_sequence + 1,
        idempotency_key=idempotency_key,
    )
    db.add(message)
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
    total = len(db.scalars(query).all())
    return list(db.scalars(query.offset(offset).limit(limit)).all()), total
