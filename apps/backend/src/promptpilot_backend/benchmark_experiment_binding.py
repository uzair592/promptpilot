"""Frozen protocol, fixture, and target-parameter bindings for experiment runs.

An experiment run is bound once, at staging time, to the exact protocol,
dataset, fixture set, and target generation parameters it was admitted against.
Any later change to any of those inputs invalidates the binding, so a run can
never be re-interpreted under a protocol that was edited after the fact.

This module performs no provider construction and no provider execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .benchmark import BenchmarkDataset, dataset_sha256
from .benchmark_call_ledger import (
    canonical_artifact_sha256,
    generation_parameters_sha256,
)
from .benchmark_fixtures import (
    FixtureManifest,
    manifest_sha256,
    text_sha256,
    validate_manifest,
)
from .production_benchmark_protocol import (
    CallCeiling,
    LiveStudyProtocol,
    RoleCallBudget,
    TargetGenerationParameters,
    calculate_call_ceiling,
    protocol_sha256,
)

ConditionOrder = Literal["alternating_paired"]


class BindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictBindingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class FixtureBinding(StrictBindingModel):
    """Identity of the one approved fixture bound to a task."""

    fixture_id: str
    manifest_sha256: str
    dataset_sha256: str
    task_id: str
    original_task_sha256: str
    document_content_sha256: tuple[str, ...]
    clarification_answer_sha256: tuple[str, ...]
    fixture_kind: str
    review_status: str
    live_eligible: bool

    @model_validator(mode="after")
    def synthetic_never_live(self) -> FixtureBinding:
        if self.fixture_kind == "synthetic_offline_test" and self.live_eligible:
            raise ValueError("Synthetic fixtures are permanently not live-eligible")
        return self


class TargetParameterBinding(StrictBindingModel):
    """Frozen target generation parameters shared by both conditions."""

    generation_parameter_sha256: str
    temperature: float
    max_tokens: int
    top_p: float
    seed: int | None
    stop: tuple[str, ...]
    presence_penalty: float
    frequency_penalty: float


class ProtocolBinding(StrictBindingModel):
    """Everything an experiment run is pinned to. Changing any field is fatal."""

    protocol_id: str
    protocol_sha256: str
    dataset_name: str
    dataset_sha256: str
    fixture_bindings: tuple[FixtureBinding, ...]
    repetitions: int
    question_cap: int
    comparison_policy_sha256: str
    fallback_admission: str
    evaluation_primary: str
    evaluation_secondary: str | None
    rubric_version: str
    target_provider: str
    target_model: str
    target_parameters: TargetParameterBinding
    call_ceiling: CallCeiling
    analysis_stratum: str
    execution_mode: Literal["offline_dry_run"]

    @model_validator(mode="after")
    def fixture_ids_unique(self) -> ProtocolBinding:
        ids = [item.fixture_id for item in self.fixture_bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("Bound fixture IDs must be unique")
        return self


def _fixture_binding(
    manifest: FixtureManifest, dataset: BenchmarkDataset, manifest_path: Path
) -> FixtureBinding:
    checked = validate_manifest(manifest, dataset, manifest_path)
    return FixtureBinding(
        fixture_id=checked.fixture_id,
        manifest_sha256=manifest_sha256(checked),
        dataset_sha256=dataset_sha256(dataset),
        task_id=checked.task_id,
        original_task_sha256=text_sha256(checked.original_task.content),
        document_content_sha256=tuple(
            item.content_sha256 for item in checked.frozen_documents
        ),
        clarification_answer_sha256=tuple(
            item.content_sha256 for item in checked.clarification_answers
        ),
        fixture_kind=checked.fixture_kind,
        review_status=checked.review.status,
        live_eligible=checked.live_eligible,
    )


def _target_binding(protocol: LiveStudyProtocol) -> TargetParameterBinding:
    params: TargetGenerationParameters = protocol.baseline_target_parameters
    return TargetParameterBinding(
        generation_parameter_sha256=generation_parameters_sha256(protocol),
        temperature=params.temperature,
        max_tokens=params.max_tokens,
        top_p=params.top_p,
        seed=params.seed,
        stop=tuple(params.stop),
        presence_penalty=params.presence_penalty,
        frequency_penalty=params.frequency_penalty,
    )


def bind_protocol(
    protocol: LiveStudyProtocol,
    dataset: BenchmarkDataset,
    fixture_manifests: Sequence[tuple[FixtureManifest, Path]],
    *,
    execution_mode: Literal["offline_dry_run"] = "offline_dry_run",
) -> ProtocolBinding:
    """Pin a protocol/dataset/fixture set into an immutable binding."""

    checked = LiveStudyProtocol.model_validate(protocol.model_dump(mode="python"))
    dataset_checked = BenchmarkDataset.model_validate(dataset.model_dump(mode="python"))
    actual_dataset_hash = dataset_sha256(dataset_checked)
    if (
        checked.dataset_name != dataset_checked.name
        or checked.dataset_sha256 != actual_dataset_hash
    ):
        raise BindingError(
            "dataset_identity_mismatch", "Protocol dataset identity differs from the dataset"
        )
    bindings = tuple(
        _fixture_binding(manifest, dataset_checked, path)
        for manifest, path in fixture_manifests
    )
    selected = tuple(item.fixture_id for item in checked.selected_fixtures)
    if tuple(item.fixture_id for item in bindings) != selected:
        raise BindingError(
            "fixture_set_mismatch", "Bound fixtures differ from protocol selected fixtures"
        )
    ceiling = calculate_call_ceiling(checked)
    return ProtocolBinding(
        protocol_id=checked.protocol_id,
        protocol_sha256=protocol_sha256(checked),
        dataset_name=dataset_checked.name,
        dataset_sha256=actual_dataset_hash,
        fixture_bindings=bindings,
        repetitions=checked.repetitions,
        question_cap=checked.question_cap,
        comparison_policy_sha256=canonical_artifact_sha256(
            checked.comparison_policy.model_dump(mode="json")
        ),
        fallback_admission=checked.comparison_policy.fallback_admission,
        evaluation_primary=checked.evaluation.primary,
        evaluation_secondary=checked.evaluation.secondary,
        rubric_version="v1",
        target_provider=checked.providers.baseline_target.provider,
        target_model=checked.providers.baseline_target.model,
        target_parameters=_target_binding(checked),
        call_ceiling=ceiling,
        analysis_stratum=checked.analysis_stratum.name,
        execution_mode=execution_mode,
    )


def assert_binding_current(binding: ProtocolBinding, protocol: LiveStudyProtocol) -> None:
    """Fail if the protocol drifted from the binding after staging."""

    checked = LiveStudyProtocol.model_validate(protocol.model_dump(mode="python"))
    if protocol_sha256(checked) != binding.protocol_sha256:
        raise BindingError(
            "protocol_drift_after_staging",
            "Protocol hash changed after the experiment was bound",
        )


def assert_fixture_current(
    binding: ProtocolBinding,
    fixture_id: str,
    manifest: FixtureManifest,
    dataset: BenchmarkDataset,
    manifest_path: Path,
) -> None:
    """Re-verify one fixture against its binding immediately before use."""

    current = _fixture_binding(manifest, dataset, manifest_path)
    frozen = next(
        (item for item in binding.fixture_bindings if item.fixture_id == fixture_id), None
    )
    if frozen is None:
        raise BindingError("fixture_not_bound", "Fixture is not part of this experiment")
    if current != frozen:
        raise BindingError(
            "fixture_drift_after_staging",
            "Fixture manifest differs from the binding frozen at staging",
        )


def assert_target_parameters_identical(
    protocol: LiveStudyProtocol,
) -> TargetParameterBinding:
    """Both conditions must share one target parameter set before execution."""

    checked = LiveStudyProtocol.model_validate(protocol.model_dump(mode="python"))
    if checked.baseline_target_parameters != checked.promptpilot_target_parameters:
        raise BindingError(
            "target_parameters_mismatch",
            "Baseline and PromptPilot target parameters differ",
        )
    return _target_binding(checked)


def role_budget_summary(ceiling: CallCeiling) -> RoleCallBudget:
    return ceiling.by_role