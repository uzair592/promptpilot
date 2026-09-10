from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .context_engine import ContextAssembler
from .db import get_db
from .dependencies import current_user
from .models import User
from .project_policy import ProjectRole, require_project_access
from .schemas import ContextAssembleRequest, ContextPackageResponse, RetrievedContextResponse

router = APIRouter(prefix="/api/v1/projects/{project_id}/context", tags=["context"])


@router.post("/assemble", response_model=ContextPackageResponse)
def assemble_context(
    project_id: UUID,
    payload: ContextAssembleRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ContextPackageResponse:
    require_project_access(db, project_id, user.id, ProjectRole.MEMBER)
    package = ContextAssembler().assemble(
        db, project_id, payload.task, payload.top_k, payload.budget
    )
    return ContextPackageResponse(
        task=package.task,
        project_memory=package.project_memory,
        user_answers=package.user_answers,
        document_context=[
            RetrievedContextResponse(**item.__dict__) for item in package.document_context
        ],
        requirements=package.requirements,
        constraints=package.constraints,
        sources=package.sources,
        omitted_count=package.omitted_count,
        budget=package.budget,
    )
