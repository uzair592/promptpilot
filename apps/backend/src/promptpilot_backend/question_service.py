from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer_service import AnalysisInput, analyze_input
from .config import get_settings
from .llm_provider import OpenAICompatibleProvider, ProviderUnavailable
from .memory_service import ProjectMemoryService
from .models import Answer, InformationGap, Message, PromptAnalysis, Question, QuestionSession
from .question_generator import (
    DeterministicQuestionGenerator,
    ProviderQuestionGenerator,
    QuestionGenerationInput,
)

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
    previous_texts = {" ".join(item.text.lower().split()) for item in session.questions}
    priority = SEVERITY_WEIGHT.get(gap.severity, 0)
    analysis = db.get(PromptAnalysis, session.latest_analysis_id or session.analysis_id)
    original = db.get(Message, analysis.message_id) if analysis else None
    memory = ProjectMemoryService().active(db, session.project_id)
    request = QuestionGenerationInput(
        original_prompt=original.content if original else "",
        task_category=analysis.task_category if analysis else "general",
        gap_id=str(gap.id),
        gap_target=gap.question_target,
        severity=gap.severity,
        importance=gap.importance,
        priority=priority,
        memory=tuple({"subject": item.subject, "content": item.content} for item in memory),
        previous_questions=tuple(item.text for item in session.questions),
        previous_answers=tuple(
            answer.content for item in session.questions for answer in item.answers
        ),
    )
    generated = DeterministicQuestionGenerator().generate(request)
    source = "fallback"
    settings = get_settings()
    if (
        settings.llm_provider
        and settings.llm_base_url
        and settings.llm_model
        and settings.llm_api_key
    ):
        try:
            generated = ProviderQuestionGenerator(OpenAICompatibleProvider()).generate(request)
            source = "ai"
        except (ProviderUnavailable, ValueError):
            pass
    if " ".join(generated.question_text.lower().split()) in previous_texts:
        generated = DeterministicQuestionGenerator().generate(request)
        source = "fallback"
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
    input_value = AnalysisInput(
        original_prompt=original.content,
        task_category=previous.task_category,
        memory_items=tuple({"subject": item.subject, "content": item.content} for item in memory),
        relevant_answers=tuple(item.content for item in memory if item.source == "user"),
    )
    analysis = analyze_input(
        db, previous.project_id, previous.conversation_id, input_value, original.id
    )
    session.latest_analysis_id = analysis.id
    answered_question = db.get(Question, answer.question_id)
    old_gap = db.get(InformationGap, answered_question.gap_id) if answered_question else None
    if old_gap:
        old_gap.status = "partially_resolved"
    db.commit()
    return analysis
