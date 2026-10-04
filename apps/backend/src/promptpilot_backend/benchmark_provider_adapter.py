"""Provider adapter boundary separating offline and live provider implementations.

This module defines the interface that all provider adapters must implement,
and provides both offline fixture and live provider implementations. The live
provider adapter wraps the existing LLMProvider abstraction (OpenAICompatibleProvider).

The adapter pattern ensures that the experiment engine never directly
constructs or calls a real provider without going through the adapter layer.
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# Provider role types are defined in benchmark_call_ledger

# Provider role types are defined in benchmark_call_ledger
ProviderRoleLiteral = Literal[
    "analysis", "question_generation", "prompt_generation", "target_execution", "judge"
]

TargetConditionLiteral = Literal["baseline", "promptpilot"]


class ProviderAdapterError(ValueError):
    """Base exception for provider adapter errors."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProviderNotAvailableError(ProviderAdapterError):
    """Raised when a provider is not available for the requested role."""

    def __init__(self, role: str) -> None:
        super().__init__(
            "provider_not_available",
            f"No provider available for role: {role}",
        )


class AdapterConfigurationError(ProviderAdapterError):
    """Raised when adapter configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__("adapter_configuration_error", message)


class ProviderResponse(BaseModel):
    """Standardized provider response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_estimate: float | None = None
    currency: str | None = None
    response_metadata: dict[str, Any] = {}


class ProviderRequest(BaseModel):
    """Standardized provider request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    prompt: str
    parameters: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class LiveProviderConfig(BaseModel):
    """Configuration for a live provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    api_key: str
    base_url: str | None = None
    timeout: float = 60.0
    max_retries: int = 0
    extra_headers: dict[str, str] = {}
    extra_body: dict[str, Any] = {}


class OfflineProviderAdapter:
    """Offline fixture provider adapter for testing and dry runs.

    This adapter never makes network calls. It returns deterministic
    responses based on the fixture data. Used for offline dry runs and tests.
    """

    offline_fixture = True

    def __init__(
        self,
        role: str,
        provider_name: str,
        model_name: str,
        responses: dict[str, str] | None = None,
    ) -> None:
        self._role = role
        self._provider_name = provider_name
        self._model_name = model_name
        self._responses = responses or {}
        self._call_count = 0

    @property
    def role(self) -> str:
        return self._role

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_offline(self) -> bool:
        return True

    def _make_response(self, content: str, base_key: str) -> dict[str, Any]:
        self._call_count += 1
        return {
            "content": content,
            "input_tokens": len(content) // 4,
            "output_tokens": len(content) // 4,
            "total_tokens": len(content) // 2,
            "cost_estimate": 0.0,
            "currency": "USD",
            "response_metadata": {"call_number": self._call_count},
        }

    def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = f"generate:{prompt[:50]}"
        prefix = f"[offline:{self._role}] generated response for: "
        content = self._responses.get(key, f"{prefix}{prompt[:50]}")
        return self._make_response(content, "generate")

    def _structured(self, model_payload: dict[str, Any]) -> dict[str, Any]:
        """Return a provider-shaped response whose content is valid JSON.

        The guarded runner parses the ``content`` field into the structured
        output model for each role, so every offline adapter response must
        carry a serialisable payload rather than free text.
        """

        return self._make_response(json.dumps(model_payload, sort_keys=True), "structured")

    def generate_question(
        self,
        prompt: dict[str, Any] | str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = prompt if isinstance(prompt, dict) else {}
        gap_id = str(payload.get("gap_id", "") or "")
        gap_target = str(payload.get("gap_target", "") or "")
        question_text = (
            gap_target
            if 3 <= len(gap_target) <= 500
            else "Offline clarification question"
        )
        try:
            priority = int(payload.get("priority", 1) or 1)
        except (TypeError, ValueError):
            priority = 1
        return self._structured(
            {
                "question_text": question_text,
                "question_type": "free_text",
                "related_gap": gap_id,
                "priority": max(0, priority),
                "rationale": "Offline fixture question derived from the information gap.",
            }
        )

    def generate_prompt(
        self,
        prompt: dict[str, Any] | str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._structured(
            {
                "optimized_prompt": "Offline optimized prompt using the supplied context.",
                "task_summary": "Offline task summary",
                "assumptions": [],
                "incorporated_context": [],
                "incorporated_requirements": [],
                "output_format": "text",
                "quality_notes": [],
                "warnings": ["Offline fixture: no real provider was contacted."],
                "generation_metadata": {"offline": True},
            }
        )

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        score = {
            "relevance": 75,
            "completeness": 75,
            "instruction_following": 75,
            "contextual_grounding": 75,
            "clarity": 75,
            "explanations": {},
            "evidence": {},
        }
        return self._structured({"response_a": score, "response_b": score})

    def analyze(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = prompt if isinstance(prompt, str) else ""
        try:
            from .analyzer_service import classify_task

            category = classify_task(text)
        except Exception:
            category = "general"
        return self._structured(
            {
                "task_category": category,
                "dimensions": {},
                "information_gaps": [],
            }
        )

    def estimate_cost(self, request_payload: Any) -> float:
        return 0.0


class LiveProviderAdapter:
    """Live provider adapter that wraps the repository's LLMProvider.

    This adapter wraps the existing LLMProvider abstraction (OpenAICompatibleProvider)
    and translates between the provider adapter interface and the LLMProvider interface.
    """

    def __init__(
        self,
        llm_provider: Any,
        role: str,
        provider_name: str,
        model_name: str,
    ) -> None:
        if getattr(llm_provider, "name", None) != provider_name:
            raise AdapterConfigurationError(
                "Configured provider differs from the live provider implementation"
            )
        if getattr(llm_provider, "model", None) != model_name:
            raise AdapterConfigurationError(
                "Configured model differs from the live provider implementation"
            )
        self._llm_provider = llm_provider
        self._role = role
        self._provider_name = provider_name
        self._model_name = model_name

    @property
    def role(self) -> str:
        return self._role

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_offline(self) -> bool:
        return False

    def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a response from the target model."""
        payload = {
            "prompt": prompt,
            "parameters": parameters or {},
        }
        result = self._llm_provider.generate_response(payload)
        return {
            "content": result.get("response_text", ""),
            "input_tokens": result.get("usage", {}).get("prompt_tokens"),
            "output_tokens": result.get("usage", {}).get("completion_tokens"),
            "total_tokens": result.get("usage", {}).get("total_tokens"),
            "cost_estimate": None,
            "currency": "USD",
            "response_metadata": {"finish_reason": result.get("finish_reason")},
        }

    def generate_question(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a clarification question."""
        result = self._llm_provider.generate_question(
            {"task": prompt, "parameters": parameters or {}}
        )
        if hasattr(result, "model_dump"):
            content = result.model_dump_json()
        else:
            content = str(result)
        return {
            "content": content,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_estimate": None,
            "currency": "USD",
            "response_metadata": {},
        }

    def generate_prompt(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate an optimized prompt."""
        result = self._llm_provider.generate_prompt(
            {"task": prompt, "parameters": parameters or {}}
        )
        if hasattr(result, "model_dump"):
            content = result.model_dump_json()
        else:
            content = str(result)
        return {
            "content": content,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_estimate": None,
            "currency": "USD",
            "response_metadata": {},
        }

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Judge two responses using the provider as LLM judge."""
        result = self._llm_provider.judge_response(task, response_a, response_b, evidence)
        if hasattr(result, "model_dump"):
            content = result.model_dump_json()
        else:
            content = str(result)
        return {
            "content": content,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_estimate": None,
            "currency": "USD",
            "response_metadata": {},
        }

    def analyze(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Analyze the task using the provider."""
        result = self._llm_provider.analyze(prompt)
        if hasattr(result, "model_dump"):
            content = result.model_dump_json()
        else:
            content = str(result)
        return {
            "content": content,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_estimate": None,
            "currency": "USD",
            "response_metadata": {},
        }

    def health_check(self) -> bool:
        return True

    def estimate_cost(self, request_payload: Any) -> float | None:
        estimator = getattr(self._llm_provider, "estimate_cost", None)
        if not callable(estimator):
            return None
        estimate = estimator(request_payload)
        if estimate is None:
            return None
        if (
            isinstance(estimate, bool)
            or not isinstance(estimate, (int, float))
            or not math.isfinite(estimate)
            or estimate < 0
        ):
            raise AdapterConfigurationError(
                "Live provider returned an invalid pre-call cost estimate"
            )
        return float(estimate)


class ProviderAdapterFactory:
    """Factory for creating provider adapters.

    This factory enforces the execution mode boundary: offline mode
    can only create offline adapters, live mode requires explicit
    launch authorization and creates live adapters.
    """

    def __init__(self, execution_mode: Literal["offline_dry_run", "live"]) -> None:
        if execution_mode not in ("offline_dry_run", "live"):
            raise ValueError(f"Invalid execution mode: {execution_mode}")
        self._mode = execution_mode
        self._offline_adapters: dict[str, Any] = {}

    @property
    def mode(self) -> str:
        return self._mode

    def create_adapter(
        self,
        role: str,
        provider: str,
        model: str,
        *,
        responses: dict[str, str] | None = None,
        config: Any | None = None,
    ) -> Any:
        """Create a provider adapter for the given role.

        In offline mode, only offline adapters are created.
        In live mode, live adapters are created using the real LLMProvider.
        """
        if self._mode == "offline_dry_run":
            adapter = OfflineProviderAdapter(role, provider, model)
            key = f"{role}:{provider}:{model}"
            self._offline_adapters[key] = adapter
            return adapter

        if self._mode == "live":
            # Live mode requires explicit launch authorization
            # which is verified by the launch gate before factory creation
            from .llm_provider import OpenAICompatibleProvider

            llm_provider = OpenAICompatibleProvider()
            if llm_provider.name != provider or llm_provider.model != model:
                raise AdapterConfigurationError(
                    "Live provider settings do not match the frozen provider assignment"
                )
            return LiveProviderAdapter(
                llm_provider=llm_provider,
                role=provider,
                provider_name=provider,
                model_name=model,
            )

        raise ValueError(f"Unknown execution mode: {self._mode}")

    def get_offline_adapter(self, role: str, provider: str, model: str) -> Any | None:
        """Get an existing offline adapter."""
        key = f"{role}:{provider}:{model}"
        return self._offline_adapters.get(key)

    def create_all_offline_adapters(
        self,
        role_bindings: dict[str, Any],
    ) -> dict[str, Any]:
        """Create offline adapters for all roles in the binding."""
        adapters: dict[str, Any] = {}
        for role, binding in role_bindings.items():
            adapters[role] = OfflineProviderAdapter(
                role=role,
                provider_name=binding.provider,
                model_name=binding.model,
            )
        return adapters


# Keep the old abstract base class for type checking compatibility
class ProviderAdapter:
    """Abstract base class for provider adapters (kept for type compatibility)."""

    @property
    def role(self) -> str:
        raise NotImplementedError

    @property
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def is_offline(self) -> bool:
        raise NotImplementedError

    def generate(self, prompt: str, parameters: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    def generate_question(self, prompt: str, parameters: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    def generate_prompt(self, prompt: str, parameters: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any],
    ) -> Any:
        raise NotImplementedError

    def analyze(self, prompt: str, parameters: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError