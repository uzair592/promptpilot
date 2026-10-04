import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import production_shape_payload, protocol_payload
from pydantic import ValidationError

from promptpilot_backend.benchmark_pricing import (
    CostEstimate,
    PricingModel,
    PricingSnapshotError,
    ProviderPricingSnapshot,
    load_pricing_snapshot,
    pricing_snapshot_reference,
    validate_pricing_snapshot,
)
from promptpilot_backend.benchmark_provider_adapter import (
    AdapterConfigurationError,
    LiveProviderAdapter,
    ProviderAdapterFactory,
)
from promptpilot_backend.production_benchmark_protocol import LiveStudyProtocol


def _pricing_protocol_and_snapshot(
    payload: dict | None = None,
    *,
    currency: str = "USD",
) -> tuple[LiveStudyProtocol, ProviderPricingSnapshot]:
    protocol_data = payload or protocol_payload()
    protocol_data = {
        **protocol_data,
        "monetary_budget": {
            "currency": currency,
            "maximum_cost": 100.0,
            "pricing_snapshot_reference": "sha256:" + "0" * 64,
        },
    }
    unchecked = LiveStudyProtocol.model_validate(protocol_data)
    assignments = [
        unchecked.providers.analysis,
        unchecked.providers.question_generation,
        unchecked.providers.prompt_generation,
        unchecked.providers.baseline_target,
    ]
    if unchecked.providers.judge is not None:
        assignments.append(unchecked.providers.judge)
    unique = {(item.provider, item.model) for item in assignments}
    now = datetime.now(UTC)
    snapshot = ProviderPricingSnapshot(
        schema_version="v1",
        source_reference="https://pricing.example.org/frozen-snapshot",
        captured_at=now - timedelta(minutes=1),
        valid_until=now + timedelta(days=1),
        currency=currency,
        pricing_basis="all_in_token_rates",
        models=tuple(
            PricingModel(
                provider=provider,
                model=model,
                input_cost_per_million_tokens=Decimal("0.25"),
                output_cost_per_million_tokens=Decimal("0.75"),
                maximum_context_tokens=1_000_000,
            )
            for provider, model in sorted(unique)
        ),
    )
    protocol_data["monetary_budget"]["pricing_snapshot_reference"] = (
        pricing_snapshot_reference(snapshot)
    )
    return LiveStudyProtocol.model_validate(protocol_data), snapshot


def test_snapshot_estimate_is_positive_and_covers_full_context_window() -> None:
    protocol_data = protocol_payload()
    for role in (
        "analysis",
        "question_generation",
        "prompt_generation",
        "baseline_target",
        "promptpilot_target",
    ):
        protocol_data["providers"][role] = {
            "provider": "openrouter",
            "model": "one-runtime-model",
        }
    protocol, snapshot = _pricing_protocol_and_snapshot(protocol_data)
    validate_pricing_snapshot(snapshot, protocol)

    quote = snapshot.estimate(
        protocol.providers.analysis.provider,
        protocol.providers.analysis.model,
    )

    assert isinstance(quote, CostEstimate)
    assert quote.amount == pytest.approx(1.0)
    assert quote.currency == protocol.monetary_budget.currency


def test_offline_snapshot_loader_checks_content_address_and_schema(tmp_path) -> None:
    protocol, snapshot = _pricing_protocol_and_snapshot()
    path = tmp_path / "pricing-snapshot.json"
    path.write_text(
        json.dumps(snapshot.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )

    loaded = load_pricing_snapshot(path, protocol)

    assert pricing_snapshot_reference(loaded) == (
        protocol.monetary_budget.pricing_snapshot_reference
    )


def test_snapshot_covers_every_frozen_provider_role() -> None:
    protocol, snapshot = _pricing_protocol_and_snapshot(production_shape_payload())

    validate_pricing_snapshot(snapshot, protocol)
    assert protocol.evaluation.primary == "llm_judge"
    assert protocol.providers.judge is not None
    assert snapshot.model_pricing(
        protocol.providers.judge.provider, protocol.providers.judge.model
    )


def test_missing_budget_or_unmatched_pricing_fails_closed() -> None:
    protocol = LiveStudyProtocol.model_validate(protocol_payload())
    now = datetime.now(UTC)
    snapshot = ProviderPricingSnapshot(
        schema_version="v1",
        source_reference="https://pricing.example.org/frozen-snapshot",
        captured_at=now - timedelta(minutes=1),
        valid_until=now + timedelta(days=1),
        currency="USD",
        pricing_basis="all_in_token_rates",
        models=(
            PricingModel(
                provider="unsupported",
                model="unsupported",
                input_cost_per_million_tokens=Decimal("1"),
                output_cost_per_million_tokens=Decimal("1"),
                maximum_context_tokens=1000,
            ),
        ),
    )

    with pytest.raises(PricingSnapshotError) as missing_budget:
        validate_pricing_snapshot(snapshot, protocol)
    assert missing_budget.value.code == "monetary_budget_not_configured"
    with pytest.raises(PricingSnapshotError) as unsupported:
        snapshot.model_pricing("openai-compatible", "not-priced")
    assert unsupported.value.code == "pricing_model_unsupported"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), float("-inf")])
def test_invalid_pricing_rates_are_rejected(value: float) -> None:
    with pytest.raises((ValidationError, ValueError)):
        PricingModel(
            provider="p",
            model="m",
            input_cost_per_million_tokens=value,
            output_cost_per_million_tokens=Decimal("1"),
            maximum_context_tokens=1000,
        )


def test_zero_pricing_and_ambiguous_models_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PricingModel(
            provider="p",
            model="m",
            input_cost_per_million_tokens=Decimal("0"),
            output_cost_per_million_tokens=Decimal("0"),
            maximum_context_tokens=1000,
        )
    entry = PricingModel(
        provider="p",
        model="m",
        input_cost_per_million_tokens=Decimal("1"),
        output_cost_per_million_tokens=Decimal("1"),
        maximum_context_tokens=1000,
    )
    with pytest.raises(ValidationError):
        ProviderPricingSnapshot(
            schema_version="v1",
            source_reference="https://pricing.example.org/frozen-snapshot",
            captured_at=datetime.now(UTC) - timedelta(minutes=1),
            valid_until=datetime.now(UTC) + timedelta(days=1),
            currency="USD",
            pricing_basis="all_in_token_rates",
            models=(entry, entry),
        )


def test_stale_snapshot_currency_and_protocol_reference_are_rejected() -> None:
    protocol, snapshot = _pricing_protocol_and_snapshot()
    with pytest.raises(PricingSnapshotError) as stale:
        validate_pricing_snapshot(
            snapshot,
            protocol,
            now=datetime.now(UTC) + timedelta(days=2),
        )
    assert stale.value.code == "pricing_snapshot_stale"

    protocol_data = protocol.model_dump(mode="json")
    protocol_data["monetary_budget"]["currency"] = "EUR"
    euro_protocol = LiveStudyProtocol.model_validate(protocol_data)
    with pytest.raises(PricingSnapshotError) as currency:
        validate_pricing_snapshot(snapshot, euro_protocol)
    assert currency.value.code == "pricing_currency_mismatch"

    protocol_data["monetary_budget"]["currency"] = "USD"
    protocol_data["monetary_budget"]["pricing_snapshot_reference"] = "https://changing/prices"
    unpinned_protocol = LiveStudyProtocol.model_validate(protocol_data)
    with pytest.raises(PricingSnapshotError) as reference:
        validate_pricing_snapshot(snapshot, unpinned_protocol)
    assert reference.value.code == "pricing_snapshot_reference_mismatch"


def test_live_adapter_uses_snapshot_estimate_and_runtime_identity() -> None:
    protocol, snapshot = _pricing_protocol_and_snapshot()
    assignment = protocol.providers.analysis
    adapter = LiveProviderAdapter(
        llm_provider=type(
            "Provider",
            (),
            {"name": assignment.provider, "model": assignment.model},
        )(),
        role="analysis",
        provider_name=assignment.provider,
        model_name=assignment.model,
        pricing_snapshot=snapshot,
    )

    estimate = adapter.estimate_cost({"prompt": "payload"})
    assert estimate.currency == "USD"
    assert estimate.amount >= 1.0


def test_live_factory_requires_protocol_snapshot_and_role_match(monkeypatch) -> None:
    with pytest.raises(AdapterConfigurationError):
        ProviderAdapterFactory("live")

    protocol_data = protocol_payload()
    for role in (
        "analysis",
        "question_generation",
        "prompt_generation",
        "baseline_target",
        "promptpilot_target",
    ):
        protocol_data["providers"][role] = {
            "provider": "openrouter",
            "model": "one-runtime-model",
        }
    protocol, snapshot = _pricing_protocol_and_snapshot(protocol_data)
    assignment = protocol.providers.analysis
    monkeypatch.setattr(
        "promptpilot_backend.llm_provider.OpenAICompatibleProvider",
        lambda: SimpleNamespace(name=assignment.provider, model=assignment.model),
    )
    monkeypatch.setattr(
        "promptpilot_backend.benchmark_provider_adapter.get_settings",
        lambda: SimpleNamespace(
            llm_provider=assignment.provider,
            llm_model=assignment.model,
            llm_api_key="runtime-only-test-key",
            llm_base_url="https://provider.example/v1",
            llm_timeout=30.0,
        ),
    )
    factory = ProviderAdapterFactory(
        "live",
        protocol=protocol,
        pricing_snapshot=snapshot,
    )
    adapter = factory.create_adapter(
        "analysis", assignment.provider, assignment.model
    )
    assert adapter.is_offline is False
    assert adapter.estimate_cost({"prompt": "offline test"}).amount >= 1.0

    altered_data = protocol.model_dump(mode="json")
    altered_data["monetary_budget"]["maximum_cost"] = 101.0
    altered_protocol = LiveStudyProtocol.model_validate(altered_data)
    with pytest.raises(AdapterConfigurationError, match="runner's frozen protocol"):
        factory.assert_protocol(altered_protocol)

    wrong_role = "unassigned-role"
    with pytest.raises(AdapterConfigurationError, match="frozen role assignment"):
        factory.create_adapter(wrong_role, assignment.provider, assignment.model)
