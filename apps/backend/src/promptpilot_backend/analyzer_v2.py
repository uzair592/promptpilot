from uuid import UUID

from sqlalchemy.orm import Session

from .analyzer_service import analyze_message
from .llm_provider import OpenAICompatibleProvider, ProviderUnavailable
from .models import Message, PromptAnalysis


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
            provider.analyze(message.content)
            result.ai_succeeded = True
            result.fallback_used = False
            result.analysis_mode = "hybrid" if mode == "hybrid" else "ai"
        except ProviderUnavailable:
            pass
    db.commit()
    db.refresh(result)
    return result
