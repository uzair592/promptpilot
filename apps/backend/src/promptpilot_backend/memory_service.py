from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProjectMemoryItem


class ProjectMemoryService:
    def add_user_answer(
        self, db: Session, project_id: UUID, subject: str, content: str
    ) -> ProjectMemoryItem:
        current = db.scalar(
            select(ProjectMemoryItem).where(
                ProjectMemoryItem.project_id == project_id,
                ProjectMemoryItem.subject == subject,
                ProjectMemoryItem.status == "active",
            )
        )
        if current:
            current.status = "superseded"
        item = ProjectMemoryItem(
            project_id=project_id,
            category="user_answer",
            subject=subject,
            content=content.strip(),
            source="user",
            confidence=100,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def active(self, db: Session, project_id: UUID) -> list[ProjectMemoryItem]:
        return list(
            db.scalars(
                select(ProjectMemoryItem)
                .where(
                    ProjectMemoryItem.project_id == project_id, ProjectMemoryItem.status == "active"
                )
                .order_by(ProjectMemoryItem.created_at)
            ).all()
        )
