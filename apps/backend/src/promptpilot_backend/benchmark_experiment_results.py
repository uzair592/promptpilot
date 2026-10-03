"""Immutable experiment results, provenance capture, and export contract.

Every unit is recorded with an explicit disposition. Nothing is silently
deleted: partial, failed, and invalid pairs are exported with their reason codes
so later analysis cannot quietly drop unfavourable outcomes.

The human-review models describe the approved review sample shape
(8 pairs, 2 blinded reviewers, 5 v1 dimensions) but carry no scores. No human
review data is fabricated by this module.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .benchmark_call_ledger import TargetCondition
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


class HumanReviewRecord(StrictResultModel):
    """One blinded reviewer's score for one dimension of one preselected pair.

    This is the *only* structure that may carry a human score. It exists
    separately from :class:`HumanReviewSampleSlot` so the pre-review artifact
    is structurally incapable of holding scores. The application never creates
    a record; a record only appears once a real human has reviewed the pair.
    """

    pair_id: str
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
    """One preselected pair awaiting blinded human review.

    This pre-review artifact is deliberately score-free. It carries only pair
    identity, the neutral A/B responses shown to reviewers, the rubric version,
    and pending/adjudication state. It has no reviewer list, no score field, and
    no condition or model identity. Actual scores live exclusively in
    :class:`HumanReviewRecord`.
    """

    pair_id: str
    task_id: str
    repetition: int
    preselected: Literal[True]
    response_a: str
    response_b: str
    neutral_label_mapping_stored_separately: Literal[True]
    rubric_version: str = RUBRIC_VERSION
    review_status: Literal["pending", "reviewed"] = "pending"
    adjudication_status: Literal["not_required", "pending", "adjudicated"] = (
        "not_required"
    )

    @property
    def awaiting_review(self) -> bool:
        return self.review_status == "pending"


class HumanReviewPlan(StrictResultModel):
    """The approved review plan.

    ``slots`` holds the blinded pre-review samples, which are score-free.
    ``records`` holds actual human review data and is empty until a real human
    reviews a pair. The application never populates it.
    """

    pair_count: int = Field(ge=0)
    reviewer_count: int = Field(ge=0)
    disagreement_threshold_points: int = Field(ge=0)
    adjudication_required_above_threshold: Literal[True]
    slots: tuple[HumanReviewSampleSlot, ...] = ()
    records: tuple[HumanReviewRecord, ...] = ()

    @property
    def populated(self) -> bool:
        return bool(self.slots)

    @property
    def review_record_count(self) -> int:
        return len(self.records)

    def disagreements_above_threshold(self) -> tuple[HumanReviewRecord, ...]:
        """Records flagged for adjudication, per the frozen 20-point policy."""

        return tuple(
            record for record in self.records if record.flagged_disagreement
        )


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

    def serialize(self) -> bytes:
        """The exact UTF-8 bytes written to the export file.

        This is the single serialization used by both the writer and the lock,
        so the recorded hash always describes the real file contents. It is
        deterministic: identical models always produce identical bytes.
        """

        return json.dumps(
            self.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")

    def content_sha256(self) -> str:
        """SHA-256 of the exact export file bytes, not a re-serialization."""

        return hashlib.sha256(self.serialize()).hexdigest()


class ExportLock(StrictResultModel):
    """An immutable lock record binding one export file to its exact bytes.

    ``export_sha256`` is the SHA-256 of the precise UTF-8 bytes written to the
    export file, not of a re-serialized model. Verification therefore re-hashes
    the file as it exists on disk, so any edit to the bytes is detected even
    when the document still parses to an equivalent model.

    The lock is a *separate* artifact and is never embedded in the export, so
    hashing the export cannot be perturbed by the lock's own fields.
    """

    lock_version: Literal["v1"] = "v1"
    export_schema_version: str
    experiment_scope: Literal["production_pipeline_paired_v1"]
    export_sha256: Sha256
    export_unit_count: int
    export_disposition_counts: dict[str, int]
    protocol_sha256: Sha256
    dataset_sha256: Sha256
    locked_at: datetime

    def verify_bytes(self, payload: bytes) -> ExperimentExport:
        """Re-hash real export bytes and return the parsed export.

        This is the authoritative check: it hashes the bytes as stored rather
        than re-serializing a parsed model.
        """

        actual = hashlib.sha256(payload).hexdigest()
        if self.export_sha256 != actual:
            raise ValueError("Export lock does not match the export file bytes")
        export = ExperimentExport.model_validate(json.loads(payload.decode("utf-8")))
        self.verify_metadata(export)
        return export

    def verify_file(self, path: Path) -> ExperimentExport:
        """Verify the lock against the export file currently on disk."""

        return self.verify_bytes(path.read_bytes())

    def verify_metadata(self, export: ExperimentExport) -> None:
        """Check the non-hash lock fields against a parsed export."""

        if self.export_schema_version != export.schema_version:
            raise ValueError("Export lock schema version differs")
        if self.experiment_scope != export.experiment_scope:
            raise ValueError("Export lock scope differs")
        if self.export_sha256 != export.content_sha256():
            raise ValueError("Export lock does not match the export content hash")
        if self.export_unit_count != export.unit_count:
            raise ValueError("Export lock unit count differs")
        if self.export_disposition_counts != export.disposition_counts:
            raise ValueError("Export lock disposition counts differ")
        if self.protocol_sha256 != export.protocol_sha256:
            raise ValueError("Export lock protocol hash differs")
        if self.dataset_sha256 != export.dataset_sha256:
            raise ValueError("Export lock dataset hash differs")

    def verify(self, export: ExperimentExport) -> None:
        """Verify the lock against an in-memory export.

        Equivalent to :meth:`verify_bytes` for a model built in memory, because
        serialization is deterministic. Prefer :meth:`verify_file` when checking
        an artifact that has already been written.
        """

        self.verify_bytes(export.serialize())


def lock_export(
    export: ExperimentExport, *, locked_at: datetime | None = None
) -> ExportLock:
    """Build the deterministic lock record for a finalized export.

    ``export_sha256`` is computed from :meth:`ExperimentExport.serialize`, the
    same bytes :func:`write_export` writes to disk.
    """

    return ExportLock(
        export_schema_version=export.schema_version,
        experiment_scope=export.experiment_scope,
        export_sha256=export.content_sha256(),
        export_unit_count=export.unit_count,
        export_disposition_counts=dict(export.disposition_counts),
        protocol_sha256=export.protocol_sha256,
        dataset_sha256=export.dataset_sha256,
        locked_at=locked_at or datetime.now(UTC),
    )


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


def write_export(
    export: ExperimentExport, path: Path, *, locked_at: datetime | None = None
) -> ExportLock:
    """Write an immutable export plus its lock record, and return the lock.

    Refuses to overwrite either artifact. The export bytes on disk are the
    exact content the lock's ``export_sha256`` was computed from, so the lock
    can always be verified against the file it accompanies. ``locked_at`` is
    injectable so the whole write path is deterministic under test.
    """

    if path.exists():
        raise ValueError("Refusing to overwrite an existing experiment export")
    lock_path = path.with_suffix(f"{path.suffix}.lock.json")
    if lock_path.exists():
        raise ValueError("Refusing to overwrite an existing experiment export lock")
    lock = lock_export(export, locked_at=locked_at)
    payload = export.serialize()
    if hashlib.sha256(payload).hexdigest() != lock.export_sha256:
        raise ValueError("Export lock does not describe the bytes being written")
    path.write_bytes(payload)
    lock_path.write_bytes(
        json.dumps(
            lock.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
    )
    return lock


def load_export(path: Path) -> ExperimentExport:
    return ExperimentExport.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_export_lock(path: Path) -> ExportLock:
    """Load the lock that accompanies the export at ``path``."""

    lock_path = path.with_suffix(f"{path.suffix}.lock.json")
    return ExportLock.model_validate(json.loads(lock_path.read_text(encoding="utf-8")))
