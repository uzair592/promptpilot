from enum import StrEnum
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Project, ProjectMember


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    MEMBER = "member"


def membership_for(db: Session, project_id: UUID, user_id: UUID) -> ProjectMember | None:
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.status == "active",
        )
    )


def require_project_access(
    db: Session, project_id: UUID, user_id: UUID, minimum_role: ProjectRole = ProjectRole.MEMBER
) -> tuple[Project, ProjectMember]:
    project = db.get(Project, project_id)
    member = membership_for(db, project_id, user_id)
    if project is None or member is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "archived" and minimum_role != ProjectRole.MEMBER:
        raise HTTPException(status_code=409, detail="Archived projects cannot be modified")
    rank = {ProjectRole.MEMBER: 1, ProjectRole.EDITOR: 2, ProjectRole.OWNER: 3}
    if rank[ProjectRole(member.role)] < rank[minimum_role]:
        raise HTTPException(status_code=403, detail="You do not have permission for this project")
    return project, member


def can_manage_membership(member: ProjectMember) -> bool:
    return member.role == ProjectRole.OWNER
