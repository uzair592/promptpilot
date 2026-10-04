"""Safety tests for provider adapter boundary."""

from types import SimpleNamespace

import pytest

from promptpilot_backend.benchmark_provider_adapter import (
    AdapterConfigurationError,
    LiveProviderAdapter,
    OfflineProviderAdapter,
    ProviderAdapterFactory,
    ProviderNotAvailableError,
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
        )
    with pytest.raises(AdapterConfigurationError, match="model"):
        LiveProviderAdapter(
            llm_provider=SimpleNamespace(name="openrouter", model="another-model"),
            role="target_execution",
            provider_name="openrouter",
            model_name="gpt-4",
        )


def test_provider_adapter_factory_offline_mode():
    factory = ProviderAdapterFactory("offline_dry_run")
    adapter = factory.create_adapter("analysis", "offline-test", "model-test")
    assert isinstance(adapter, OfflineProviderAdapter)
    assert adapter.is_offline is True


def test_provider_adapter_factory_live_mode_creates_matching_live_adapter(monkeypatch):
    monkeypatch.setattr(
        "promptpilot_backend.llm_provider.OpenAICompatibleProvider",
        lambda: SimpleNamespace(name="openrouter", model="gpt-4"),
    )
    factory = ProviderAdapterFactory("live")
    adapter = factory.create_adapter("analysis", "openrouter", "gpt-4")
    # In live mode, factory creates a LiveProviderAdapter
    assert not adapter.is_offline
    assert adapter.provider_name == "openrouter"
    assert adapter.model_name == "gpt-4"


def test_provider_adapter_factory_rejects_frozen_model_mismatch(monkeypatch):
    monkeypatch.setattr(
        "promptpilot_backend.llm_provider.OpenAICompatibleProvider",
        lambda: SimpleNamespace(name="openrouter", model="gpt-4"),
    )
    factory = ProviderAdapterFactory("live")
    with pytest.raises(AdapterConfigurationError, match="frozen provider assignment"):
        factory.create_adapter("target_execution", "openrouter", "different-model")


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