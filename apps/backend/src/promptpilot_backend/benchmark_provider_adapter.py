"""Provider adapter boundary separating offline and live provider implementations.

This module defines the interface that all provider adapters must implement,
and provides the offline fixture provider implementation. The live provider
adapter is a factory boundary that remains unimplemented in this milestone.

The adapter pattern ensures that the experiment engine never directly
constructs or calls a real provider. The live runner milestone will provide
the concrete live implementation behind an explicit launch gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

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


class ProviderAdapter(ABC):
    """Abstract base class for provider adapters.

    All provider adapters must implement this interface. The experiment
    engine only interacts with this interface, never with concrete
    implementations directly.
    """

    @property
    @abstractmethod
    def role(self) -> str:
        """The provider role this adapter serves."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The provider identifier (e.g., 'openrouter', 'anthropic')."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier (e.g., 'gpt-4', 'claude-3-opus')."""

    @property
    @abstractmethod
    def is_offline(self) -> bool:
        """Whether this adapter is an offline fixture (never makes network calls)."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Generate a response from the provider.

        Args:
            prompt: The prompt to send to the provider.
            parameters: Generation parameters (temperature, max_tokens, etc.).

        Returns:
            A standardized provider response.

        Raises:
            ProviderAdapterError: If the provider call fails.
        """

    @abstractmethod
    def generate_question(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Generate a clarification question from the provider."""

    @abstractmethod
    def generate_prompt(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Generate an optimized prompt from the provider."""

    @abstractmethod
    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any],
    ) -> ProviderResponse:
        """Judge two responses using the provider as LLM judge."""

    @abstractmethod
    def analyze(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Analyze the task using the provider."""

    def health_check(self) -> bool:
        """Check if the provider is available."""
        return True

    def estimate_cost(self, prompt: str, parameters: dict[str, Any] | None = None) -> float | None:
        """Estimate the cost of a call. Returns None if estimation is not supported."""
        return None


class OfflineProviderAdapter(ProviderAdapter):
    """Offline fixture provider adapter for testing and dry runs.

    This adapter never makes network calls. It returns deterministic
    responses based on the fixture data. Used for offline dry runs and tests.
    """

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

    def _make_response(self, content: str, base_key: str) -> ProviderResponse:
        self._call_count += 1
        return ProviderResponse(
            content=content,
            input_tokens=len(content) // 4,
            output_tokens=len(content) // 4,
            total_tokens=len(content) // 2,
            cost_estimate=0.0,
            currency="USD",
            response_metadata={"call_number": self._call_count},
        )

    def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        key = f"generate:{prompt[:50]}"
        prefix = f"[offline:{self._role}] generated response for: "
        content = self._responses.get(key, f"{prefix}{prompt[:50]}")
        return self._make_response(content, "generate")

    def generate_question(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        key = f"question:{prompt[:50]}"
        prefix = f"[offline:{self._role}] generated question for: "
        content = self._responses.get(key, f"{prefix}{prompt[:50]}")
        return self._make_response(content, "question")

    def generate_prompt(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        key = f"prompt:{prompt[:50]}"
        prefix = f"[offline:{self._role}] generated prompt for: "
        content = self._responses.get(key, f"{prefix}{prompt[:50]}")
        return self._make_response(content, "prompt")

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any],
    ) -> ProviderResponse:
        key = f"judge:{task[:50]}"
        content = self._responses.get(key, '{"winner": "A", "scores": {"a": 80, "b": 70}}')
        return self._make_response(content, "judge")

    def analyze(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        key = f"analyze:{prompt[:50]}"
        content = self._responses.get(key, f"[offline:analysis] analysis for: {prompt[:50]}")
        return self._make_response(content, "analyze")


class LiveProviderAdapter(ProviderAdapter):
    """Live provider adapter - NOT IMPLEMENTED IN THIS MILESTONE.

    This class exists as a factory boundary for the future live-runner
    milestone. It is intentionally not instantiable in this milestone.

    The live adapter will be implemented in the live-runner milestone
    behind an explicit launch gate. It will wrap a real provider client
    (e.g., OpenRouter, Anthropic, OpenAI) and implement the same interface.
    """

    def __init__(self, config: LiveProviderConfig) -> None:
        # This is deliberately not implemented in this milestone.
        # The live adapter will be implemented in the live-runner milestone.
        raise ProviderAdapterError(
            "live_adapter_not_implemented",
            "LiveProviderAdapter is not implemented in this milestone. "
            "Use OfflineProviderAdapter for offline dry runs.",
        )

    @property
    def role(self) -> str:
        raise NotImplementedError("Live adapter not implemented")

    @property
    def provider_name(self) -> str:
        raise NotImplementedError("Live adapter not implemented")

    @property
    def model_name(self) -> str:
        raise NotImplementedError("Live adapter not implemented")

    @property
    def is_offline(self) -> bool:
        return False

    def generate(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("Live adapter not implemented")

    def generate_question(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("Live adapter not implemented")

    def generate_prompt(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("Live adapter not implemented")

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any],
    ) -> ProviderResponse:
        raise NotImplementedError("Live adapter not implemented")

    def analyze(
        self,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError("Live adapter not implemented")


class ProviderAdapterFactory:
    """Factory for creating provider adapters.

    This factory enforces the execution mode boundary: offline mode
    can only create offline adapters, live mode requires explicit
    launch authorization and is not available in this milestone.
    """

    def __init__(self, execution_mode: Literal["offline_dry_run", "live"]) -> None:
        if execution_mode not in ("offline_dry_run", "live"):
            raise ValueError(f"Invalid execution mode: {execution_mode}")
        self._mode = execution_mode
        self._offline_adapters: dict[str, ProviderAdapter] = {}

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
    ) -> ProviderAdapter:
        """Create a provider adapter for the given role.

        In offline mode, only offline adapters are created.
        In live mode, live adapters would be created (not implemented).
        """
        if self._mode == "offline_dry_run":
            adapter = OfflineProviderAdapter(role, provider, model)
            key = f"{role}:{provider}:{model}"
            self._offline_adapters[key] = adapter
            return adapter

        if self._mode == "live":
            # Live mode requires explicit launch authorization
            # which is verified by the launch gate before factory creation
            raise NotImplementedError(
                "Live adapter creation requires launch authorization. "
                "Not implemented in this milestone."
            )

        raise ValueError(f"Unknown execution mode: {self._mode}")

    def get_offline_adapter(self, role: str, provider: str, model: str) -> ProviderAdapter | None:
        """Get an existing offline adapter."""
        key = f"{role}:{provider}:{model}"
        return self._offline_adapters.get(key)

    def create_all_offline_adapters(
        self,
        role_bindings: dict[str, Any],
    ) -> dict[str, ProviderAdapter]:
        """Create offline adapters for all roles in the binding."""
        adapters: dict[str, ProviderAdapter] = {}
        for role, binding in role_bindings.items():
            adapters[role] = OfflineProviderAdapter(
                role=role,
                provider_name=binding.provider,
                model_name=binding.model,
            )
        return adapters