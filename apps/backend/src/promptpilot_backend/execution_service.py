import json
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .llm_provider import OpenAICompatibleProvider, ProviderUnavailable
from .models import Message, ModelRun, PromptVersion

STRATEGIES = {"baseline", "promptpilot"}


class LLMExecutionInput(BaseModel):
    optimized_prompt: str = Field(min_length=1, max_length=200000)
    prompt_version_id: UUID | None = None
    project_id: UUID
    conversation_id: UUID
    source_message_id: UUID
    provider: str | None = None
    model: str | None = None
    system_instruction: str | None = Field(default=None, max_length=10000)
    parameters: dict[str, float | int | str | bool] = {}
    execution_strategy: str

    def validate_strategy(self) -> None:
        if self.execution_strategy not in STRATEGIES:
            raise ValueError("Unsupported execution strategy")


class LLMExecutionResult(BaseModel):
    response_text: str = Field(min_length=1)
    provider: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int | float | str] = {}
    latency_ms: int | None = None
    execution_metadata: dict[str, Any] = {}


class ExecutionProvider(Protocol):
    name: str
    model: str

    def generate_response(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class LLMExecutionService:
    def __init__(self, provider: ExecutionProvider | None = None) -> None:
        self.provider = provider or OpenAICompatibleProvider()

    def execute(self, db: Session, prompt_version: PromptVersion | None, message: Message, system_instruction: str | None, parameters: dict[str, Any], strategy: str) -> tuple[ModelRun, LLMExecutionResult]:
        if strategy not in STRATEGIES:
            raise ValueError("Unsupported execution strategy")
        if strategy == "promptpilot" and prompt_version is None:
            raise ValueError("PromptPilot execution requires a prompt version")
        prompt = prompt_version.optimized_prompt if prompt_version else message.content
        started = time.perf_counter()
        provider_name = self.provider.name
        model_name = self.provider.model
        try:
            payload: dict[str, Any] = {"prompt": prompt, "system_instruction": system_instruction, "parameters": parameters}
            raw = self.provider.generate_response(payload)
            result = LLMExecutionResult.model_validate({**raw, "provider": raw.get("provider", provider_name), "model": raw.get("model", model_name), "latency_ms": int((time.perf_counter() - started) * 1000)})
            run = ModelRun(project_id=message.conversation.project_id, conversation_id=message.conversation_id, prompt_version_id=prompt_version.id if prompt_version else None, source_message_id=message.id, execution_strategy=strategy, optimized_prompt=prompt, response_text=result.response_text, provider=result.provider, model=result.model, status="succeeded", finish_reason=result.finish_reason, usage_json=json.dumps(result.usage), generation_parameters_json=json.dumps(parameters, sort_keys=True), latency_ms=result.latency_ms, created_at=datetime.now(UTC))
        except (ProviderUnavailable, ValueError) as error:
            run = ModelRun(project_id=message.conversation.project_id, conversation_id=message.conversation_id, prompt_version_id=prompt_version.id if prompt_version else None, source_message_id=message.id, execution_strategy=strategy, optimized_prompt=prompt, provider=provider_name, model=model_name, status="failed", generation_parameters_json=json.dumps(parameters, sort_keys=True), error_message=str(error)[:500], latency_ms=int((time.perf_counter() - started) * 1000), created_at=datetime.now(UTC))
            db.add(run)
            db.commit()
            db.refresh(run)
            raise
        db.add(run)
        db.commit()
        db.refresh(run)
        return run, result


def load_execution_targets(db: Session, conversation_id: UUID, prompt_version_id: UUID | None, message_id: UUID | None, strategy: str) -> tuple[PromptVersion | None, Message]:
    if strategy == "promptpilot":
        version = db.get(PromptVersion, prompt_version_id) if prompt_version_id else None
        if version is None or version.conversation_id != conversation_id:
            raise ValueError("Prompt version does not belong to this conversation")
        message = db.get(Message, version.source_message_id)
    else:
        message = db.get(Message, message_id) if message_id else None
        version = None
    if message is None or message.conversation_id != conversation_id or message.role != "user":
        raise ValueError("Source user message not found")
    return version, message
