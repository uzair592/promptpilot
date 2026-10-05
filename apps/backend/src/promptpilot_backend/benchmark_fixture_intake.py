"""Production fixture intake for the frozen 8-task study.

This module turns the existing frozen benchmark dataset into a
clean real-fixture intake package. It is preparation tooling
only: it never executes the study, never contacts a provider,
never spends credits, and never manufactures a human decision.

The intake package makes three things explicit:

1. **The frozen task inventory.** A machine-readable audit of
   the 8 canonical tasks exactly as they appear in the dataset.
   The task text is never modified, rewritten, reordered, or
   improved.
2. **Production fixture templates.** One ``experimental_candidate``
   fixture template per frozen task, using the existing
   ``FixtureManifest`` schema. Each template is intentionally
   incomplete: its review status is ``pending`` and it carries
   no reviewer identity, no review timestamp, and no fabricated
   provenance evidence. A pending fixture is therefore not
   live-eligible and cannot be admitted.
3. **The human fill-in checklist.** A per-fixture, machine-
   readable report of exactly what a human must supply before
   the fixture becomes eligible: reviewer identity, review
   timestamp, genuine provenance/consent evidence, and the
   admission decision.

Synthetic fixtures are never converted into production fixtures.
The ``synthetic_offline_test`` kind and ``synthetic`` review
status remain permanently ineligible.

Research principle: Prompt Quality != Response Quality. The
intake package only prepares inputs; it never asserts readiness.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .benchmark import BenchmarkDataset, BenchmarkTask, dataset_sha256
from .benchmark_fixtures import (
    FixtureManifest,
    OriginalTask,
    Provenance,
    Review,
    manifest_sha256,
    text_sha256,
)

# The frozen production-study shape. These are immutable.
FROZEN_TASK_COUNT = 8
FROZEN_REPETITIONS = 3
FROZEN_QUESTION_CAP = 2
FROZEN_UNIT_COUNT = FROZEN_TASK_COUNT * FROZEN_REPETITIONS
FROZEN_CALL_CEILING_TOTAL = 168

# The canonical dataset identity every production fixture must bind to.
CANONICAL_DATASET_NAME = "promptpilot-experimental-v1"

# Review statuses a production fixture template can carry. A template
# is born ``pending`` and only a genuine human review can move it to
# ``human_approved``.
FixtureReviewStatus = Literal["pending", "human_approved"]

# Machine-readable intake states.
IntakeState = Literal["ready", "blocked"]


class FixtureIntakeError(ValueError):
    """A fixture-intake input is absent, malformed, or inconsistent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


class StrictIntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class FrozenTaskInventory(StrictIntakeModel):
    """The machine-readable audit of one frozen benchmark task.

    The fields mirror the canonical dataset exactly. The task text
    is reproduced verbatim and is never modified.
    """

    task_id: str
    category: str
    difficulty: str
    task_text: str
    objective: str
    requirements: tuple[str, ...]
    constraints: tuple[str, ...]
    expected_output_characteristics: tuple[str, ...]
    available_context: tuple[str, ...]
    reference: str | None
    task_text_sha256: str

    @model_validator(mode="after")
    def hash_matches_text(self) -> FrozenTaskInventory:
        if self.task_text_sha256 != text_sha256(self.task_text):
            raise ValueError("task_text_sha256 does not match task_text")
        return self


class FixtureChecklistEntry(StrictIntakeModel):
    """The human fill-in checklist for one production fixture.

    Every field reports whether the human has supplied it. A
    template is born with the human-supplied fields unset, so the
    fixture is blocked until a genuine human completes them.
    """

    fixture_id: str
    task_id: str
    task_category: str
    fixture_exists: bool
    task_matches_frozen_dataset: bool
    manifest_hash: str | None
    provenance_supplied: bool
    reviewer_supplied: bool
    review_timestamp_supplied: bool
    review_status: FixtureReviewStatus
    live_eligible: bool
    missing_fields: tuple[str, ...]
    blocker_codes: tuple[str, ...]


class FixtureIntakeReport(StrictIntakeModel):
    """The deterministic production-study fixture intake report.

    The report never implies the study is ready while human-
    controlled inputs are missing. ``genuine_fixture_evidence``,
    ``human_review``, and ``live_eligibility`` remain pending or
    blocked until a genuine human completes them.
    """

    schema_version: Literal["v1"] = "v1"
    dataset_name: str
    dataset_sha256: str
    task_count: int
    task_inventory: tuple[FrozenTaskInventory, ...]
    checklist: tuple[FixtureChecklistEntry, ...]
    genuine_fixture_evidence: Literal["pending", "supplied"] = "pending"
    human_review: Literal["pending", "complete"] = "pending"
    live_eligibility: Literal["blocked", "eligible"] = "blocked"
    software_verification_limit: str

    @property
    def state(self) -> IntakeState:
        return "ready" if self.live_eligibility == "eligible" else "blocked"

    @model_validator(mode="after")
    def frozen_shape(self) -> FixtureIntakeReport:
        if self.task_count != FROZEN_TASK_COUNT:
            raise ValueError("The production study requires exactly 8 frozen tasks")
        if len(self.task_inventory) != FROZEN_TASK_COUNT:
            raise ValueError("The task inventory must cover all 8 frozen tasks")
        if len(self.checklist) != FROZEN_TASK_COUNT:
            raise ValueError("The checklist must cover all 8 production fixtures")
        return self


def audit_frozen_tasks(dataset: BenchmarkDataset) -> tuple[FrozenTaskInventory, ...]:
    """Audit the canonical dataset and return the frozen task inventory.

    The inventory reproduces each task exactly as it appears in the
    dataset. The task text is never modified.
    """

    if len(dataset.tasks) != FROZEN_TASK_COUNT:
        raise FixtureIntakeError(
            "task_count_mismatch",
            f"The canonical dataset must contain exactly {FROZEN_TASK_COUNT} tasks; "
            f"{len(dataset.tasks)} were found",
        )
    inventory: list[FrozenTaskInventory] = []
    for task in dataset.tasks:
        inventory.append(
            FrozenTaskInventory(
                task_id=task.task_id,
                category=task.category,
                difficulty=task.difficulty,
                task_text=task.task_text,
                objective=task.objective,
                requirements=tuple(task.requirements),
                constraints=tuple(task.constraints),
                expected_output_characteristics=tuple(
                    task.expected_output_characteristics
                ),
                available_context=tuple(task.available_context),
                reference=task.reference,
                task_text_sha256=text_sha256(task.task_text),
            )
        )
    return tuple(inventory)


def production_fixture_id(task_id: str) -> str:
    """Derive the production fixture id for a frozen task id."""

    return f"production-{task_id}"


def build_production_fixture_template(
    task: BenchmarkTask,
    *,
    dataset: BenchmarkDataset,
) -> FixtureManifest:
    """Build an intentionally incomplete production fixture template.

    The template uses the existing ``FixtureManifest`` schema with
    ``fixture_kind = experimental_candidate`` and
    ``review.status = pending``. It carries the exact original task
    from the dataset (with a verified content hash) and no project
    facts, clarification answers, frozen documents, or evaluation-
    only criteria. It carries no reviewer identity, no review
    timestamp, and no fabricated provenance evidence. A pending
    fixture is therefore not live-eligible and cannot be admitted.

    The human must supply: genuine project facts, clarification
    answers, frozen documents, evaluation-only criteria (as
    applicable), reviewer identity, review timestamp, and
    provenance/consent evidence.
    """

    dataset_hash = dataset_sha256(dataset)
    if dataset.name != CANONICAL_DATASET_NAME:
        raise FixtureIntakeError(
            "dataset_name_mismatch",
            f"Production fixtures must bind to the canonical dataset "
            f"{CANONICAL_DATASET_NAME!r}; {dataset.name!r} was supplied",
        )
    original_task = OriginalTask(
        fixture_id="original-task",
        task_id=task.task_id,
        source_type="dataset_original",
        content=task.task_text,
        content_sha256=text_sha256(task.task_text),
        provenance=Provenance(
            source_type="dataset_original",
            source_id=f"dataset:{task.task_id}",
            description="Exact task_text from the canonical benchmark dataset",
        ),
    )
    return FixtureManifest(
        schema_version="v1",
        fixture_id=production_fixture_id(task.task_id),
        fixture_kind="experimental_candidate",
        review=Review(
            status="pending", reviewer_id=None, reviewed_at=None
        ),
        dataset_name=dataset.name,
        dataset_sha256=dataset_hash,
        task_id=task.task_id,
        original_task=original_task,
        project_facts=(),
        clarification_answers=(),
        frozen_documents=(),
        evaluation_only=(),
    )


def _checklist_entry(
    *,
    fixture_id: str,
    task_id: str,
    task_category: str,
    fixture_exists: bool,
    task_matches_frozen_dataset: bool,
    manifest_hash: str | None,
    provenance_supplied: bool,
    reviewer_supplied: bool,
    review_timestamp_supplied: bool,
    review_status: FixtureReviewStatus,
    live_eligible: bool,
    missing_fields: Sequence[str],
    blocker_codes: Sequence[str],
) -> FixtureChecklistEntry:
    return FixtureChecklistEntry(
        fixture_id=fixture_id,
        task_id=task_id,
        task_category=task_category,
        fixture_exists=fixture_exists,
        task_matches_frozen_dataset=task_matches_frozen_dataset,
        manifest_hash=manifest_hash,
        provenance_supplied=provenance_supplied,
        reviewer_supplied=reviewer_supplied,
        review_timestamp_supplied=review_timestamp_supplied,
        review_status=review_status,
        live_eligible=live_eligible,
        missing_fields=tuple(missing_fields),
        blocker_codes=tuple(blocker_codes),
    )


def build_fixture_checklist(
    *,
    dataset: BenchmarkDataset,
    manifests: Mapping[str, FixtureManifest] | None = None,
) -> tuple[FixtureChecklistEntry, ...]:
    """Build the per-fixture human fill-in checklist.

    For every frozen task the checklist reports whether the
    production fixture exists, whether its task matches the frozen
    dataset, its manifest hash, whether provenance/reviewer/
    timestamp are supplied, its review status, its live eligibility,
    and the exact missing fields and blocker codes. A template that
    has not been human-reviewed is reported as blocked with the
    ``human_review_pending`` and ``fixture_not_live_eligible``
    blockers.
    """

    supplied = manifests or {}
    entries: list[FixtureChecklistEntry] = []
    for task in dataset.tasks:
        fixture_id = production_fixture_id(task.task_id)
        manifest = supplied.get(fixture_id)
        if manifest is None:
            entries.append(
                _checklist_entry(
                    fixture_id=fixture_id,
                    task_id=task.task_id,
                    task_category=task.category,
                    fixture_exists=False,
                    task_matches_frozen_dataset=False,
                    manifest_hash=None,
                    provenance_supplied=False,
                    reviewer_supplied=False,
                    review_timestamp_supplied=False,
                    review_status="pending",
                    live_eligible=False,
                    missing_fields=(
                        "fixture_manifest",
                        "original_task",
                        "provenance_evidence",
                        "reviewer_id",
                        "reviewed_at",
                    ),
                    blocker_codes=(
                        "fixture_manifest_missing",
                        "human_review_pending",
                        "fixture_not_live_eligible",
                    ),
                )
            )
            continue
        task_matches = manifest.task_id == task.task_id
        original_matches = (
            manifest.original_task.task_id == task.task_id
            and manifest.original_task.content == task.task_text
            and manifest.original_task.content_sha256 == text_sha256(task.task_text)
        )
        reviewer_supplied = manifest.review.reviewer_id is not None
        timestamp_supplied = manifest.review.reviewed_at is not None
        human_approved = manifest.review.status == "human_approved"
        provenance_supplied = (
            manifest.original_task.provenance.source_type == "dataset_original"
        )
        missing_fields: list[str] = []
        blocker_codes: list[str] = []
        if not task_matches or not original_matches:
            blocker_codes.append("task_identity_mismatch")
        if not provenance_supplied:
            missing_fields.append("provenance_evidence")
            blocker_codes.append("provenance_missing")
        if not reviewer_supplied:
            missing_fields.append("reviewer_id")
        if not timestamp_supplied:
            missing_fields.append("reviewed_at")
        if not human_approved:
            missing_fields.append("human_review_decision")
            blocker_codes.append("human_review_pending")
        if not manifest.live_eligible:
            blocker_codes.append("fixture_not_live_eligible")
        entries.append(
            _checklist_entry(
                fixture_id=fixture_id,
                task_id=task.task_id,
                task_category=task.category,
                fixture_exists=True,
                task_matches_frozen_dataset=task_matches and original_matches,
                manifest_hash=manifest_sha256(manifest),
                provenance_supplied=provenance_supplied,
                reviewer_supplied=reviewer_supplied,
                review_timestamp_supplied=timestamp_supplied,
                review_status=(
                    "human_approved" if human_approved else "pending"
                ),
                live_eligible=manifest.live_eligible,
                missing_fields=tuple(missing_fields),
                blocker_codes=tuple(blocker_codes),
            )
        )
    return tuple(entries)


def build_intake_report(
    *,
    dataset: BenchmarkDataset,
    manifests: Mapping[str, FixtureManifest] | None = None,
) -> FixtureIntakeReport:
    """Build the deterministic production-study fixture intake report.

    The report audits the 8 frozen tasks, builds the per-fixture
    human fill-in checklist, and reports the overall intake state.
    It never implies the study is ready while human-controlled
    inputs are missing.
    """

    dataset_hash = dataset_sha256(dataset)
    if dataset.name != CANONICAL_DATASET_NAME:
        raise FixtureIntakeError(
            "dataset_name_mismatch",
            f"Production fixtures must bind to the canonical dataset "
            f"{CANONICAL_DATASET_NAME!r}; {dataset.name!r} was supplied",
        )
    inventory = audit_frozen_tasks(dataset)
    checklist = build_fixture_checklist(dataset=dataset, manifests=manifests)
    all_human_reviewed = all(
        entry.review_status == "human_approved" and entry.live_eligible
        for entry in checklist
    )
    all_provenance = all(entry.provenance_supplied for entry in checklist)
    return FixtureIntakeReport(
        dataset_name=dataset.name,
        dataset_sha256=dataset_hash,
        task_count=len(dataset.tasks),
        task_inventory=inventory,
        checklist=checklist,
        genuine_fixture_evidence="supplied" if all_provenance else "pending",
        human_review="complete" if all_human_reviewed else "pending",
        live_eligibility="eligible" if all_human_reviewed else "blocked",
        software_verification_limit=(
            "Software verifies only the presence, shape, and binding of "
            "human-supplied declarations. Authenticity of any reviewer, "
            "issuer, signature, consent, or provenance evidence remains an "
            "unverified claim requiring out-of-band human confirmation; "
            "this report can never authorize live execution."
        ),
    )


def render_intake_report(report: FixtureIntakeReport) -> str:
    """Render the deterministic human-readable intake report.

    The report lists every frozen task/category and its readiness,
    then the overall human-input state. It never implies the study
    is ready while human-controlled inputs are missing.
    """

    lines: list[str] = []
    lines.append("Production Study Fixture Intake")
    lines.append("=" * 40)
    lines.append(
        f"Dataset: {report.dataset_name} ({report.dataset_sha256[:16]}...)"
    )
    lines.append(f"Frozen tasks: {report.task_count}")
    lines.append("")
    lines.append("Frozen task inventory:")
    for index, task in enumerate(report.task_inventory, start=1):
        lines.append(
            f"  {index:02d} {task.task_id} ({task.category}) "
            f"........ READY"
        )
    lines.append("")
    lines.append("Per-fixture human fill-in checklist:")
    for entry in report.checklist:
        state = "ELIGIBLE" if entry.live_eligible else "BLOCKED"
        lines.append(
            f"  {entry.fixture_id} ({entry.task_category}) ........ {state}"
        )
        if entry.missing_fields:
            lines.append(
                f"      missing: {', '.join(entry.missing_fields)}"
            )
        if entry.blocker_codes:
            lines.append(
                f"      blockers: {', '.join(entry.blocker_codes)}"
            )
    lines.append("")
    lines.append("Overall intake state:")
    lines.append(
        f"  Genuine fixture evidence ........ {report.genuine_fixture_evidence.upper()}"
    )
    lines.append(f"  Human review .................... {report.human_review.upper()}")
    lines.append(f"  Live eligibility ................ {report.live_eligibility.upper()}")
    lines.append("")
    lines.append(f"Intake state: {report.state.upper()}")
    lines.append("")
    lines.append(f"Software verification limit: {report.software_verification_limit}")
    return "\n".join(lines)


def write_production_fixture_templates(
    *,
    dataset: BenchmarkDataset,
    output_dir: Path,
) -> tuple[Path, ...]:
    """Write the 8 production fixture templates to ``output_dir``.

    Each template is an intentionally incomplete
    ``experimental_candidate`` fixture with ``pending`` review. The
    templates are versioned, inspectable JSON files that a human
    fills in. No reviewer identity, review timestamp, or fabricated
    provenance evidence is written.
    """

    if not output_dir.is_dir():
        raise FixtureIntakeError(
            "output_dir_missing",
            f"The production-study input directory does not exist: {output_dir}",
        )
    written: list[Path] = []
    for task in dataset.tasks:
        manifest = build_production_fixture_template(task, dataset=dataset)
        payload = json.loads(manifest.model_dump_json())
        manifest_path = output_dir / f"{manifest.fixture_id}.json"
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(manifest_path)
    return tuple(written)


def load_production_fixtures(
    *,
    dataset: BenchmarkDataset,
    fixtures_dir: Path,
) -> dict[str, FixtureManifest]:
    """Load every production fixture template from ``fixtures_dir``.

    Only fixtures whose id matches a frozen task are loaded. A
    missing fixture is simply absent from the returned mapping; the
    checklist reports it as blocked. Malformed fixtures raise
    ``FixtureIntakeError`` so the human can correct them.
    """

    expected_ids = {
        production_fixture_id(task.task_id) for task in dataset.tasks
    }
    loaded: dict[str, FixtureManifest] = {}
    for fixture_id in sorted(expected_ids):
        manifest_path = fixtures_dir / f"{fixture_id}.json"
        if not manifest_path.exists():
            continue
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                manifest = FixtureManifest.model_validate(json.load(handle))
        except (OSError, ValueError) as error:
            raise FixtureIntakeError(
                "fixture_manifest_invalid",
                f"Production fixture {fixture_id} is malformed: {error}",
            ) from error
        if manifest.fixture_id != fixture_id:
            raise FixtureIntakeError(
                "fixture_id_mismatch",
                f"Fixture file {manifest_path.name} declares "
                f"{manifest.fixture_id!r}; expected {fixture_id!r}",
            )
        loaded[fixture_id] = manifest
    return loaded


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def intake_package_sha256(
    report: FixtureIntakeReport,
) -> str:
    """Content-address the intake report."""

    canonical = _canonical_json(json.loads(report.model_dump_json()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
