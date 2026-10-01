from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from .analyzer_service import analyze_message
from .llm_provider import (
    AIAnalysis,
    OpenAICompatibleProvider,
    ProviderConfigurationError,
    ProviderUnavailable,
)
from .models import InformationGap, Message, PromptAnalysis
from .provider_observation import (
    ProviderCallObservation,
    ProviderObserver,
    notify_observer,
    safe_provider_label,
    sanitized_request_hash,
)


class AnalysisProvider(Protocol):
    name: str
    model: str

    def analyze(self, prompt: str) -> AIAnalysis: ...


class AnalysisReconciler:
    """Merge validated semantic findings while keeping scoring deterministic."""

    def reconcile(self, baseline: PromptAnalysis, ai_result: AIAnalysis) -> PromptAnalysis:
        if ai_result.task_category:
            baseline.task_category = ai_result.task_category
        for dimension in baseline.dimensions:
            ai_dimension = ai_result.dimensions.get(dimension.key)
            if ai_dimension is None or not ai_dimension.applicable:
                continue
            dimension.applicable = True
            dimension.score = ai_dimension.score
            dimension.status = ai_dimension.status
            dimension.evidence = ai_dimension.evidence or dimension.evidence
            dimension.explanation = ai_dimension.explanation or dimension.explanation
        existing = {(gap.dimension, gap.title.lower()) for gap in baseline.gaps}
        for gap in ai_result.information_gaps:
            key = (gap.dimension, gap.title.lower())
            if key in existing:
                continue
            baseline.gaps.append(
                InformationGap(
                    dimension=gap.dimension,
                    title=gap.title,
                    description=gap.description,
                    severity=gap.severity,
                    importance=gap.importance,
                    question_target=gap.question_target,
                    status="unresolved",
                )
            )
            existing.add(key)
        applicable = [
            item for item in baseline.dimensions if item.applicable and item.score is not None
        ]
        baseline.overall_score = round(
            sum(item.score or 0 for item in applicable) / len(applicable)
        )
        baseline.status = (
            "Good"
            if baseline.overall_score >= 80
            else "Medium"
            if baseline.overall_score >= 50
            else "Poor"
        )
        return baseline


def analyze_hybrid(
    db: Session,
    project_id: UUID,
    conversation_id: UUID,
    message: Message,
    mode: str = "hybrid",
    provider: AnalysisProvider | None = None,
    observer: ProviderObserver | None = None,
) -> PromptAnalysis:
    if mode not in {"baseline", "ai", "hybrid"}:
        mode = "hybrid"
    result = analyze_message(db, project_id, conversation_id, message)
    result.analysis_version = "prompt-analyzer-v2" if mode != "baseline" else "prompt-analyzer-v1"
    result.analysis_mode = "baseline"
    result.ai_succeeded = False
    result.fallback_used = mode != "baseline"
    if mode != "baseline":
        injected = provider is not None
        active_provider = provider if provider is not None else OpenAICompatibleProvider()
        provider_name = safe_provider_label(active_provider.name)
        model_name = safe_provider_label(active_provider.model)
        result.ai_provider = provider_name
        result.ai_model = model_name
        if not injected and not all(
            (
                getattr(active_provider, "base_url", None),
                active_provider.model,
                getattr(active_provider, "api_key", None),
            )
        ):
            notify_observer(
                observer,
                ProviderCallObservation(
                    purpose="analysis",
                    provider=provider_name,
                    model=model_name,
                    request_hash=None,
                    started_at=None,
                    finished_at=None,
                    latency_ms=None,
                    request_outcome="not_attempted",
                    service_result="error" if mode == "ai" else "fallback",
                    fallback_reason="not_configured",
                ),
            )
            if mode == "ai":
                db.rollback()
                raise ProviderConfigurationError("OpenRouter configuration is incomplete")
        else:
            started_at = datetime.now(UTC)
            start = perf_counter()
            request_hash = sanitized_request_hash("analysis", model_name, message.content)
            try:
                ai_result = active_provider.analyze(message.content)
            except Exception as error:
                finished_at = datetime.now(UTC)
                handled = isinstance(error, (ProviderUnavailable, ProviderConfigurationError))
                notify_observer(
                    observer,
                    ProviderCallObservation(
                        purpose="analysis",
                        provider=provider_name,
                        model=model_name,
                        request_hash=request_hash,
                        started_at=started_at,
                        finished_at=finished_at,
                        latency_ms=round((perf_counter() - start) * 1000),
                        request_outcome="failed",
                        service_result="fallback" if handled and mode != "ai" else "error",
                        fallback_reason="provider_failed" if handled and mode != "ai" else None,
                        error_type=type(error).__name__,
                    ),
                )
                if not handled or mode == "ai":
                    if handled and mode == "ai":
                        db.rollback()
                    raise
            else:
                finished_at = datetime.now(UTC)
                try:
                    AnalysisReconciler().reconcile(result, ai_result)
                except Exception as error:
                    notify_observer(
                        observer,
                        ProviderCallObservation(
                            purpose="analysis",
                            provider=provider_name,
                            model=model_name,
                            request_hash=request_hash,
                            started_at=started_at,
                            finished_at=finished_at,
                            latency_ms=round((perf_counter() - start) * 1000),
                            request_outcome="succeeded",
                            service_result="error",
                            error_type=type(error).__name__,
                        ),
                    )
                    raise
                result.ai_succeeded = True
                result.fallback_used = False
                result.analysis_mode = "hybrid" if mode == "hybrid" else "ai"
                notify_observer(
                    observer,
                    ProviderCallObservation(
                        purpose="analysis",
                        provider=provider_name,
                        model=model_name,
                        request_hash=request_hash,
                        started_at=started_at,
                        finished_at=finished_at,
                        latency_ms=round((perf_counter() - start) * 1000),
                        request_outcome="succeeded",
                        service_result="ai",
                    ),
                )
    db.commit()
    db.refresh(result)
    return result
