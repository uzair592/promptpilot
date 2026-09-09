from base64 import urlsafe_b64decode, urlsafe_b64encode
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from .conversation_service import (
    add_message,
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    update_conversation,
)
from .db import get_db
from .dependencies import current_user
from .models import Conversation, Project, User
from .project_policy import ProjectRole, require_project_access
from .schemas import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageCreateRequest,
    MessageListResponse,
    MessageResponse,
    PageMetadata,
)

project_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/conversations", tags=["conversations"]
)
conversation_router = APIRouter(
    prefix="/api/v1/conversations/{conversation_id}", tags=["conversations"]
)


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(urlsafe_b64decode(cursor.encode()).decode())
        if value < 0:
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid pagination cursor") from None


def encode_cursor(offset: int) -> str:
    return urlsafe_b64encode(str(offset).encode()).decode()


def conversation_access(
    db: Session, conversation_id: UUID, user: User, role: ProjectRole = ProjectRole.MEMBER
) -> tuple[Conversation, Project, str]:
    conversation = get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    project, member = require_project_access(db, conversation.project_id, user.id, role)
    return conversation, project, member.role


@project_router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create(
    project_id: UUID,
    payload: ConversationCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Conversation:
    project, _ = require_project_access(db, project_id, user.id, ProjectRole.EDITOR)
    return create_conversation(db, project, payload)


@project_router.get("", response_model=ConversationListResponse)
def list_for_project(
    project_id: UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConversationListResponse:
    require_project_access(db, project_id, user.id)
    offset = decode_cursor(cursor)
    conversations, total = list_conversations(db, project_id, offset, limit)
    next_cursor = encode_cursor(offset + limit) if offset + limit < total else None
    return ConversationListResponse(
        items=[ConversationResponse.model_validate(item) for item in conversations],
        page=PageMetadata(cursor=cursor, next_cursor=next_cursor, limit=limit, total=total),
    )


@conversation_router.get("", response_model=ConversationDetailResponse)
def detail(
    conversation_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ConversationDetailResponse:
    conversation, _, role = conversation_access(db, conversation_id, user)
    return ConversationDetailResponse(
        **ConversationResponse.model_validate(conversation).model_dump(), current_user_role=role
    )


@conversation_router.patch("", response_model=ConversationResponse)
def update(
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Conversation:
    conversation, project, _ = conversation_access(db, conversation_id, user, ProjectRole.EDITOR)
    if conversation.status == "archived" or project.status == "archived":
        raise HTTPException(status_code=409, detail="Archived conversations cannot be modified")
    return update_conversation(db, conversation, payload)


@conversation_router.post(
    "/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED
)
def create_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    conversation, project, _ = conversation_access(db, conversation_id, user, ProjectRole.EDITOR)
    if conversation.status == "archived" or project.status == "archived":
        raise HTTPException(status_code=409, detail="Archived conversations cannot be modified")
    if idempotency_key and len(idempotency_key) > 128:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    return MessageResponse.model_validate(add_message(db, conversation, payload, idempotency_key))


@conversation_router.get("/messages", response_model=MessageListResponse)
def list_for_conversation(
    conversation_id: UUID,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    conversation_access(db, conversation_id, user)
    offset = decode_cursor(cursor)
    messages, total = list_messages(db, conversation_id, offset, limit)
    next_cursor = encode_cursor(offset + limit) if offset + limit < total else None
    return MessageListResponse(
        items=[MessageResponse.model_validate(item) for item in messages],
        page=PageMetadata(cursor=cursor, next_cursor=next_cursor, limit=limit, total=total),
    )
