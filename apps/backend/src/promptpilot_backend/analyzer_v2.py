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
    db: Session, project_id: UUID, conversation_id: UUID, message: Message, mode: str = "hybrid"
) -> PromptAnalysis:
    if mode not in {"baseline", "ai", "hybrid"}:
        mode = "hybrid"
    result = analyze_message(db, project_id, conversation_id, message)
    result.analysis_version = "prompt-analyzer-v2" if mode != "baseline" else "prompt-analyzer-v1"
    result.analysis_mode = "baseline"
    result.ai_succeeded = False
    result.fallback_used = mode != "baseline"
    if mode != "baseline":
        provider = OpenAICompatibleProvider()
        result.ai_provider = provider.name
        result.ai_model = provider.model or None
        try:
            ai_result = provider.analyze(message.content)
            AnalysisReconciler().reconcile(result, ai_result)
            result.ai_succeeded = True
            result.fallback_used = False
            result.analysis_mode = "hybrid" if mode == "hybrid" else "ai"
        except (ProviderUnavailable, ProviderConfigurationError):
            if mode == "ai":
                db.rollback()
                raise
    db.commit()
    db.refresh(result)
    return result
