from base64 import urlsafe_b64decode, urlsafe_b64encode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .db import get_db
from .dependencies import current_user
from .models import Project, User
from .project_policy import ProjectRole, require_project_access
from .project_service import archive_project, create_project, list_projects, update_project
from .schemas import (
    PageMetadata,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(urlsafe_b64decode(cursor.encode()).decode())
        if offset < 0:
            raise ValueError
        return offset
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid pagination cursor") from None


def encode_cursor(offset: int) -> str:
    return urlsafe_b64encode(str(offset).encode()).decode()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create(
    payload: ProjectCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Project:
    return create_project(db, user, payload)


@router.get("", response_model=ProjectListResponse)
def list_accessible(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectListResponse:
    offset = decode_cursor(cursor)
    projects, total = list_projects(db, user.id, offset, limit)
    next_cursor = encode_cursor(offset + limit) if offset + limit < total else None
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(project) for project in projects],
        page=PageMetadata(cursor=cursor, next_cursor=next_cursor, limit=limit, total=total),
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def detail(
    project_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    project, member = require_project_access(db, project_id, user.id)
    return ProjectDetailResponse(
        **ProjectResponse.model_validate(project).model_dump(),
        current_user_role=member.role,
        members=[
            ProjectMemberResponse.model_validate(project_member, from_attributes=True)
            for project_member in project.members
        ],
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
def update(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Project:
    project, _ = require_project_access(db, project_id, user.id, ProjectRole.EDITOR)
    return update_project(db, project, payload)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
def archive(
    project_id: UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Project:
    project, _ = require_project_access(db, project_id, user.id, ProjectRole.OWNER)
    return archive_project(db, project)
