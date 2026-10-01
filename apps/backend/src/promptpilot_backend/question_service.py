from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer_service import AnalysisInput, analyze_input
from .config import get_settings
from .llm_provider import OpenAICompatibleProvider, ProviderUnavailable
from .memory_service import ProjectMemoryService
from .models import Answer, InformationGap, Message, PromptAnalysis, Question, QuestionSession
from .provider_observation import (
    FallbackReason,
    ProviderCallObservation,
    ProviderObserver,
    RequestOutcome,
    notify_observer,
    safe_provider_label,
    sanitized_request_hash,
)
from .question_generator import (
    DeterministicQuestionGenerator,
    ProviderQuestionGenerator,
    QuestionGenerationInput,
    QuestionProvider,
)

SEVERITY_WEIGHT = {"critical": 300, "important": 200, "optional": 100}


def create_question_session(db: Session, analysis: PromptAnalysis) -> QuestionSession:
    """Create the active session after analysis, using the route's existing commit boundary."""

    session = QuestionSession(
        project_id=analysis.project_id,
        conversation_id=analysis.conversation_id,
        analysis_id=analysis.id,
    )
    db.add(session)
    db.commit()
    return session


def next_question(
    db: Session,
    session: QuestionSession,
    provider: QuestionProvider | None = None,
    observer: ProviderObserver | None = None,
) -> Question | None:
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
    session_questions = list(
        db.scalars(select(Question).where(Question.session_id == session.id)).all()
    )
    previous_texts = {" ".join(item.text.lower().split()) for item in session_questions}
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
        previous_questions=tuple(item.text for item in session_questions),
        previous_answers=tuple(
            answer.content for item in session_questions for answer in item.answers
        ),
    )
    generated = DeterministicQuestionGenerator().generate(request)
    source: Literal["ai", "fallback"] = "fallback"
    settings = get_settings()
    configured = (
        settings.llm_provider
        and settings.llm_base_url
        and settings.llm_model
        and settings.llm_api_key
    )
    attempt_outcome: RequestOutcome = "not_attempted"
    fallback_reason: FallbackReason | None = "not_configured"
    request_hash: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    latency_ms: int | None = None
    error_type: str | None = None
    active_provider = (
        provider if provider is not None else (OpenAICompatibleProvider() if configured else None)
    )
    provider_name = safe_provider_label(active_provider.name) if active_provider else None
    model_name = safe_provider_label(active_provider.model) if active_provider else None
    if active_provider is not None:

        def call_provider(payload: dict[str, object]) -> object:
            nonlocal attempt_outcome, request_hash, started_at, finished_at, latency_ms, error_type
            request_hash = sanitized_request_hash("question", model_name, payload)
            started_at = datetime.now(UTC)
            start = perf_counter()
            try:
                response = active_provider.generate_question(payload)
            except Exception as error:
                attempt_outcome = "failed"
                error_type = type(error).__name__
                raise
            else:
                attempt_outcome = "succeeded"
                return response
            finally:
                finished_at = datetime.now(UTC)
                latency_ms = round((perf_counter() - start) * 1000)

        try:
            generated = ProviderQuestionGenerator(active_provider).generate(request, call_provider)
            source = "ai"
            fallback_reason = None
        except (ProviderUnavailable, ValueError):
            fallback_reason = (
                "provider_failed" if attempt_outcome == "failed" else "invalid_question"
            )
        except Exception:
            notify_observer(
                observer,
                ProviderCallObservation(
                    purpose="question",
                    provider=provider_name,
                    model=model_name,
                    request_hash=request_hash,
                    started_at=started_at,
                    finished_at=finished_at,
                    latency_ms=latency_ms,
                    request_outcome=attempt_outcome,
                    service_result="error",
                    error_type=error_type,
                ),
            )
            raise
    if " ".join(generated.question_text.lower().split()) in previous_texts:
        generated = DeterministicQuestionGenerator().generate(request)
        source = "fallback"
        if attempt_outcome == "succeeded" and fallback_reason is None:
            fallback_reason = "duplicate_question"
    notify_observer(
        observer,
        ProviderCallObservation(
            purpose="question",
            provider=provider_name,
            model=model_name,
            request_hash=request_hash,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
            request_outcome=attempt_outcome,
            service_result=source,
            fallback_reason=fallback_reason,
            error_type=error_type,
        ),
    )
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


def skip_and_next_question(
    db: Session,
    session: QuestionSession,
    question: Question,
    provider: QuestionProvider | None = None,
    observer: ProviderObserver | None = None,
) -> Question | None:
    """Commit the skip before selecting the next unresolved gap."""

    if question.session_id != session.id:
        raise ValueError("Question does not belong to the session")
    question.status = "skipped"
    db.commit()
    return next_question(db, session, provider=provider, observer=observer)


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
