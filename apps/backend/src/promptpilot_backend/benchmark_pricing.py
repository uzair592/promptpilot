"""Pinned, offline-loaded provider pricing used by guarded benchmark calls."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .production_benchmark_protocol import LiveStudyProtocol

Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Currency = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
NonBlank = Annotated[str, StringConstraints(strict=True, min_length=1)]


class PricingSnapshotError(ValueError):
    """A pricing snapshot is missing, invalid, stale, or mismatched."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PricingModel(BaseModel):
    """All-in published token prices and provider-enforced context limit."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: NonBlank
    model: NonBlank
    input_cost_per_million_tokens: Decimal = Field(ge=0, allow_inf_nan=False)
    output_cost_per_million_tokens: Decimal = Field(ge=0, allow_inf_nan=False)
    maximum_context_tokens: int = Field(gt=0, le=10_000_000)

    @model_validator(mode="after")
    def has_nonzero_pricing(self) -> PricingModel:
        if (
            self.input_cost_per_million_tokens == 0
            and self.output_cost_per_million_tokens == 0
        ):
            raise ValueError("Pricing must contain a nonzero published token rate")
        return self


class ProviderPricingSnapshot(BaseModel):
    """Immutable source facts pinned by the protocol's sha256 reference."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["v1"]
    source_reference: NonBlank
    captured_at: datetime
    valid_until: datetime
    currency: Currency
    pricing_basis: Literal["all_in_token_rates"]
    models: tuple[PricingModel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot(self) -> ProviderPricingSnapshot:
        parsed = urlparse(self.source_reference)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Pricing source must be a credential-free HTTPS reference")
        if self.captured_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("Pricing snapshot timestamps must include a timezone")
        if self.valid_until <= self.captured_at:
            raise ValueError("Pricing snapshot expiry must follow its capture time")
        identities = [(item.provider, item.model) for item in self.models]
        if len(identities) != len(set(identities)):
            raise ValueError("Pricing snapshot contains ambiguous provider/model entries")
        return self

    def assert_fresh(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise PricingSnapshotError(
                "pricing_validation_time_invalid", "Pricing validation time must be timezone-aware"
            )
        if self.captured_at > current or self.valid_until <= current:
            raise PricingSnapshotError(
                "pricing_snapshot_stale", "Pricing snapshot is not currently valid"
            )

    def model_pricing(self, provider: str, model: str) -> PricingModel:
        matches = tuple(
            item for item in self.models if (item.provider, item.model) == (provider, model)
        )
        if len(matches) != 1:
            raise PricingSnapshotError(
                "pricing_model_unsupported",
                "Pricing snapshot does not contain exactly one matching provider/model entry",
            )
        return matches[0]

    def estimate(self, provider: str, model: str) -> CostEstimate:
        self.assert_fresh()
        rates = self.model_pricing(provider, model)
        # The serving endpoint enforces the pinned context ceiling. Charging the
        # full ceiling at both input and output rates bounds every accepted call.
        amount = (
            Decimal(rates.maximum_context_tokens)
            * (
                rates.input_cost_per_million_tokens
                + rates.output_cost_per_million_tokens
            )
            / Decimal(1_000_000)
        )
        estimate = float(amount)
        if not math.isfinite(estimate) or estimate <= 0:
            raise PricingSnapshotError(
                "pricing_estimate_invalid", "Pricing snapshot produced no finite positive estimate"
            )
        return CostEstimate(amount=math.nextafter(estimate, math.inf), currency=self.currency)


class CostEstimate(BaseModel):
    """Positive, currency-bound cost upper bound for one provider call."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: Currency


def pricing_snapshot_reference(snapshot: ProviderPricingSnapshot) -> str:
    """Return the canonical content-addressed reference stored by the protocol."""

    content = json.dumps(
        snapshot.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def validate_pricing_snapshot(
    snapshot: ProviderPricingSnapshot,
    protocol: LiveStudyProtocol,
    *,
    now: datetime | None = None,
) -> None:
    """Bind fresh pricing for every frozen provider role to protocol budget."""

    budget = protocol.monetary_budget
    if budget is None:
        raise PricingSnapshotError(
            "monetary_budget_not_configured", "A monetary budget is required for live pricing"
        )
    snapshot.assert_fresh(now)
    if budget.pricing_snapshot_reference != pricing_snapshot_reference(snapshot):
        raise PricingSnapshotError(
            "pricing_snapshot_reference_mismatch",
            "Pricing snapshot content does not match the protocol's pinned reference",
        )
    if snapshot.currency != budget.currency:
        raise PricingSnapshotError(
            "pricing_currency_mismatch",
            "Pricing snapshot currency differs from the protocol monetary budget",
        )
    assignments = protocol.providers
    required = [
        assignments.analysis,
        assignments.question_generation,
        assignments.prompt_generation,
        assignments.baseline_target,
    ]
    if protocol.evaluation.requires_judge:
        if assignments.judge is None:
            raise PricingSnapshotError(
                "judge_assignment_missing", "The frozen evaluation plan requires a judge"
            )
        required.append(assignments.judge)
    for assignment in required:
        snapshot.model_pricing(assignment.provider, assignment.model)


def load_pricing_snapshot(
    path: str | Path,
    protocol: LiveStudyProtocol,
    *,
    now: datetime | None = None,
) -> ProviderPricingSnapshot:
    """Load a local pricing artifact without network access and bind it to protocol."""

    try:
        raw = Path(path).read_text(encoding="utf-8")
        json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"Invalid JSON numeric constant: {value}")
            ),
        )
        snapshot = ProviderPricingSnapshot.model_validate_json(raw, strict=True)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise PricingSnapshotError(
            "pricing_snapshot_invalid", "Pricing snapshot could not be loaded or validated"
        ) from error
    validate_pricing_snapshot(snapshot, protocol, now=now)
    return snapshot
