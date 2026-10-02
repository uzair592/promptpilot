"""Typed, offline-only admission for a future live production benchmark.

This module validates declarations and frozen files. It never constructs a provider,
makes a network request, or authorizes execution of a live study.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .benchmark import BenchmarkDataset, dataset_sha256, load_dataset
from .benchmark_fixtures import (
    FixtureManifest,
    admit_live_manifest,
    manifest_sha256,
    validate_manifest,
)

Sha256 = str
EvaluationMethod = Literal["heuristic", "llm_judge"]
ProviderRole = Literal[
    "analysis", "question_generation", "prompt_generation", "target_execution", "judge"
]

_PLACEHOLDER = re.compile(r"(?i)(?:^|[^a-z0-9])(?:tbd|unknown|later)(?:$|[^a-z0-9])")
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:authorization\s*:|bearer\s+[a-z0-9._~+/=-]+|"
    r"(?:api[_ -]?key|access[_ -]?token|password|cookie)\s*[:=]|sk-[a-z0-9_-]{8,})"
)
_CREDENTIAL_KEYS = {
    "apikey",
    "authorization",
    "authorizationheader",
    "cookie",
    "password",
    "secret",
    "token",
    "accesstoken",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "refreshtoken",
    "sessioncookie",
}


def _key_is_credential_like(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    return normalized in _CREDENTIAL_KEYS or any(
        normalized.endswith(marker)
        for marker in {
            "apikey",
            "authorizationheader",
            "accesstoken",
            "authtoken",
            "bearertoken",
            "clientsecret",
            "refreshtoken",
            "sessioncookie",
        }
    )


def _walk_declaration(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _key_is_credential_like(str(key)):
                raise ValueError("Credential-like fields are forbidden in protocol data")
            _walk_declaration(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _walk_declaration(item)
    elif isinstance(value, str):
        if _PLACEHOLDER.search(value):
            raise ValueError("Unresolved placeholder values are forbidden in protocol data")
        if _CREDENTIAL_VALUE.search(value):
            raise ValueError("Credential-like values are forbidden in protocol data")


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class ProviderAssignment(StrictModel):
    provider: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=240)


class TargetGenerationParameters(StrictModel):
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1)
    top_p: float = Field(gt=0, le=1)
    seed: int | None
    stop: tuple[str, ...]
    presence_penalty: float = Field(ge=-2, le=2)
    frequency_penalty: float = Field(ge=-2, le=2)


class ProviderAssignments(StrictModel):
    analysis: ProviderAssignment
    question_generation: ProviderAssignment
    prompt_generation: ProviderAssignment
    baseline_target: ProviderAssignment
    promptpilot_target: ProviderAssignment
    judge: ProviderAssignment | None


class ComparisonPolicy(StrictModel):
    baseline_input: Literal["exact_original_task"]
    execution_order: Literal["alternating_paired"]
    unit_isolation: Literal["task_repetition"]
    incomplete_pair_evaluation: Literal["prohibited"]
    unmatched_gap: Literal["stop", "skip_and_exclude"]
    fallback_admission: Literal["reject", "admit_separate_stratum"]


class AnalysisStratum(StrictModel):
    name: Literal["strict_ai_backed", "hybrid_product_behavior"]
    fallback_containing_runs_admissible: bool


class EvaluationPlan(StrictModel):
    primary: EvaluationMethod
    secondary: EvaluationMethod | None

    @model_validator(mode="after")
    def distinct_methods(self) -> EvaluationPlan:
        if self.secondary == self.primary:
            raise ValueError("Secondary evaluation method must differ from primary")
        return self

    @property
    def requires_judge(self) -> bool:
        return self.primary == "llm_judge" or self.secondary == "llm_judge"


class RoleCallBudget(StrictModel):
    analysis: int = Field(ge=0)
    question_generation: int = Field(ge=0)
    prompt_generation: int = Field(ge=0)
    target_execution: int = Field(ge=0)
    judge: int = Field(ge=0)


class ProviderCallBudgets(StrictModel):
    by_role: RoleCallBudget
    total: int = Field(ge=0)


class MonetaryBudget(StrictModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    maximum_cost: float = Field(ge=0)
    pricing_snapshot_reference: str = Field(min_length=1)


class StopRules(StrictModel):
    stop_on_budget_exhaustion: Literal[True]
    stop_on_manifest_change: Literal[True]
    stop_on_incomplete_treatment_preparation: Literal[True]
    stop_on_target_failure: Literal[True]
    stop_on_judge_failure: Literal[True]
    maximum_consecutive_provider_failures: int = Field(ge=1)


class FixtureReviewAttestation(StrictModel):
    attestation_version: Literal["v1"]
    fixture_id: str = Field(min_length=1)
    manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    provenance_consent_evidence_reference: str = Field(min_length=1)
    test_only: bool

    @model_validator(mode="after")
    def timezone_required(self) -> FixtureReviewAttestation:
        _aware(self.reviewed_at, "Attestation reviewed_at")
        return self


class SelectedFixture(StrictModel):
    fixture_id: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    attestation: FixtureReviewAttestation

    @model_validator(mode="after")
    def bind_attestation(self) -> SelectedFixture:
        path = Path(self.manifest_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Manifest paths must be protocol-relative and cannot escape")
        if (
            self.attestation.fixture_id != self.fixture_id
            or self.attestation.manifest_sha256 != self.manifest_sha256
        ):
            raise ValueError("Fixture attestation does not match its fixture ID and manifest hash")
        return self


class ProtocolReview(StrictModel):
    status: Literal["draft", "pending", "locked"]
    reviewer_id: str | None
    locked_at: datetime | None

    @model_validator(mode="after")
    def validate_lock(self) -> ProtocolReview:
        if self.status == "locked":
            if not self.reviewer_id or self.locked_at is None:
                raise ValueError("Locked protocol review requires reviewer_id and locked_at")
            _aware(self.locked_at, "Protocol locked_at")
        elif self.reviewer_id is not None or self.locked_at is not None:
            raise ValueError("Protocol reviewer_id and locked_at are only valid when locked")
        return self


class LiveStudyProtocol(StrictModel):
    schema_version: Literal["v1"]
    protocol_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    study_title: str = Field(min_length=1, max_length=300)
    study_version: str = Field(min_length=1, max_length=80)
    dataset_name: str = Field(min_length=1)
    dataset_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    selected_fixtures: tuple[SelectedFixture, ...] = Field(min_length=1)
    repetitions: int = Field(ge=1)
    question_cap: int = Field(ge=0, le=50)
    comparison_policy: ComparisonPolicy
    analysis_stratum: AnalysisStratum
    generation_mode: Literal["structured", "minimal", "detailed"]
    evaluation: EvaluationPlan
    baseline_target_parameters: TargetGenerationParameters
    promptpilot_target_parameters: TargetGenerationParameters
    providers: ProviderAssignments
    call_budgets: ProviderCallBudgets
    monetary_budget: MonetaryBudget | None
    stop_rules: StopRules
    review: ProtocolReview

    @model_validator(mode="before")
    @classmethod
    def reject_unsafe_declarations(cls, value: Any) -> Any:
        _walk_declaration(value)
        return value

    @model_validator(mode="after")
    def research_invariants(self) -> LiveStudyProtocol:
        fixture_ids = [item.fixture_id for item in self.selected_fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("Selected fixture IDs must be unique")
        if self.providers.baseline_target != self.providers.promptpilot_target:
            raise ValueError("Baseline and PromptPilot target provider/model must match")
        if self.baseline_target_parameters != self.promptpilot_target_parameters:
            raise ValueError("Baseline and PromptPilot target parameters must match")
        if self.evaluation.requires_judge and self.providers.judge is None:
            raise ValueError("LLM-judge evaluation requires a judge provider/model assignment")
        if not self.evaluation.requires_judge and self.providers.judge is not None:
            raise ValueError("Heuristic-only evaluation must not assign a judge")
        fallback_allowed = self.comparison_policy.fallback_admission == "admit_separate_stratum"
        if self.analysis_stratum.fallback_containing_runs_admissible != fallback_allowed:
            raise ValueError("Analysis stratum and fallback admission policy disagree")
        if fallback_allowed and self.analysis_stratum.name != "hybrid_product_behavior":
            raise ValueError("Fallback-containing runs require the hybrid product stratum")
        if not fallback_allowed and self.analysis_stratum.name != "strict_ai_backed":
            raise ValueError("Rejected fallbacks require the strict AI-backed stratum")
        return self


class CallCeiling(StrictModel):
    fixture_count: int
    unit_count: int
    by_role: RoleCallBudget
    total: int


class AdmissionBlocker(StrictModel):
    code: str
    message: str
    fixture_id: str | None = None
    field: str | None = None


class HumanApprovalBoundary(StrictModel):
    externally_verified: Literal[False] = False
    statement: str


class AdmissionReport(StrictModel):
    schema_version: Literal["v1"] = "v1"
    protocol_id: str | None
    technical_ready: bool
    ready: bool
    protocol_sha256: str | None
    dataset_sha256: str | None
    admitted_fixture_ids: tuple[str, ...]
    call_ceiling: CallCeiling | None
    blockers: tuple[AdmissionBlocker, ...]
    human_approval: HumanApprovalBoundary
    authorization_statement: str


def protocol_sha256(protocol: LiveStudyProtocol) -> str:
    checked = LiveStudyProtocol.model_validate(protocol.model_dump(mode="json"))
    canonical = json.dumps(
        checked.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def calculate_call_ceiling(protocol: LiveStudyProtocol) -> CallCeiling:
    """Calculate the conservative ceiling for all proposed fixture/repetition units."""

    checked = LiveStudyProtocol.model_validate(protocol.model_dump(mode="json"))
    fixture_count = len(checked.selected_fixtures)
    units = fixture_count * checked.repetitions
    roles = RoleCallBudget(
        analysis=units,
        question_generation=units * checked.question_cap,
        prompt_generation=units,
        target_execution=units * 2,
        judge=units if checked.evaluation.requires_judge else 0,
    )
    return CallCeiling(
        fixture_count=fixture_count,
        unit_count=units,
        by_role=roles,
        total=sum(roles.model_dump().values()),
    )


def _safe_manifest_path(protocol_path: Path, selection: SelectedFixture) -> Path:
    base = protocol_path.resolve().parent
    resolved = (base / selection.manifest_path).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("Manifest path escapes the protocol directory")
    return resolved


def _load_manifest(path: Path) -> FixtureManifest:
    with path.open(encoding="utf-8") as handle:
        return FixtureManifest.model_validate(json.load(handle))


def _budget_blockers(protocol: LiveStudyProtocol, ceiling: CallCeiling) -> list[AdmissionBlocker]:
    blockers: list[AdmissionBlocker] = []
    required = ceiling.by_role.model_dump()
    declared = protocol.call_budgets.by_role.model_dump()
    for role, required_calls in required.items():
        if declared[role] < required_calls:
            blockers.append(
                AdmissionBlocker(
                    code="insufficient_role_budget",
                    field=f"call_budgets.by_role.{role}",
                    message=f"{role} budget is below the calculated ceiling of {required_calls}",
                )
            )
    if protocol.call_budgets.total < ceiling.total:
        blockers.append(
            AdmissionBlocker(
                code="insufficient_total_budget",
                field="call_budgets.total",
                message=f"Total call budget is below the calculated ceiling of {ceiling.total}",
            )
        )
    return blockers


def admit_protocol(
    protocol: LiveStudyProtocol, dataset: BenchmarkDataset, protocol_path: str | Path
) -> AdmissionReport:
    """Validate technical readiness without verifying human claims or running providers."""

    checked = LiveStudyProtocol.model_validate(protocol.model_dump(mode="json"))
    dataset_checked = BenchmarkDataset.model_validate(dataset.model_dump(mode="json"))
    path = Path(protocol_path)
    blockers: list[AdmissionBlocker] = []
    admitted: list[str] = []
    actual_dataset_hash = dataset_sha256(dataset_checked)
    if (
        checked.dataset_name != dataset_checked.name
        or checked.dataset_sha256 != actual_dataset_hash
    ):
        blockers.append(
            AdmissionBlocker(
                code="dataset_identity_mismatch",
                field="dataset_sha256",
                message="Protocol dataset name or canonical hash differs from the supplied dataset",
            )
        )
    if checked.review.status != "locked":
        blockers.append(
            AdmissionBlocker(
                code="protocol_not_locked",
                field="review.status",
                message="Protocol review status must be locked for technical admission",
            )
        )

    for selection in checked.selected_fixtures:
        try:
            manifest_path = _safe_manifest_path(path, selection)
            manifest = _load_manifest(manifest_path)
            dataset_bound = validate_manifest(manifest, dataset_checked, manifest_path)
        except (OSError, ValueError, ValidationError):
            blockers.append(
                AdmissionBlocker(
                    code="fixture_validation_failed",
                    fixture_id=selection.fixture_id,
                    message=(
                        "Fixture declaration, dataset binding, or frozen document "
                        "verification failed"
                    ),
                )
            )
            continue
        actual_manifest_hash = manifest_sha256(dataset_bound)
        if selection.fixture_id != dataset_bound.fixture_id:
            blockers.append(
                AdmissionBlocker(
                    code="fixture_id_mismatch",
                    fixture_id=selection.fixture_id,
                    message="Selected fixture ID differs from the referenced manifest",
                )
            )
            continue
        if selection.manifest_sha256 != actual_manifest_hash:
            blockers.append(
                AdmissionBlocker(
                    code="manifest_hash_mismatch",
                    fixture_id=selection.fixture_id,
                    message="Selected canonical manifest hash differs from the referenced manifest",
                )
            )
            continue
        try:
            live_manifest = admit_live_manifest(dataset_bound, dataset_checked, manifest_path)
        except (ValueError, ValidationError):
            blockers.append(
                AdmissionBlocker(
                    code="fixture_not_live_eligible",
                    fixture_id=selection.fixture_id,
                    message=(
                        "Fixture is synthetic, pending, changed, stale, or not "
                        "schema-approved for live use"
                    ),
                )
            )
            continue
        attestation = selection.attestation
        if attestation.test_only:
            blockers.append(
                AdmissionBlocker(
                    code="test_only_attestation",
                    fixture_id=selection.fixture_id,
                    message="Test-only attestations cannot support live technical admission",
                )
            )
            continue
        if (
            live_manifest.review.reviewer_id != attestation.reviewer_id
            or live_manifest.review.reviewed_at != attestation.reviewed_at
        ):
            blockers.append(
                AdmissionBlocker(
                    code="attestation_review_mismatch",
                    fixture_id=selection.fixture_id,
                    message=(
                        "Attestation reviewer or timestamp differs from the manifest review claim"
                    ),
                )
            )
            continue
        admitted.append(selection.fixture_id)

    ceiling = calculate_call_ceiling(checked)
    blockers.extend(_budget_blockers(checked, ceiling))
    if len(admitted) != len(checked.selected_fixtures):
        blockers.append(
            AdmissionBlocker(
                code="fixture_set_not_fully_admitted",
                message="Every selected fixture must pass live-manifest admission",
            )
        )
    ready = not blockers
    return AdmissionReport(
        protocol_id=checked.protocol_id,
        technical_ready=ready,
        ready=ready,
        protocol_sha256=protocol_sha256(checked),
        dataset_sha256=actual_dataset_hash,
        admitted_fixture_ids=tuple(admitted),
        call_ceiling=ceiling,
        blockers=tuple(blockers),
        human_approval=HumanApprovalBoundary(
            statement=(
                "Reviewer identities, consent, provenance, and evidence references are unverified "
                "claims requiring external human verification."
            )
        ),
        authorization_statement="Technical admission does not authorize or execute a live study.",
    )


def _structural_failure(code: str, message: str) -> AdmissionReport:
    return AdmissionReport(
        protocol_id=None,
        technical_ready=False,
        ready=False,
        protocol_sha256=None,
        dataset_sha256=None,
        admitted_fixture_ids=(),
        call_ceiling=None,
        blockers=(AdmissionBlocker(code=code, message=message),),
        human_approval=HumanApprovalBoundary(
            statement=(
                "Reviewer identities, consent, provenance, and evidence references are unverified "
                "claims requiring external human verification."
            )
        ),
        authorization_statement="Technical admission does not authorize or execute a live study.",
    )


def _write_reserved(handle: Any, report: AdmissionReport) -> None:
    handle.seek(0)
    handle.truncate()
    json.dump(report.model_dump(mode="json"), handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def validate_to_report(
    dataset_path: Path, protocol_path: Path, output_path: Path
) -> AdmissionReport:
    """Reserve output first, then perform entirely offline validation."""

    if not output_path.parent.is_dir():
        raise ValueError("Output parent directory does not exist")
    with output_path.open("x+", encoding="utf-8") as output:
        staged = _structural_failure(
            "validation_incomplete", "Validation was staged but did not complete"
        )
        _write_reserved(output, staged)
        try:
            with protocol_path.open(encoding="utf-8") as handle:
                raw_protocol = json.load(handle)
            protocol = LiveStudyProtocol.model_validate(raw_protocol)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError):
            report = _structural_failure(
                "invalid_protocol",
                "Protocol is missing, malformed, unsafe, or structurally invalid",
            )
            _write_reserved(output, report)
            return report
        try:
            dataset = load_dataset(dataset_path)
            report = admit_protocol(protocol, dataset, protocol_path)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError):
            report = _structural_failure(
                "validation_failed", "Dataset or referenced fixture validation failed safely"
            )
        _write_reserved(output, report)
        return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a future live-study protocol offline")
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = validate_to_report(args.dataset, args.protocol, args.output)
    except FileExistsError:
        parser.exit(2, "Admission validation refused: output already exists\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Admission validation could not stage output: {type(exc).__name__}\n")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
