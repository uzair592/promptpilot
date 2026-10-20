from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .llm_provider import OpenAICompatibleProvider
from .models import ProviderConnection
from .orchestration_service import decrypt_api_key, user_connection
from .provider_gateway import ProviderGateway


def chat_provider(
    db: Session, user_id: UUID, connection_id: UUID | None = None
) -> OpenAICompatibleProvider | ProviderGateway:
    connection = (
        user_connection(db, connection_id, user_id)
        if connection_id
        else db.scalar(
            select(ProviderConnection)
            .where(ProviderConnection.user_id == user_id, ProviderConnection.status == "active")
            .order_by(ProviderConnection.created_at.desc())
        )
    )
    if connection is not None:
        if connection.status != "active":
            raise HTTPException(
                status_code=409, detail="Test this connection in Models & API keys first"
            )
        return ProviderGateway(
            connection.provider,
            connection.default_model,
            decrypt_api_key(connection),
            connection.base_url,
        )
    settings = get_settings()
    if settings.llm_provider in {
        "gemini",
        "anthropic",
        "grok",
        "deepseek",
        "mistral",
        "groq",
        "openai",
        "openrouter",
    }:
        return ProviderGateway(settings.llm_provider, settings.llm_model, settings.llm_api_key)
    return OpenAICompatibleProvider()
