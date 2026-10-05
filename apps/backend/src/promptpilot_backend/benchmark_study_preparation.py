"""Study preparation and admission workflow for the frozen production study.

This module implements the *preparation* milestone only. It never
executes the study, never contacts a provider, never spends credits,
and never manufactures a human decision. It validates human-supplied
inputs and reports exactly what is still missing.

The module deliberately reuses the existing launch-gate, admission,
fixture, pricing, and protocol architecture instead of introducing a
competing readiness system. Every readiness answer is derived from the
same frozen declarations the live runner already enforces.

Research principle: Prompt Quality != Response Quality. The study is an
unbiased paired comparison; this module only prepares the inputs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .benchmark import BenchmarkDataset, dataset_sha256
from .benchmark_experiment_analysis import (
    DryRunPlan,
    plan_dry_run,
)
from .benchmark_experiment_authorization import (
    LiveLaunchAuthorization,
    evaluate_launch_gate,
)
from .benchmark_fixtures import (
    FixtureManifest,
    manifest_sha256,
    validate_manifest,
)
from .benchmark_pricing import (
    PricingSnapshotError,
    ProviderPricingSnapshot,
    pricing_snapshot_reference,
    validate_pricing_snapshot,
)
from .production_benchmark_protocol import (
    AdmissionReport,
    LiveStudyProtocol,
    TargetGenerationParameters,
    admit_protocol,
    calculate_call_ceiling,
    protocol_sha256,
)

StudyReadinessState = Literal["ready", "blocked"]
StudyExecutionState = Literal["not_run", "blocked", "authorized_pending_human"]

# The frozen production-study shape. These are immutable and are never
# relaxed by this module.
FROZEN_TASK_COUNT = 8
FROZEN_REPETITIONS = 3
FROZEN_QUESTION_CAP = 2
FROZEN_UNIT_COUNT = FROZEN_TASK_COUNT * FROZEN_REPETITIONS
FROZEN_COMPARISON_POLICY = {
    "baseline_input": "exact_original_task",
    "execution_order": "alternating_paired",
    "unit_isolation": "task_repetition",
    "incomplete_pair_evaluation": "prohibited",
    "unmatched_gap": "skip",
    "unanswered_question": "skip",
    "fallback_admission": "reject",
}
FROZEN_EVALUATION = {"primary": "llm_judge", "secondary": None}
FROZEN_RUBRIC_VERSION = "v1"
FROZEN_ANALYSIS_STRATUM = "strict_ai_backed"
FROZEN_GENERATION_MODE = "structured"

# Frozen target generation parameters. ``max_tokens`` and ``timeout`` are
# human decisions and are validated for presence, never defaulted.
FROZEN_TARGET_PARAMETERS = {
    "temperature": 0,
    "top_p": 1.0,
    "stop": [],
    "presence_penalty": 0,
    "frequency_penalty": 0,
    "seed": None,
}

# The approved provider-call ceiling. It is independent of the monetary
# budget and is never increased.
FROZEN_CALL_CEILING = {
    "analysis": 24,
    "question_generation": 48,
    "prompt_generation": 24,
    "target_execution": 48,
    "judge": 24,
}
FROZEN_CALL_CEILING_TOTAL = sum(FROZEN_CALL_CEILING.values())

# Rubric weights for the v1 judge. Descriptive only; the module never
# computes a score.
RUBRIC_V1_WEIGHTS = {
    "relevance": 0.25,
    "completeness": 0.20,
    "instruction_following": 0.20,
    "contextual_grounding": 0.20,
    "clarity": 0.15,
}


class StudyPreparationError(ValueError):
    """A study-preparation input is absent, malformed, or inconsistent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictStudyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class StudyReadinessBlocker(StrictStudyModel):
    """One machine-readable reason the study is not ready."""

    code: str
    message: str
    field: str | None = None
    fixture_id: str | None = None


class StudyReadinessCheck(StrictStudyModel):
    """One named readiness question and its answer."""

    name: str
    ready: bool
    blocker_code: str | None = None
    detail: str | None = None


class StudyReadinessReport(StrictStudyModel):
    """The deterministic human-input checklist for the real study.

    ``technical_ready`` separates what software can verify from
    ``human_approval`` and ``authorized``, which remain false until a
    human completes the out-of-band decisions. ``live_execution_ready``
    is always false here because software cannot authorize a live run.
    """

    schema_version: Literal["v1"] = "v1"
    protocol_id: str | None = None
    protocol_sha256: str | None = None
    dataset_sha256: str | None = None
    configuration_sha256: str | None = None
    state: StudyReadinessState
    technical_ready: bool
    human_approval: bool
    authorized: bool
    live_execution_ready: Literal[False] = False
    checks: tuple[StudyReadinessCheck, ...]
    blockers: tuple[StudyReadinessBlocker, ...]
    software_verification_limit: str

    @property
    def ready(self) -> bool:
        return self.state == "ready"


class StudyConfiguration(StrictStudyModel):
    """The canonical, content-addressed study configuration artifact.

    It binds every frozen decision into one immutable representation so
    the study cannot be silently re-interpreted under a different
    configuration. The configuration is content-addressed by its own
    canonical SHA-256.
    """

    schema_version: Literal["v1"] = "v1"
    study_id: str
    protocol_id: str
    protocol_sha256: str
    dataset_name: str
    dataset_sha256: str
    fixture_ids: tuple[str, ...]
    fixture_sha256: tuple[str, ...]
    provider_assignments: dict[str, dict[str, str]]
    target_provider: str
    target_model: str
    judge_provider: str | None
    judge_model: str | None
    target_parameters: dict[str, Any]
    target_timeout_seconds: float
    question_cap: int
    skip_policies: dict[str, str]
    fallback_policy: str
    evaluator: dict[str, Any]
    rubric_version: str
    condition_order: list[list[str]]
    repetitions: int
    monetary_budget: dict[str, Any] | None
    pricing_snapshot_reference: str | None
    call_ceiling: dict[str, int]
    call_ceiling_total: int

    @model_validator(mode="after")
    def frozen_shape(self) -> StudyConfiguration:
        if len(self.fixture_ids) != FROZEN_TASK_COUNT:
            raise ValueError("The production study requires exactly 8 fixtures")
        if len(set(self.fixture_ids)) != FROZEN_TASK_COUNT:
            raise ValueError("Fixture identities must be unique")
        if len(self.fixture_sha256) != FROZEN_TASK_COUNT:
            raise ValueError("Every fixture must contribute exactly one hash")
        if self.repetitions != FROZEN_REPETITIONS:
            raise ValueError("The production study requires R=3 repetitions")
        if self.question_cap != FROZEN_QUESTION_CAP:
            raise ValueError("The production study requires Q=2")
        if self.call_ceiling_total != FROZEN_CALL_CEILING_TOTAL:
            raise ValueError("The provider-call ceiling must remain 168")
        if self.call_ceiling != FROZEN_CALL_CEILING:
            raise ValueError("The per-role provider-call ceiling is frozen")
        if self.rubric_version != FROZEN_RUBRIC_VERSION:
            raise ValueError("The rubric version is frozen at v1")
        if self.evaluator != FROZEN_EVALUATION:
            raise ValueError("The evaluation plan is frozen at llm_judge primary")
        if self.skip_policies != {
            "unmatched_gap": "skip",
            "unanswered_question": "skip",
        }:
            raise ValueError("The skip policies are frozen at skip/skip")
        if self.fallback_policy != "reject":
            raise ValueError("The fallback admission policy is frozen at reject")
        frozen_subset = {
            key: self.target_parameters.get(key)
            for key in FROZEN_TARGET_PARAMETERS
        }
        if frozen_subset != FROZEN_TARGET_PARAMETERS:
            raise ValueError("The frozen target parameters differ from the study configuration")
        max_tokens = self.target_parameters.get("max_tokens")
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("Target max_tokens is a required human decision and must be >= 1")
        return self

    @property
    def configuration_sha256(self) -> str:
        """Content-address the canonical configuration bytes."""

        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _require_frozen_target_parameters(
    parameters: TargetGenerationParameters,
) -> None:
    """Verify the frozen target parameters are exactly the approved values."""

    if parameters.temperature != 0:
        raise StudyPreparationError(
            "target_temperature_not_frozen",
            "Target temperature must be 0",
        )
    if parameters.top_p != 1.0:
        raise StudyPreparationError(
            "target_top_p_not_frozen",
            "Target top_p must be 1.0",
        )
    if tuple(parameters.stop) != ():
        raise StudyPreparationError(
            "target_stop_not_frozen",
            "Target stop must be empty",
        )
    if parameters.presence_penalty != 0:
        raise StudyPreparationError(
            "target_presence_penalty_not_frozen",
            "Target presence_penalty must be 0",
        )
    if parameters.frequency_penalty != 0:
        raise StudyPreparationError(
            "target_frequency_penalty_not_frozen",
            "Target frequency_penalty must be 0",
        )
    if parameters.seed is not None:
        raise StudyPreparationError(
            "target_seed_not_frozen",
            "Target seed must be null",
        )
    if parameters.max_tokens < 1:
        raise StudyPreparationError(
            "target_max_tokens_missing",
            "Target max_tokens is a required human decision and must be >= 1",
        )


def _target_timeout_blocker(timeout_seconds: float | None) -> StudyReadinessBlocker | None:
    if timeout_seconds is None:
        return StudyReadinessBlocker(
            code="target_timeout_missing",
            field="target_timeout_seconds",
            message=(
                "Target timeout is a required human decision; no default is invented"
            ),
        )
    if not (isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0):
        return StudyReadinessBlocker(
            code="target_timeout_invalid",
            field="target_timeout_seconds",
            message="Target timeout must be a positive number of seconds",
        )
    return None


def _check_frozen_study_shape(protocol: LiveStudyProtocol) -> list[StudyReadinessBlocker]:
    """Verify the protocol carries the immutable production-study shape."""

    blockers: list[StudyReadinessBlocker] = []
    if len(protocol.selected_fixtures) != FROZEN_TASK_COUNT:
        blockers.append(
            StudyReadinessBlocker(
                code="fixture_count_not_eight",
                field="selected_fixtures",
                message=(
                    f"The production study requires exactly {FROZEN_TASK_COUNT} "
                    f"fixtures; {len(protocol.selected_fixtures)} were supplied"
                ),
            )
        )
    fixture_ids = [item.fixture_id for item in protocol.selected_fixtures]
    if len(set(fixture_ids)) != len(fixture_ids):
        blockers.append(
            StudyReadinessBlocker(
                code="fixture_id_duplicate",
                field="selected_fixtures",
                message="Fixture identities must be unique",
            )
        )
    if protocol.repetitions != FROZEN_REPETITIONS:
        blockers.append(
            StudyReadinessBlocker(
                code="repetition_count_not_frozen",
                field="repetitions",
                message=f"The production study requires R={FROZEN_REPETITIONS}",
            )
        )
    if protocol.question_cap != FROZEN_QUESTION_CAP:
        blockers.append(
            StudyReadinessBlocker(
                code="question_cap_not_frozen",
                field="question_cap",
                message=f"The production study requires Q={FROZEN_QUESTION_CAP}",
            )
        )
    policy = protocol.comparison_policy
    if policy.unmatched_gap != "skip" or policy.unanswered_question != "skip":
        blockers.append(
            StudyReadinessBlocker(
                code="skip_policy_not_frozen",
                field="comparison_policy",
                message="The skip policies must be unmatched_gap=skip and unanswered_question=skip",
            )
        )
    if policy.fallback_admission != "reject":
        blockers.append(
            StudyReadinessBlocker(
                code="fallback_policy_not_frozen",
                field="comparison_policy",
                message="The fallback admission policy must be reject",
            )
        )
    if protocol.evaluation.primary != "llm_judge" or protocol.evaluation.secondary is not None:
        blockers.append(
            StudyReadinessBlocker(
                code="evaluation_plan_not_frozen",
                field="evaluation",
                message="The evaluation plan must be llm_judge primary with no secondary evaluator",
            )
        )
    if protocol.analysis_stratum.name != FROZEN_ANALYSIS_STRATUM:
        blockers.append(
            StudyReadinessBlocker(
                code="analysis_stratum_not_frozen",
                field="analysis_stratum",
                message="The analysis stratum must be strict_ai_backed",
            )
        )
    if protocol.generation_mode != FROZEN_GENERATION_MODE:
        blockers.append(
            StudyReadinessBlocker(
                code="generation_mode_not_frozen",
                field="generation_mode",
                message="The generation mode must be structured",
            )
        )
    return blockers


def _check_target_parameters(
    protocol: LiveStudyProtocol,
) -> list[StudyReadinessBlocker]:
    """Verify both conditions resolve to one identical frozen parameter set."""

    blockers: list[StudyReadinessBlocker] = []
    if protocol.baseline_target_parameters != protocol.promptpilot_target_parameters:
        blockers.append(
            StudyReadinessBlocker(
                code="target_parameters_not_identical",
                field="baseline_target_parameters",
                message=(
                    "Baseline and PromptPilot must resolve to one identical "
                    "target parameter set"
                ),
            )
        )
        return blockers
    try:
        _require_frozen_target_parameters(protocol.baseline_target_parameters)
    except StudyPreparationError as error:
        blockers.append(
            StudyReadinessBlocker(
                code=error.code,
                field="baseline_target_parameters",
                message=str(error),
            )
        )
    return blockers


def _check_provider_configuration(
    protocol: LiveStudyProtocol,
) -> list[StudyReadinessBlocker]:
    """Verify the frozen provider/model assignments are internally consistent."""

    blockers: list[StudyReadinessBlocker] = []
    providers = protocol.providers
    if providers.baseline_target != providers.promptpilot_target:
        blockers.append(
            StudyReadinessBlocker(
                code="target_provider_mismatch",
                field="providers",
                message=(
                    "Baseline and PromptPilot must use one identical target "
                    "provider/model assignment"
                ),
            )
        )
    if protocol.evaluation.primary == "llm_judge" and providers.judge is None:
        blockers.append(
            StudyReadinessBlocker(
                code="judge_assignment_missing",
                field="providers.judge",
                message="The llm_judge evaluator requires a judge provider/model assignment",
            )
        )
    for role in ("analysis", "question_generation", "prompt_generation", "baseline_target"):
        assignment = getattr(providers, role)
        if not assignment.provider or not assignment.model:
            blockers.append(
                StudyReadinessBlocker(
                    code="provider_assignment_incomplete",
                    field=f"providers.{role}",
                    message=f"The {role} provider/model assignment is incomplete",
                )
            )
    return blockers


def _check_monetary_budget(
    protocol: LiveStudyProtocol,
    authorization: LiveLaunchAuthorization | None,
) -> list[StudyReadinessBlocker]:
    """Verify the monetary budget is configured and matches authorization."""

    blockers: list[StudyReadinessBlocker] = []
    budget = protocol.monetary_budget
    if budget is None:
        blockers.append(
            StudyReadinessBlocker(
                code="monetary_budget_missing",
                field="monetary_budget",
                message="A monetary budget with a maximum spend and currency is required",
            )
        )
        return blockers
    if not budget.currency or not budget.maximum_cost >= 0:
        blockers.append(
            StudyReadinessBlocker(
                code="monetary_budget_incomplete",
                field="monetary_budget",
                message="The monetary budget must declare a currency and a maximum spend",
            )
        )
    if not budget.pricing_snapshot_reference:
        blockers.append(
            StudyReadinessBlocker(
                code="pricing_snapshot_reference_missing",
                field="monetary_budget.pricing_snapshot_reference",
                message="The protocol must bind to a content-addressed pricing snapshot reference",
            )
        )
    if authorization is not None:
        if authorization.spend_currency != budget.currency:
            blockers.append(
                StudyReadinessBlocker(
                    code="authorized_currency_mismatch",
                    field="monetary_budget.currency",
                    message=(
                        "Authorization currency must exactly match the frozen "
                        "protocol budget currency"
                    ),
                )
            )
        if authorization.maximum_spend != budget.maximum_cost:
            blockers.append(
                StudyReadinessBlocker(
                    code="authorized_budget_mismatch",
                    field="monetary_budget.maximum_cost",
                    message=(
                        "Authorization maximum spend must exactly match the frozen "
                        "protocol budget"
                    ),
                )
            )
    return blockers


def _check_pricing_snapshot(
    snapshot: ProviderPricingSnapshot | None,
    protocol: LiveStudyProtocol,
) -> tuple[bool, list[StudyReadinessBlocker]]:
    """Verify a fresh, hash-pinned pricing snapshot covers every frozen role."""

    blockers: list[StudyReadinessBlocker] = []
    if snapshot is None:
        return False, [
            StudyReadinessBlocker(
                code="pricing_snapshot_missing",
                field="pricing_snapshot",
                message="A fresh, hash-pinned pricing snapshot is required",
            )
        ]
    try:
        validate_pricing_snapshot(snapshot, protocol)
    except PricingSnapshotError as error:
        blockers.append(
            StudyReadinessBlocker(
                code=error.code,
                field="pricing_snapshot",
                message=str(error),
            )
        )
        return False, blockers
    return True, blockers


def _check_fixture_evidence(
    protocol: LiveStudyProtocol,
    dataset: BenchmarkDataset,
    protocol_path: Path,
    manifests: Mapping[str, FixtureManifest],
) -> list[StudyReadinessBlocker]:
    """Verify every selected fixture is current, reviewed, and live-eligible."""

    blockers: list[StudyReadinessBlocker] = []
    for selection in protocol.selected_fixtures:
        manifest = manifests.get(selection.fixture_id)
        if manifest is None:
            blockers.append(
                StudyReadinessBlocker(
                    code="fixture_manifest_missing",
                    fixture_id=selection.fixture_id,
                    message="No manifest was supplied for the selected fixture",
                )
            )
            continue
        try:
            checked = validate_manifest(manifest, dataset, protocol_path / selection.manifest_path)
        except (ValueError, OSError) as error:
            blockers.append(
                StudyReadinessBlocker(
                    code="fixture_validation_failed",
                    fixture_id=selection.fixture_id,
                    message=f"Fixture validation failed: {error}",
                )
            )
            continue
        if manifest_sha256(checked) != selection.manifest_sha256:
            blockers.append(
                StudyReadinessBlocker(
                    code="fixture_hash_mismatch",
                    fixture_id=selection.fixture_id,
                    message="The fixture manifest hash differs from the protocol selection",
                )
            )
            continue
        if not checked.live_eligible:
            blockers.append(
                StudyReadinessBlocker(
                    code="fixture_not_live_eligible",
                    fixture_id=selection.fixture_id,
                    message=(
                        "The fixture is not a human-reviewed experimental candidate; "
                        "synthetic fixtures are permanently not live-eligible"
                    ),
                )
            )
            continue
        if checked.review.reviewer_id is None or checked.review.reviewed_at is None:
            blockers.append(
                StudyReadinessBlocker(
                    code="fixture_review_evidence_missing",
                    fixture_id=selection.fixture_id,
                    message="Human review evidence (reviewer_id and reviewed_at) is required",
                )
            )
    return blockers


def build_study_configuration(
    protocol: LiveStudyProtocol,
    dataset: BenchmarkDataset,
    manifests: Mapping[str, FixtureManifest],
    *,
    protocol_path: Path,
    target_timeout_seconds: float | None,
    pricing_snapshot: ProviderPricingSnapshot | None = None,
) -> StudyConfiguration:
    """Build the canonical, content-addressed study configuration.

    The configuration is derived only from human-supplied frozen
    declarations. It never invents a provider, model, max_tokens,
    timeout, budget, or pricing value.
    """

    _require_frozen_target_parameters(protocol.baseline_target_parameters)
    if protocol.baseline_target_parameters != protocol.promptpilot_target_parameters:
        raise StudyPreparationError(
            "target_parameters_not_identical",
            "Baseline and PromptPilot target parameters must be identical",
        )
    if len(protocol.selected_fixtures) != FROZEN_TASK_COUNT:
        raise StudyPreparationError(
            "fixture_count_not_eight",
            "The production study requires exactly 8 fixtures",
        )
    timeout_blocker = _target_timeout_blocker(target_timeout_seconds)
    if timeout_blocker is not None:
        raise StudyPreparationError(timeout_blocker.code, timeout_blocker.message)
    assert target_timeout_seconds is not None
    fixture_ids: list[str] = []
    fixture_hashes: list[str] = []
    for selection in protocol.selected_fixtures:
        manifest = manifests.get(selection.fixture_id)
        if manifest is None:
            raise StudyPreparationError(
                "fixture_manifest_missing",
                f"No manifest was supplied for fixture {selection.fixture_id}",
            )
        checked = validate_manifest(
            manifest, dataset, protocol_path.parent / selection.manifest_path
        )
        if manifest_sha256(checked) != selection.manifest_sha256:
            raise StudyPreparationError(
                "fixture_hash_mismatch",
                f"Fixture hash mismatch for {selection.fixture_id}",
            )
        fixture_ids.append(selection.fixture_id)
        fixture_hashes.append(manifest_sha256(checked))

    providers = protocol.providers
    budget = protocol.monetary_budget
    ceiling = calculate_call_ceiling(protocol)
    condition_order: list[list[str]] = []
    for repetition in range(1, protocol.repetitions + 1):
        condition_order.append(
            ["baseline", "promptpilot"] if repetition % 2 else ["promptpilot", "baseline"]
        )
    parameters = protocol.baseline_target_parameters
    return StudyConfiguration(
        study_id=protocol.protocol_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256(protocol),
        dataset_name=dataset.name,
        dataset_sha256=dataset_sha256(dataset),
        fixture_ids=tuple(fixture_ids),
        fixture_sha256=tuple(fixture_hashes),
        provider_assignments={
            role: {
                "provider": assignment.provider,
                "model": assignment.model,
            }
            for role, assignment in (
                ("analysis", providers.analysis),
                ("question_generation", providers.question_generation),
                ("prompt_generation", providers.prompt_generation),
                ("baseline_target", providers.baseline_target),
                ("promptpilot_target", providers.promptpilot_target),
                ("judge", providers.judge),
            )
            if assignment is not None
        },
        target_provider=providers.baseline_target.provider,
        target_model=providers.baseline_target.model,
        judge_provider=providers.judge.provider if providers.judge is not None else None,
        judge_model=providers.judge.model if providers.judge is not None else None,
        target_parameters={
            "temperature": parameters.temperature,
            "top_p": parameters.top_p,
            "stop": list(parameters.stop),
            "presence_penalty": parameters.presence_penalty,
            "frequency_penalty": parameters.frequency_penalty,
            "seed": parameters.seed,
            "max_tokens": parameters.max_tokens,
        },
        target_timeout_seconds=target_timeout_seconds,
        question_cap=protocol.question_cap,
        skip_policies={
            "unmatched_gap": protocol.comparison_policy.unmatched_gap,
            "unanswered_question": protocol.comparison_policy.unanswered_question,
        },
        fallback_policy=protocol.comparison_policy.fallback_admission,
        evaluator={
            "primary": protocol.evaluation.primary,
            "secondary": protocol.evaluation.secondary,
        },
        rubric_version=FROZEN_RUBRIC_VERSION,
        condition_order=condition_order,
        repetitions=protocol.repetitions,
        monetary_budget=(
            {
                "currency": budget.currency,
                "maximum_cost": budget.maximum_cost,
                "pricing_snapshot_reference": budget.pricing_snapshot_reference,
            }
            if budget is not None
            else None
        ),
        pricing_snapshot_reference=(
            pricing_snapshot_reference(pricing_snapshot)
            if pricing_snapshot is not None
            else None
        ),
        call_ceiling=ceiling.by_role.model_dump(),
        call_ceiling_total=ceiling.total,
    )


def evaluate_study_readiness(
    *,
    protocol: LiveStudyProtocol,
    dataset: BenchmarkDataset,
    protocol_path: Path,
    manifests: Mapping[str, FixtureManifest],
    target_timeout_seconds: float | None = None,
    pricing_snapshot: ProviderPricingSnapshot | None = None,
    authorization: LiveLaunchAuthorization | None = None,
    admission_report: AdmissionReport | None = None,
) -> StudyReadinessReport:
    """Compute the deterministic human-input checklist for the real study.

    The report separates technical readiness (what software can verify)
    from human approval and actual authorization. It never sets
    ``live_execution_ready`` to true and never manufactures a missing
    human decision.
    """

    checked_protocol = LiveStudyProtocol.model_validate(
        protocol.model_dump(mode="python")
    )
    checked_dataset = BenchmarkDataset.model_validate(dataset.model_dump(mode="python"))
    blockers: list[StudyReadinessBlocker] = []
    checks: list[StudyReadinessCheck] = []

    # Protocol locked.
    protocol_locked = checked_protocol.review.status == "locked"
    checks.append(
        StudyReadinessCheck(
            name="protocol_locked",
            ready=protocol_locked,
            blocker_code=None if protocol_locked else "protocol_not_locked",
            detail=(
                "Protocol review status is locked"
                if protocol_locked
                else "Protocol review is not locked"
            ),
        )
    )
    if not protocol_locked:
        blockers.append(
            StudyReadinessBlocker(
                code="protocol_not_locked",
                field="review.status",
                message="Protocol review status must be locked",
            )
        )

    # Dataset locked.
    dataset_hash = dataset_sha256(checked_dataset)
    dataset_locked = (
        checked_protocol.dataset_name == checked_dataset.name
        and checked_protocol.dataset_sha256 == dataset_hash
    )
    checks.append(
        StudyReadinessCheck(
            name="dataset_locked",
            ready=dataset_locked,
            blocker_code=None if dataset_locked else "dataset_identity_mismatch",
            detail="Protocol dataset identity matches the supplied dataset"
            if dataset_locked
            else "Protocol dataset name or hash differs from the supplied dataset",
        )
    )
    if not dataset_locked:
        blockers.append(
            StudyReadinessBlocker(
                code="dataset_identity_mismatch",
                field="dataset_sha256",
                message="Protocol dataset name or canonical hash differs from the supplied dataset",
            )
        )

    # Frozen study shape.
    shape_blockers = _check_frozen_study_shape(checked_protocol)
    blockers.extend(shape_blockers)
    checks.append(
        StudyReadinessCheck(
            name="exactly_eight_eligible_fixtures",
            ready=not any(
                blocker.code
                in {
                    "fixture_count_not_eight",
                    "fixture_id_duplicate",
                    "repetition_count_not_frozen",
                    "question_cap_not_frozen",
                }
                for blocker in shape_blockers
            ),
            blocker_code=(
                shape_blockers[0].code if shape_blockers else None
            ),
            detail=(
                "The study carries the frozen 8-fixture, R=3, Q=2 shape"
                if not shape_blockers
                else "The frozen study shape is violated"
            ),
        )
    )

    # Fixture evidence and hashes.
    fixture_blockers = _check_fixture_evidence(
        checked_protocol, checked_dataset, protocol_path, manifests
    )
    blockers.extend(fixture_blockers)
    fixture_ready = not fixture_blockers
    checks.append(
        StudyReadinessCheck(
            name="all_fixture_hashes_current",
            ready=fixture_ready,
            blocker_code=None if fixture_ready else fixture_blockers[0].code,
            detail=(
                "Every selected fixture is current, reviewed, and live-eligible"
                if fixture_ready
                else "At least one fixture is stale, unreviewed, or not live-eligible"
            ),
        )
    )
    checks.append(
        StudyReadinessCheck(
            name="all_required_review_evidence_present",
            ready=not any(
                blocker.code == "fixture_review_evidence_missing" for blocker in fixture_blockers
            ),
            blocker_code=(
                next(
                    (
                        blocker.code
                        for blocker in fixture_blockers
                        if blocker.code == "fixture_review_evidence_missing"
                    ),
                    None,
                )
            ),
            detail=(
                "Every fixture carries human review evidence"
                if not any(
                    blocker.code == "fixture_review_evidence_missing"
                    for blocker in fixture_blockers
                )
                else "At least one fixture is missing human review evidence"
            ),
        )
    )

    # Target parameters.
    parameter_blockers = _check_target_parameters(checked_protocol)
    blockers.extend(parameter_blockers)
    parameters_ready = not parameter_blockers
    checks.append(
        StudyReadinessCheck(
            name="target_parameters_identical",
            ready=parameters_ready,
            blocker_code=None if parameters_ready else parameter_blockers[0].code,
            detail=(
                "Both conditions resolve to one identical frozen parameter set"
                if parameters_ready
                else "Target parameters are not identical or not frozen"
            ),
        )
    )

    # max_tokens and timeout are explicit human decisions.
    max_tokens_ready = checked_protocol.baseline_target_parameters.max_tokens >= 1
    checks.append(
        StudyReadinessCheck(
            name="max_tokens_chosen",
            ready=max_tokens_ready,
            blocker_code=None if max_tokens_ready else "target_max_tokens_missing",
            detail=(
                f"Target max_tokens is set to "
                f"{checked_protocol.baseline_target_parameters.max_tokens}"
                if max_tokens_ready
                else "Target max_tokens is a required human decision"
            ),
        )
    )
    if not max_tokens_ready:
        blockers.append(
            StudyReadinessBlocker(
                code="target_max_tokens_missing",
                field="baseline_target_parameters.max_tokens",
                message="Target max_tokens is a required human decision and must be >= 1",
            )
        )
    timeout_blocker = _target_timeout_blocker(target_timeout_seconds)
    timeout_ready = timeout_blocker is None
    checks.append(
        StudyReadinessCheck(
            name="timeout_chosen",
            ready=timeout_ready,
            blocker_code=(
                None
                if timeout_ready
                else timeout_blocker.code
                if timeout_blocker
                else None
            ),
            detail=(
                f"Target timeout is set to {target_timeout_seconds} seconds"
                if timeout_ready
                else "Target timeout is a required human decision"
            ),
        )
    )
    if timeout_blocker is not None:
        blockers.append(timeout_blocker)

    # Provider/model configuration.
    provider_blockers = _check_provider_configuration(checked_protocol)
    blockers.extend(provider_blockers)
    provider_ready = not provider_blockers
    checks.append(
        StudyReadinessCheck(
            name="provider_and_model_selected",
            ready=provider_ready,
            blocker_code=None if provider_ready else provider_blockers[0].code,
            detail=(
                "Every frozen provider role is assigned and the target is shared by both conditions"
                if provider_ready
                else "At least one provider role is incomplete or inconsistent"
            ),
        )
    )

    # Pricing snapshot.
    pricing_valid, pricing_blockers = _check_pricing_snapshot(
        pricing_snapshot, checked_protocol
    )
    blockers.extend(pricing_blockers)
    checks.append(
        StudyReadinessCheck(
            name="pricing_snapshot_verified",
            ready=pricing_valid,
            blocker_code=(
                None
                if pricing_valid
                else pricing_blockers[0].code
                if pricing_blockers
                else None
            ),
            detail=(
                "A fresh, hash-pinned pricing snapshot covers every frozen role"
                if pricing_valid
                else "The pricing snapshot is missing, stale, mismatched, or incomplete"
            ),
        )
    )

    # Monetary budget and authorization.
    budget_blockers = _check_monetary_budget(checked_protocol, authorization)
    blockers.extend(budget_blockers)
    budget_ready = not any(
        blocker.code
        in {
            "monetary_budget_missing",
            "monetary_budget_incomplete",
            "pricing_snapshot_reference_missing",
        }
        for blocker in budget_blockers
    )
    checks.append(
        StudyReadinessCheck(
            name="budget_configured",
            ready=budget_ready,
            blocker_code=(
                None
                if budget_ready
                else budget_blockers[0].code
                if budget_blockers
                else None
            ),
            detail=(
                "The monetary budget declares a maximum spend and currency"
                if budget_ready
                else "The monetary budget is missing or incomplete"
            ),
        )
    )
    checks.append(
        StudyReadinessCheck(
            name="currency_configured",
            ready=budget_ready,
            blocker_code=(
                None
                if budget_ready
                else budget_blockers[0].code
                if budget_blockers
                else None
            ),
            detail=(
                f"The budget currency is {checked_protocol.monetary_budget.currency}"
                if budget_ready and checked_protocol.monetary_budget is not None
                else "The budget currency is not configured"
            ),
        )
    )

    # Authorization.
    authorization_supplied = authorization is not None
    checks.append(
        StudyReadinessCheck(
            name="provider_authorization_supplied",
            ready=authorization_supplied,
            blocker_code=None if authorization_supplied else "launch_authorization_absent",
            detail=(
                "An external launch authorization was supplied"
                if authorization_supplied
                else "No external launch authorization was supplied"
            ),
        )
    )
    checks.append(
        StudyReadinessCheck(
            name="spending_authorization_supplied",
            ready=authorization_supplied,
            blocker_code=None if authorization_supplied else "launch_authorization_absent",
            detail=(
                "The external authorization grants spending"
                if authorization_supplied
                else "No external authorization grants spending"
            ),
        )
    )
    checks.append(
        StudyReadinessCheck(
            name="external_human_authorization_supplied",
            ready=authorization_supplied,
            blocker_code=None if authorization_supplied else "launch_authorization_absent",
            detail=(
                "An external human authorization artifact was presented"
                if authorization_supplied
                else "No external human authorization artifact was presented"
            ),
        )
    )
    if not authorization_supplied:
        blockers.append(
            StudyReadinessBlocker(
                code="launch_authorization_absent",
                field="authorization",
                message="No external launch authorization was supplied",
            )
        )

    # Technical admission.
    if admission_report is None:
        admission_report = admit_protocol(checked_protocol, checked_dataset, protocol_path)
    admission_ready = admission_report.ready
    checks.append(
        StudyReadinessCheck(
            name="technical_admission_ready",
            ready=admission_ready,
            blocker_code=None if admission_ready else "protocol_admission_failed",
            detail=(
                "Technical admission passed for every selected fixture"
                if admission_ready
                else "Technical admission failed for at least one fixture"
            ),
        )
    )
    if not admission_ready:
        for admission_blocker in admission_report.blockers:
            blockers.append(
                StudyReadinessBlocker(
                    code=admission_blocker.code,
                    field=admission_blocker.field,
                    message=admission_blocker.message,
                    fixture_id=admission_blocker.fixture_id,
                )
            )

    # Launch gate capable of passing. The gate is evaluated with the
    # supplied authorization; it always reports ready=false because
    # software cannot verify human admission.
    launch_report = evaluate_launch_gate(
        protocol_locked=protocol_locked,
        fixture_ids=[item.fixture_id for item in checked_protocol.selected_fixtures],
        live_eligible_fixture_ids=[
            item.fixture_id
            for item in checked_protocol.selected_fixtures
            if manifests.get(item.fixture_id) is not None
            and manifests[item.fixture_id].live_eligible
        ],
        protocol_sha256=protocol_sha256(checked_protocol),
        authorization=authorization,
        target_provider=checked_protocol.providers.baseline_target.provider,
        target_model=checked_protocol.providers.baseline_target.model,
        pricing_snapshot_valid=pricing_valid,
        budget_currency=(
            checked_protocol.monetary_budget.currency
            if checked_protocol.monetary_budget is not None
            else None
        ),
        budget_maximum_cost=(
            checked_protocol.monetary_budget.maximum_cost
            if checked_protocol.monetary_budget is not None
            else None
        ),
        required_provider_assignments=tuple(
            (assignment.provider, assignment.model)
            for assignment in (
                checked_protocol.providers.analysis,
                checked_protocol.providers.question_generation,
                checked_protocol.providers.prompt_generation,
                checked_protocol.providers.baseline_target,
            )
        ),
        provider_configuration_valid=False,
        admission_ready=admission_ready,
    )
    gate_capable = launch_report.technical_ready
    checks.append(
        StudyReadinessCheck(
            name="launch_gate_capable_of_passing",
            ready=gate_capable,
            blocker_code=None if gate_capable else "launch_gate_not_ready",
            detail=(
                "The launch gate is technically capable of passing once human admission completes"
                if gate_capable
                else "The launch gate has unresolved technical blockers"
            ),
        )
    )
    if not gate_capable:
        for gate_blocker in launch_report.blockers:
            if gate_blocker.code != "human_admission_unverified":
                blockers.append(
                    StudyReadinessBlocker(
                        code=gate_blocker.code,
                        message=gate_blocker.message,
                    )
                )

    # The study is ready only when every technical check passes. Human
    # approval and authorization remain separate and are never asserted
    # by software.
    technical_ready = not blockers
    state: StudyReadinessState = "ready" if technical_ready else "blocked"
    return StudyReadinessReport(
        protocol_id=checked_protocol.protocol_id,
        protocol_sha256=protocol_sha256(checked_protocol),
        dataset_sha256=dataset_hash,
        configuration_sha256=None,
        state=state,
        technical_ready=technical_ready,
        human_approval=False,
        authorized=False,
        checks=tuple(checks),
        blockers=tuple(blockers),
        software_verification_limit=(
            "Software verifies only the presence, shape, and binding of "
            "human-supplied declarations. Authenticity of any reviewer, "
            "issuer, signature, consent, or authorization remains an "
            "unverified claim requiring out-of-band human confirmation; "
            "this report can never authorize live execution."
        ),
    )


def rehearse_study_preparation(
    *,
    protocol: LiveStudyProtocol,
    dataset: BenchmarkDataset,
    protocol_path: Path,
    manifests: Mapping[str, FixtureManifest],
    target_timeout_seconds: float | None,
) -> dict[str, Any]:
    """Rehearse the complete preparation/staging workflow offline.

    The rehearsal uses only the supplied declarations and the offline
    dry-run planner. It makes zero network calls, zero real provider
    calls, spends zero money, and never produces a live-eligible
    fixture or a human approval. It proves the staging machinery works
    without involving real infrastructure.
    """

    task_ids = sorted({manifest.task_id for manifest in manifests.values()})
    plan: DryRunPlan = plan_dry_run(
        task_ids=task_ids,
        repetitions=protocol.repetitions,
        question_cap=protocol.question_cap,
        judge_enabled=protocol.evaluation.primary == "llm_judge",
    )
    ceiling = calculate_call_ceiling(protocol)
    configuration = build_study_configuration(
        protocol,
        dataset,
        manifests,
        protocol_path=protocol_path,
        target_timeout_seconds=target_timeout_seconds,
    )
    readiness = evaluate_study_readiness(
        protocol=protocol,
        dataset=dataset,
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=target_timeout_seconds,
    )
    return {
        "rehearsal_mode": "offline_dry_run",
        "network_calls": 0,
        "live_provider_calls": 0,
        "cost": 0,
        "live_eligible_fixtures_produced": 0,
        "human_approvals_created": 0,
        "plan": plan.model_dump(mode="json"),
        "call_ceiling": ceiling.model_dump(mode="json"),
        "configuration": configuration.model_dump(mode="json"),
        "configuration_sha256": configuration.configuration_sha256,
        "readiness_state": readiness.state,
        "readiness_technical_ready": readiness.technical_ready,
        "readiness_blockers": [
            blocker.model_dump(mode="json") for blocker in readiness.blockers
        ],
    }
