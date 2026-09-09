from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .db import get_db
from .dependencies import current_user
from .memory_service import ProjectMemoryService
from .models import User
from .project_policy import ProjectRole, require_project_access
from .schemas import ProjectMemoryResponse

router = APIRouter(prefix="/api/v1/projects/{project_id}/memory", tags=["memory"])


@router.get("", response_model=list[ProjectMemoryResponse])
def list_memory(
    project_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ProjectMemoryResponse]:
    require_project_access(db, project_id, user.id, ProjectRole.MEMBER)
    return [
        ProjectMemoryResponse.model_validate(item)
        for item in ProjectMemoryService().active(db, project_id)
    ]
