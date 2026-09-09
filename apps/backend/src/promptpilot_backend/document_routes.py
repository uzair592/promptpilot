from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .dependencies import current_user
from .document_service import DocumentService
from .models import Document, User
from .project_policy import ProjectRole, require_project_access
from .schemas import DocumentResponse

router = APIRouter(prefix="/api/v1/projects/{project_id}/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    project_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    require_project_access(db, project_id, user.id, ProjectRole.EDITOR)
    try:
        document = DocumentService().ingest_file(
            db,
            project_id,
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            file.file.read(),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return DocumentResponse.model_validate(document)


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    project_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[DocumentResponse]:
    require_project_access(db, project_id, user.id, ProjectRole.MEMBER)
    return [
        DocumentResponse.model_validate(item)
        for item in db.scalars(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        ).all()
    ]
