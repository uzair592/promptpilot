import csv
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Document, DocumentChunk

ALLOWED_TYPES = {
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@dataclass(frozen=True)
class ParsedContent:
    text: str
    provenance: str


class DocumentParser:
    def parse(self, name: str, media_type: str, content: bytes) -> list[ParsedContent]:
        raise NotImplementedError


class BasicDocumentParser(DocumentParser):
    def parse(self, name: str, media_type: str, content: bytes) -> list[ParsedContent]:
        extension = Path(name).suffix.lower()
        if extension == ".txt":
            return [ParsedContent(content.decode("utf-8-sig", errors="strict"), "text")]
        if extension == ".csv":
            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig", errors="strict"))))
            return [
                ParsedContent("\n".join(", ".join(row) for row in rows), "rows 1-%d" % len(rows))
            ]
        if extension in {".png", ".jpg", ".jpeg"}:
            return []
        raise ValueError(f"Parser for {extension} is not enabled in this processing version")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(
    parsed: list[ParsedContent], size: int = 1200, overlap: int = 120
) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for item in parsed:
        text = normalize(item.text)
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            output.append((text[start:end], item.provenance))
            if end == len(text):
                break
            start = max(start + 1, end - overlap)
    return output


class DocumentService:
    def __init__(self, parser: DocumentParser | None = None) -> None:
        self.parser = parser or BasicDocumentParser()

    def ingest_file(
        self, db: Session, project_id: UUID, name: str, media_type: str, content: bytes
    ) -> Document:
        extension = Path(name).suffix.lower()
        max_size = get_settings().max_upload_bytes
        if extension not in ALLOWED_TYPES or media_type not in {
            ALLOWED_TYPES[extension],
            "application/octet-stream",
        }:
            raise ValueError("Unsupported or mismatched file type")
        if len(content) > max_size:
            raise ValueError("File exceeds configured size limit")
        checksum = hashlib.sha256(content).hexdigest()
        storage_key = f"documents/{project_id}/{uuid4().hex}{extension}"
        storage_root = Path(get_settings().storage_path)
        (storage_root / storage_key).parent.mkdir(parents=True, exist_ok=True)
        (storage_root / storage_key).write_bytes(content)
        document = Document(
            project_id=project_id,
            name=Path(name).name,
            media_type=media_type,
            storage_key=storage_key,
            size_bytes=len(content),
            checksum=checksum,
            status="processing",
        )
        db.add(document)
        db.flush()
        try:
            for index, (text, provenance) in enumerate(
                chunk_text(self.parser.parse(name, media_type, content))
            ):
                db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=text,
                        provenance=provenance,
                        character_count=len(text),
                        processing_version="document-processing-v1",
                    )
                )
            document.status = "processed"
        except Exception as error:
            document.status = "failed"
            document.error_message = str(error)[:500]
        db.commit()
        db.refresh(document)
        return document
