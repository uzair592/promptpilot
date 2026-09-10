from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .context_engine import ContextAssembler, ContextAssemblyInput
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
    package = ContextAssembler().assemble(db, ContextAssemblyInput(
        project_id=project_id, task=payload.task, conversation_id=payload.conversation_id,
        message_id=payload.message_id, analysis_id=payload.analysis_id,
        top_k=payload.top_k, context_budget=payload.budget,
    ))
    return ContextPackageResponse(
        task=package.task,
        project_memory=package.project_memory,
        user_answers=package.user_answers,
        document_context=[
            RetrievedContextResponse(
                content=item.content,
                score=item.score,
                source_type=item.source_type,
                document_id=UUID(item.metadata["document_id"]),
                chunk_id=UUID(item.metadata["chunk_id"]),
                provenance=item.provenance,
                metadata=item.metadata,
            ) for item in package.document_context
        ],
        requirements=package.requirements,
        constraints=package.constraints,
        sources=package.sources,
        omitted_items=package.omitted_items,
        budget=package.budget,
        used_budget=package.used_budget,
    )
