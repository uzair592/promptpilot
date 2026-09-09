from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer_service import analyze_message
from .config import get_settings
from .llm_provider import OpenAICompatibleProvider, ProviderUnavailable
from .memory_service import ProjectMemoryService
from .models import Answer, InformationGap, Message, PromptAnalysis, Question, QuestionSession
from .question_generator import DeterministicQuestionGenerator, ProviderQuestionGenerator

SEVERITY_WEIGHT = {"critical": 300, "important": 200, "optional": 100}


def next_question(db: Session, session: QuestionSession) -> Question | None:
    existing_gap_ids = select(Question.gap_id).where(
        Question.session_id == session.id,
        Question.status.in_(("answered", "skipped", "dismissed", "obsolete")),
    )
    gaps = list(
        db.scalars(
            select(InformationGap).where(
                InformationGap.analysis_id == (session.latest_analysis_id or session.analysis_id),
                InformationGap.status.in_(("unresolved", "partially_resolved")),
                InformationGap.id.not_in(existing_gap_ids),
            )
        ).all()
    )
    if not gaps:
        session.status = "completed"
        session.stop_reason = "no_unresolved_gaps"
        db.commit()
        return None
    gap = max(gaps, key=lambda item: (SEVERITY_WEIGHT.get(item.severity, 0), item.importance))
    priority = SEVERITY_WEIGHT.get(gap.severity, 0)
    generated = DeterministicQuestionGenerator().generate(
        gap.question_target, str(gap.id), priority
    )
    source = "fallback"
    settings = get_settings()
    if (
        settings.llm_provider
        and settings.llm_base_url
        and settings.llm_model
        and settings.llm_api_key
    ):
        try:
            generated = ProviderQuestionGenerator(OpenAICompatibleProvider()).generate(
                gap.question_target, str(gap.id), priority
            )
            source = "ai"
        except (ProviderUnavailable, ValueError):
            pass
    question = Question(
        session_id=session.id,
        gap_id=gap.id,
        text=generated.question_text,
        question_type=generated.question_type,
        priority=generated.priority,
        status="presented",
        source=source,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def answer_question(db: Session, question: Question, content: str) -> Answer:
    answer = Answer(question_id=question.id, content=content.strip(), source="user")
    db.add(answer)
    question.status = "answered"
    question.answered_at = datetime.now(UTC)
    db.commit()
    db.refresh(answer)
    return answer


def reanalyze_after_answer(db: Session, session: QuestionSession, answer: Answer) -> PromptAnalysis:
    previous = db.get(PromptAnalysis, session.latest_analysis_id or session.analysis_id)
    if previous is None:
        raise ValueError("Question session analysis is missing")
    original = db.get(Message, previous.message_id)
    if original is None:
        raise ValueError("Question source message is missing")
    memory = ProjectMemoryService().active(db, previous.project_id)
    context = "\n".join(f"{item.subject}: {item.content}" for item in memory)
    analysis = analyze_message(
        db, previous.project_id, previous.conversation_id, original, context=context
    )
    session.latest_analysis_id = analysis.id
    answered_question = db.get(Question, answer.question_id)
    old_gap = db.get(InformationGap, answered_question.gap_id) if answered_question else None
    if old_gap:
        old_gap.status = "partially_resolved"
    db.commit()
    return analysis
