import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .memory_service import ProjectMemoryService
from .models import Document, DocumentChunk

STOP_WORDS = {"the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "is", "with"}


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in STOP_WORDS]


@dataclass(frozen=True)
class RetrievedContextItem:
    content: str
    score: float
    source_type: str
    document_id: UUID | None
    chunk_id: UUID | None
    provenance: str
    metadata: dict[str, str]


class ContextRetriever:
    def retrieve(
        self, db: Session, project_id: UUID, query: str, top_k: int = 5
    ) -> list[RetrievedContextItem]:
        raise NotImplementedError


class LexicalContextRetriever(ContextRetriever):
    def retrieve(
        self, db: Session, project_id: UUID, query: str, top_k: int = 5
    ) -> list[RetrievedContextItem]:
        if not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        query_terms = set(tokenize(query))
        if not query_terms:
            return []
        rows = db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.project_id == project_id, Document.status == "processed")
        ).all()
        ranked: list[RetrievedContextItem] = []
        for chunk, document in rows:
            terms = tokenize(chunk.content)
            overlap = query_terms.intersection(terms)
            phrase_bonus = 1.0 if query.lower() in chunk.content.lower() else 0.0
            score = (len(overlap) / len(query_terms)) + phrase_bonus
            if score > 0:
                ranked.append(
                    RetrievedContextItem(
                        chunk.content,
                        score,
                        "document",
                        document.id,
                        chunk.id,
                        chunk.provenance or f"chunk {chunk.chunk_index + 1}",
                        {"document_name": document.name, "chunk_index": str(chunk.chunk_index)},
                    )
                )
        return sorted(ranked, key=lambda item: (-item.score, str(item.chunk_id)))[:top_k]


@dataclass(frozen=True)
class ContextPackage:
    task: str
    project_memory: list[dict[str, str]]
    user_answers: list[dict[str, str]]
    document_context: list[RetrievedContextItem]
    requirements: list[str]
    constraints: list[str]
    sources: list[dict[str, str]]
    omitted_count: int
    budget: int


class ContextAssembler:
    def __init__(self, retriever: ContextRetriever | None = None) -> None:
        self.retriever = retriever or LexicalContextRetriever()

    def assemble(
        self, db: Session, project_id: UUID, task: str, top_k: int = 5, budget: int = 8000
    ) -> ContextPackage:
        if not 500 <= budget <= 100_000:
            raise ValueError("budget must be between 500 and 100000 characters")
        memory = ProjectMemoryService().active(db, project_id)
        memory_items = [
            {
                "category": item.category,
                "subject": item.subject,
                "content": item.content,
                "source": item.source,
            }
            for item in memory
        ]
        chunks = self.retriever.retrieve(db, project_id, task, top_k)
        used = sum(len(item["content"]) for item in memory_items)
        selected: list[RetrievedContextItem] = []
        for item in chunks:
            if used + len(item.content) > budget:
                continue
            selected.append(item)
            used += len(item.content)
        sources = [
            {"source_type": "memory", "subject": item["subject"], "reason": "active project memory"}
            for item in memory_items
        ]
        sources.extend(
            {
                "source_type": item.source_type,
                "document_id": str(item.document_id),
                "chunk_id": str(item.chunk_id),
                "provenance": item.provenance,
                "score": f"{item.score:.4f}",
            }
            for item in selected
        )
        return ContextPackage(
            task, memory_items, [], selected, [], [], sources, len(chunks) - len(selected), budget
        )
