"""Immutable experiment results, provenance capture, and export contract.

Every unit is recorded with an explicit disposition. Nothing is silently
deleted: partial, failed, and invalid pairs are exported with their reason codes
so later analysis cannot quietly drop unfavourable outcomes.

The human-review models describe the approved review sample shape
(8 pairs, 2 blinded reviewers, 5 v1 dimensions) but carry no scores. No human
review data is fabricated by this module.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .benchmark_call_ledger import TargetCondition, canonical_artifact_sha256
from .evaluation_service import RUBRIC_VERSION
from .production_benchmark_protocol import Sha256

UnitDisposition = Literal["complete_pair", "partial_unit", "failed_unit", "invalid_pair"]
StageStatus = Literal[
    "not_started", "attempted", "succeeded", "fallback", "skipped", "failed"
]
FailureCode = str


class StrictResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class StageArtifact(StrictResultModel):
    name: str
    status: StageStatus
    timestamp: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class QuestionArtifact(StrictResultModel):
    question_id: str
    gap_id: str
    question_text: str
    resolution: Literal["answered", "skip", "unanswered"]
    reason: str | None = None
    answer_existed: bool

    @model_validator(mode="after")
    def never_fabricate_an_answer(self) -> QuestionArtifact:
        """A question may only be resolved as answered when an answer existed.

        The frozen policy is skip for both unmatched gaps and unanswered
        questions, and fabrication is prohibited outright. This invariant
        makes it impossible to record a resolved answer that never existed.
        """

        if self.resolution == "answered" and not self.answer_existed:
            raise ValueError("A question cannot be answered without a real answer")
        if self.resolution != "answered" and self.reason is None:
            raise ValueError("An unresolved question must record why it is unresolved")
        return self


class ProvenanceArtifacts(StrictResultModel):
    analysis_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()
    question_ids: tuple[str, ...] = ()
    answer_ids: tuple[str, ...] = ()
    memory_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    selected_context_ids: tuple[str, ...] = ()
    omitted_context_ids: tuple[str, ...] = ()
    prompt_version_id: str | None = None
    model_run_ids: tuple[str, ...] = ()
    evaluation_id: str | None = None


class ProviderObservationArtifact(StrictResultModel):
    role: str
    provider: str
    model: str
    request_sha256: Sha256
    status: Literal["succeeded", "failed"]
    fallback_classification: str
    safe_error_code: str | None = None


class EvaluationArtifact(StrictResultModel):
    evaluation_id: str
    method: str
    rubric_version: str = RUBRIC_VERSION
    baseline_score: float | None
    promptpilot_score: float | None
    overall_delta: float | None
    winner: str | None
    dimension_scores: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    neutral_labels: bool = True


class ExperimentUnit(StrictResultModel):
    """One task x repetition unit with a single explicit disposition."""

    experiment_scope: Literal["production_pipeline_paired_v1"] = (
        "production_pipeline_paired_v1"
    )
    execution_mode: str
    unit_id: str
    task_id: str
    task_category: str
    repetition: int
    fixture_id: str
    fixture_manifest_sha256: Sha256
    dataset_name: str
    dataset_sha256: Sha256
    protocol_id: str
    protocol_sha256: Sha256
    repository_sha: str | None = None
    disposition: UnitDisposition
    condition_order: tuple[TargetCondition, ...]
    fallback_state: Literal["none", "fallback_seen"]
    failure_reason: str | None = None
    budget_state: dict[str, Any] = Field(default_factory=dict)
    stages: tuple[StageArtifact, ...] = ()
    questions: tuple[QuestionArtifact, ...] = ()
    provenance: ProvenanceArtifacts = ProvenanceArtifacts()
    provider_observations: tuple[ProviderObservationArtifact, ...] = ()
    evaluation: EvaluationArtifact | None = None
    created_at: datetime

    @property
    def is_complete_pair(self) -> bool:
        return self.disposition == "complete_pair"


class HumanReviewScore(StrictResultModel):
    """A single blinded reviewer score. Never fabricated by the application."""

    reviewer_id: str
    dimension: Literal[
        "relevance",
        "completeness",
        "instruction_following",
        "contextual_grounding",
        "clarity",
    ]
    score: int = Field(ge=0, le=100)
    notes: str = Field(default="", max_length=4000)
    flagged_disagreement: bool = False


class HumanReviewSampleSlot(StrictResultModel):
    """One preselected pair awaiting blinded human review. Carries no scores."""

    pair_id: str
    task_id: str
    repetition: int
    preselected: Literal[True]
    response_a: str
    response_b: str
    neutral_label_mapping_stored_separately: Literal[True]
    rubric_version: str = RUBRIC_VERSION
    reviewers: tuple[HumanReviewScore, ...] = ()
    adjudication_status: Literal["pending", "adjudicated"] = "pending"

    @property
    def score_count(self) -> int:
        return len(self.reviewers)


class HumanReviewPlan(StrictResultModel):
    """The approved review plan. Sample selection and scores stay empty."""

    pair_count: int = Field(ge=0)
    reviewer_count: int = Field(ge=0)
    disagreement_threshold_points: int = Field(ge=0)
    adjudication_required_above_threshold: Literal[True]
    slots: tuple[HumanReviewSampleSlot, ...] = ()

    @property
    def populated(self) -> bool:
        return bool(self.slots)


class ExperimentExport(StrictResultModel):
    schema_version: Literal["v1"] = "v1"
    experiment_scope: Literal["production_pipeline_paired_v1"]
    execution_mode: str
    protocol_id: str
    protocol_sha256: Sha256
    dataset_name: str
    dataset_sha256: Sha256
    repository_sha: str | None = None
    generated_at: datetime
    unit_count: int
    disposition_counts: dict[str, int]
    call_ceiling_total: int
    units: tuple[ExperimentUnit, ...]

    def content_sha256(self) -> str:
        return canonical_artifact_sha256(self.model_dump(mode="json"))


def _disposition_counts(units: tuple[ExperimentUnit, ...]) -> dict[str, int]:
    counts = {
        "complete_pair": 0,
        "partial_unit": 0,
        "failed_unit": 0,
        "invalid_pair": 0,
    }
    for unit in units:
        counts[unit.disposition] += 1
    return counts


def build_export(
    *,
    units: tuple[ExperimentUnit, ...],
    protocol_id: str,
    protocol_sha256: str,
    dataset_name: str,
    dataset_sha256: str,
    execution_mode: str,
    call_ceiling_total: int,
    repository_sha: str | None = None,
) -> ExperimentExport:
    return ExperimentExport(
        experiment_scope="production_pipeline_paired_v1",
        execution_mode=execution_mode,
        protocol_id=protocol_id,
        protocol_sha256=protocol_sha256,
        dataset_name=dataset_name,
        dataset_sha256=dataset_sha256,
        repository_sha=repository_sha,
        generated_at=datetime.now(UTC),
        unit_count=len(units),
        disposition_counts=_disposition_counts(units),
        call_ceiling_total=call_ceiling_total,
        units=units,
    )


def write_export(export: ExperimentExport, path: Path) -> str:
    """Write an immutable export and return its content hash."""

    if path.exists():
        raise ValueError("Refusing to overwrite an existing experiment export")
    path.write_text(
        json.dumps(export.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return export.content_sha256()


def load_export(path: Path) -> ExperimentExport:
    return ExperimentExport.model_validate(json.loads(path.read_text(encoding="utf-8")))