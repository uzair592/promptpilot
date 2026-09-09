from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Project, ProjectMember, User
from .schemas import ProjectCreateRequest, ProjectUpdateRequest


def create_project(db: Session, user: User, payload: ProjectCreateRequest) -> Project:
    project = Project(
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        domain=payload.domain.strip() if payload.domain else None,
        status="active",
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role="owner",
            status="active",
        )
    )
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session, user_id: UUID, offset: int, limit: int) -> tuple[list[Project], int]:
    query = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id, ProjectMember.status == "active")
        .order_by(Project.created_at.desc(), Project.id.desc())
    )
    total = len(db.scalars(query).all())
    return list(db.scalars(query.offset(offset).limit(limit)).all()), total


def update_project(db: Session, project: Project, payload: ProjectUpdateRequest) -> Project:
    if payload.name is not None:
        project.name = payload.name.strip()
    if payload.description is not None:
        project.description = payload.description.strip() or None
    if payload.domain is not None:
        project.domain = payload.domain.strip() or None
    db.commit()
    db.refresh(project)
    return project


def archive_project(db: Session, project: Project) -> Project:
    project.status = "archived"
    db.commit()
    db.refresh(project)
    return project
