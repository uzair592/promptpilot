import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .memory_service import ProjectMemoryService
from .models import (
    Answer,
    Document,
    DocumentChunk,
    InformationGap,
    PromptAnalysis,
    Question,
    QuestionSession,
)

STOP_WORDS = {"the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "is", "with", "this", "that"}
SOURCE_AUTHORITY = {"requirement": 1.0, "constraint": 1.0, "memory": 0.88, "answer": 0.82, "document": 0.72}


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if token not in STOP_WORDS]


def normalized(value: str) -> str:
    return " ".join(tokenize(value))


@dataclass(frozen=True)
class ContextAssemblyInput:
    project_id: UUID
    task: str
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    analysis_id: UUID | None = None
    top_k: int = 5
    context_budget: int = 8000
    filters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedContextItem:
    content: str
    score: float
    source_type: str
    document_id: UUID | None
    chunk_id: UUID | None
    provenance: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class ContextCandidate:
    content: str
    source_type: str
    score: float
    priority: float
    identifier: str
    provenance: str
    metadata: dict[str, str]


class ContextRetriever:
    def retrieve(self, db: Session, project_id: UUID, query: str, top_k: int = 5) -> list[RetrievedContextItem]:
        raise NotImplementedError


class LexicalContextRetriever(ContextRetriever):
    def retrieve(self, db: Session, project_id: UUID, query: str, top_k: int = 5) -> list[RetrievedContextItem]:
        if not 1 <= top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        query_terms = set(tokenize(query))
        if not query_terms:
            return []
        rows = db.execute(select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id).where(Document.project_id == project_id, Document.status == "processed")).all()
        ranked = []
        for chunk, document in rows:
            overlap = query_terms.intersection(tokenize(chunk.content))
            phrase_bonus = 1.0 if normalized(query) and normalized(query) in normalized(chunk.content) else 0.0
            score = len(overlap) / len(query_terms) + phrase_bonus
            if score > 0:
                ranked.append(RetrievedContextItem(chunk.content, score, "document", document.id, chunk.id, chunk.provenance or f"chunk {chunk.chunk_index + 1}", {"document_name": document.name, "chunk_index": str(chunk.chunk_index)}))
        return sorted(ranked, key=lambda item: (-item.score, str(item.chunk_id)))[:top_k]


class ContextAssembler:
    def __init__(self, retriever: ContextRetriever | None = None) -> None:
        self.retriever = retriever or LexicalContextRetriever()

    @staticmethod
    def _relevance(task: str, content: str, category: str = "") -> float:
        terms = set(tokenize(task))
        return len(terms.intersection(set(tokenize(f"{category} {content}")))) / len(terms) if terms else 0.0

    def _answers(self, db: Session, data: ContextAssemblyInput) -> list[ContextCandidate]:
        query = select(Answer, Question, QuestionSession).join(Question, Question.id == Answer.question_id).join(QuestionSession, QuestionSession.id == Question.session_id).where(QuestionSession.project_id == data.project_id, Answer.source == "user")
        if data.conversation_id:
            query = query.where(QuestionSession.conversation_id == data.conversation_id)
        rows = db.execute(query).all()
        result = []
        for answer, question, session in rows:
            relevance = self._relevance(data.task, f"{question.text} {answer.content}")
            if relevance:
                result.append(ContextCandidate(answer.content, "answer", relevance, SOURCE_AUTHORITY["answer"], str(answer.id), f"question {question.id} / session {session.id}", {"question_id": str(question.id), "session_id": str(session.id), "source": "user"}))
        return result

    def assemble(self, db: Session, input_data: ContextAssemblyInput | UUID, task: str | None = None, top_k: int = 5, budget: int = 8000) -> "ContextPackage":
        if isinstance(input_data, UUID):
            input_data = ContextAssemblyInput(input_data, task or "", top_k=top_k, context_budget=budget)
        if not input_data.task.strip():
            raise ValueError("task is required")
        if not 500 <= input_data.context_budget <= 100_000:
            raise ValueError("context_budget must be between 500 and 100000 characters")
        candidates: list[ContextCandidate] = []
        for item in ProjectMemoryService().active(db, input_data.project_id):
            relevance = self._relevance(input_data.task, f"{item.subject} {item.content}", item.category)
            if relevance:
                authority = SOURCE_AUTHORITY["memory"] + (0.12 if item.source == "user" else 0)
                candidates.append(ContextCandidate(item.content, "memory", relevance, authority, str(item.id), f"memory {item.category}: {item.subject}", {"category": item.category, "subject": item.subject, "source": item.source}))
        candidates.extend(self._answers(db, input_data))
        document_items = self.retriever.retrieve(db, input_data.project_id, input_data.task, input_data.top_k)
        for doc_item in document_items:
            candidates.append(ContextCandidate(doc_item.content, "document", doc_item.score / 2, SOURCE_AUTHORITY["document"], str(doc_item.chunk_id), doc_item.provenance, {**doc_item.metadata, "document_id": str(doc_item.document_id), "chunk_id": str(doc_item.chunk_id)}))
        if input_data.analysis_id:
            analysis = db.get(PromptAnalysis, input_data.analysis_id)
            if analysis:
                for gap in db.scalars(select(InformationGap).where(InformationGap.analysis_id == analysis.id, InformationGap.status != "resolved")).all():
                    if gap.dimension == "constraints" and self._relevance(input_data.task, gap.description):
                        candidates.append(ContextCandidate(gap.description, "constraint", self._relevance(input_data.task, gap.description), SOURCE_AUTHORITY["constraint"], str(gap.id), f"analysis gap {gap.id}", {"gap_id": str(gap.id), "source": "ai_inferred"}))
        candidates.sort(key=lambda item: (-item.priority * item.score, -item.score, item.source_type, item.identifier))
        selected: list[ContextCandidate] = []
        omissions: list[dict[str, str]] = []
        seen: dict[str, int] = {}
        used = 0
        for candidate in candidates:
            key = normalized(candidate.content)
            if not key:
                continue
            if key in seen:
                old = selected[seen[key]]
                selected[seen[key]] = ContextCandidate(old.content, old.source_type, old.score, old.priority, old.identifier, old.provenance, {**old.metadata, "also_supported_by": f"{old.source_type},{candidate.source_type}"})
                continue
            if used + len(candidate.content) > input_data.context_budget:
                omissions.append({"source_type": candidate.source_type, "identifier": candidate.identifier, "reason": "lower priority or does not fit budget", "score": f"{candidate.score:.4f}", "priority": f"{candidate.priority:.4f}"})
                continue
            seen[key] = len(selected)
            selected.append(candidate)
            used += len(candidate.content)
        def values(source: str) -> list[dict[str, str]]:
            return [{"content": item.content, "source": item.metadata.get("source", item.source_type), "provenance": item.provenance, "why_included": "Matched task terms and source authority."} for item in selected if item.source_type == source]
        return ContextPackage(input_data.task, values("memory"), values("answer"), values("requirement"), values("constraint"), [item for item in selected if item.source_type == "document"], [{"source_type": item.source_type, "identifier": item.identifier, "provenance": item.provenance, "score": f"{item.score:.4f}", "why_included": "Matched task terms and source authority."} for item in selected], omissions, input_data.context_budget, used)


@dataclass(frozen=True)
class ContextPackage:
    task: str
    project_memory: list[dict[str, str]]
    user_answers: list[dict[str, str]]
    requirements: list[dict[str, str]]
    constraints: list[dict[str, str]]
    document_context: list[ContextCandidate]
    sources: list[dict[str, str]]
    omitted_items: list[dict[str, str]]
    budget: int
    used_budget: int
