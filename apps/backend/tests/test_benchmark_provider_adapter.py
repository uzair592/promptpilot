"""Safety tests for provider adapter boundary."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from promptpilot_backend.benchmark_pricing import PricingModel, ProviderPricingSnapshot
from promptpilot_backend.benchmark_provider_adapter import (
    AdapterConfigurationError,
    LiveProviderAdapter,
    OfflineProviderAdapter,
    ProviderAdapterFactory,
    ProviderNotAvailableError,
)


def _snapshot(provider: str, model: str) -> ProviderPricingSnapshot:
    now = datetime.now(UTC)
    return ProviderPricingSnapshot(
        schema_version="v1",
        source_reference="https://pricing.example.org/frozen-snapshot",
        captured_at=now - timedelta(minutes=1),
        valid_until=now + timedelta(days=1),
        currency="USD",
        pricing_basis="all_in_token_rates",
        models=(
            PricingModel(
                provider=provider,
                model=model,
                input_cost_per_million_tokens=Decimal("1"),
                output_cost_per_million_tokens=Decimal("1"),
                maximum_context_tokens=1000,
            ),
        ),
    )


def test_offline_provider_adapter_is_offline():
    adapter = OfflineProviderAdapter("analysis", "offline-test", "model-test")
    assert adapter.is_offline is True
    assert adapter.provider_name == "offline-test"
    assert adapter.model_name == "model-test"


def test_offline_provider_adapter_generates_responses():
    adapter = OfflineProviderAdapter("analysis", "offline-test", "model-test")
    response = adapter.generate("test prompt")
    assert response["content"] is not None
    assert response["cost_estimate"] == 0.0
    assert response["currency"] == "USD"


def test_offline_provider_adapter_custom_responses():
    custom = {"generate:test prompt": "custom response"}
    adapter = OfflineProviderAdapter("analysis", "offline-test", "model-test", custom)
    response = adapter.generate("test prompt")
    assert response["content"] == "custom response"


def test_offline_provider_adapter_all_methods():
    adapter = OfflineProviderAdapter("analysis", "offline-test", "model-test")
    assert adapter.generate("test")["content"] is not None
    assert adapter.generate_question("test")["content"] is not None
    assert adapter.generate_prompt("test")["content"] is not None
    assert adapter.judge_response("task", "a", "b", {})["content"] is not None
    assert adapter.analyze("test")["content"] is not None


def test_live_provider_adapter_is_implemented():
    """LiveProviderAdapter is now implemented and wraps LLMProvider."""
    adapter = LiveProviderAdapter(
        llm_provider=SimpleNamespace(name="openrouter", model="gpt-4"),
        role="target_execution",
        provider_name="openrouter",
        model_name="gpt-4",
        pricing_snapshot=_snapshot("openrouter", "gpt-4"),
    )
    assert adapter.is_offline is False
    assert adapter.provider_name == "openrouter"
    assert adapter.model_name == "gpt-4"
    assert adapter.role == "target_execution"


def test_live_provider_adapter_rejects_provider_or_model_drift():
    with pytest.raises(AdapterConfigurationError, match="provider"):
        LiveProviderAdapter(
            llm_provider=SimpleNamespace(name="another-provider", model="gpt-4"),
            role="target_execution",
            provider_name="openrouter",
            model_name="gpt-4",
            pricing_snapshot=_snapshot("openrouter", "gpt-4"),
        )
    with pytest.raises(AdapterConfigurationError, match="model"):
        LiveProviderAdapter(
            llm_provider=SimpleNamespace(name="openrouter", model="another-model"),
            role="target_execution",
            provider_name="openrouter",
            model_name="gpt-4",
            pricing_snapshot=_snapshot("openrouter", "gpt-4"),
        )


def test_provider_adapter_factory_offline_mode():
    factory = ProviderAdapterFactory("offline_dry_run")
    adapter = factory.create_adapter("analysis", "offline-test", "model-test")
    assert isinstance(adapter, OfflineProviderAdapter)
    assert adapter.is_offline is True


def test_provider_adapter_factory_rejects_live_mode_without_pinned_pricing():
    with pytest.raises(AdapterConfigurationError, match="pinned pricing"):
        ProviderAdapterFactory("live")


def test_openai_compatible_provider_uses_runtime_credentials_without_network(
    monkeypatch,
) -> None:
    secret = "runtime-only-test-credential"
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "task_category": "general",
                                        "dimensions": {},
                                        "information_gaps": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def intercepted_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = request.data
        return Response()

    monkeypatch.setattr(
        "promptpilot_backend.llm_provider.get_settings",
        lambda: SimpleNamespace(
            llm_provider="openrouter",
            llm_base_url="https://provider.example",
            llm_model="runtime-model",
            llm_api_key=secret,
            llm_timeout=1,
        ),
    )
    monkeypatch.setattr("promptpilot_backend.llm_provider.urlopen", intercepted_urlopen)

    from promptpilot_backend.llm_provider import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider()
    result = provider.analyze("offline unit-test task")

    assert provider.name == "openrouter"
    assert provider.model == "runtime-model"
    assert result.task_category == "general"
    assert captured["authorization"] == f"Bearer {secret}"
    assert secret.encode() not in captured["body"]


def test_provider_adapter_factory_invalid_mode():
    with pytest.raises(ValueError):
        ProviderAdapterFactory("invalid_mode")


def test_provider_adapter_factory_creates_all_offline():
    factory = ProviderAdapterFactory("offline_dry_run")
    bindings = {
        "analysis": type("B", (), {"provider": "p1", "model": "m1"}),
        "prompt_generation": type("B", (), {"provider": "p2", "model": "m2"}),
    }
    adapters = factory.create_all_offline_adapters(bindings)
    assert "analysis" in adapters
    assert "prompt_generation" in adapters
    assert all(a.is_offline for a in adapters.values())


def test_provider_adapter_error_codes():
    with pytest.raises(ProviderNotAvailableError) as e:
        raise ProviderNotAvailableError("analysis")
    assert e.value.code == "provider_not_available"

    with pytest.raises(AdapterConfigurationError) as e:
        raise AdapterConfigurationError("bad config")
    assert e.value.code == "adapter_configuration_error"