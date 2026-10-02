"""Offline admission checks for production-benchmark fixtures."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_fixtures import (
    FixtureManifest,
    GapMatchKey,
    Review,
    admit_live_manifest,
    generation_inputs,
    load_fixture_manifest,
    manifest_sha256,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "benchmark_dataset.json"
MANIFEST_PATH = ROOT / "tests/fixtures/production_pipeline/synthetic_manifest.json"


def manifest_data() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def parsed(data: dict[str, object]) -> FixtureManifest:
    return FixtureManifest.model_validate(data)


def test_synthetic_fixture_validates_and_cannot_enter_live_study() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    assert manifest.task_id == "planning-launch-001"
    assert not manifest.live_eligible
    assert manifest.review.reviewer_id is None
    assert len(manifest.project_facts) == 1
    assert len(manifest.clarification_answers) == 1
    assert len(manifest.frozen_documents) == 1
    assert len(manifest_sha256(manifest)) == 64


def test_evaluation_only_never_enters_generation_projection() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    inputs = generation_inputs(manifest, dataset, MANIFEST_PATH)
    projected = inputs.model_dump(mode="json")
    assert set(projected) == {
        "original_task",
        "project_facts",
        "clarification_answers",
        "frozen_documents",
    }
    assert "SYNTHETIC_EVAL_ONLY_MARKER" not in json.dumps(projected)
    assert "SYNTHETIC_EVAL_ONLY_MARKER" in manifest.evaluation_only[0].content
    assert inputs.frozen_documents[0].content.startswith(b"SYNTHETIC TEST DOCUMENT")
    assert inputs.original_task is not manifest.original_task
    assert inputs.project_facts[0] is not manifest.project_facts[0]
    assert inputs.clarification_answers[0] is not manifest.clarification_answers[0]
    assert inputs.frozen_documents[0].provenance is not manifest.frozen_documents[0].provenance


def test_synthetic_manifest_cannot_be_mutated_into_live_eligibility() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    with pytest.raises(ValidationError, match="frozen_instance"):
        manifest.fixture_kind = "experimental_candidate"
    with pytest.raises(ValidationError, match="frozen_instance"):
        manifest.review.status = "human_approved"
    with pytest.raises(ValueError, match="not eligible for live experiments"):
        admit_live_manifest(manifest, dataset, MANIFEST_PATH)

    # Pydantic's model_copy(update=...) skips validation; every admission path checks again.
    forged = manifest.model_copy(
        update={
            "fixture_kind": "experimental_candidate",
            "review": Review(
                status="human_approved",
                reviewer_id="claimed-reviewer",
                reviewed_at="2026-01-01T00:00:00Z",
            ),
        }
    )
    with pytest.raises(ValidationError, match="synthetic test sources"):
        _ = forged.live_eligible
    with pytest.raises(ValidationError, match="synthetic test sources"):
        admit_live_manifest(forged, dataset, MANIFEST_PATH)


def test_changed_original_task_cannot_enter_generation_even_with_matching_text_hash() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    with pytest.raises(ValidationError, match="frozen_instance"):
        manifest.original_task.content = "Changed task"
    changed = manifest.original_task.model_copy(
        update={
            "content": "Changed task",
            "content_sha256": hashlib.sha256(b"Changed task").hexdigest(),
        }
    )
    forged = manifest.model_copy(update={"original_task": changed})
    with pytest.raises(ValueError, match="Original-task content differs"):
        generation_inputs(forged, dataset, MANIFEST_PATH)


def test_nested_collection_changes_are_rejected_before_projection() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    with pytest.raises(ValidationError, match="frozen_instance"):
        manifest.project_facts += manifest.project_facts
    with pytest.raises(ValidationError, match="frozen_instance"):
        manifest.clarification_answers[0].gap_key.dimension = "context"
    forged = manifest.model_copy(
        update={"clarification_answers": manifest.clarification_answers * 2}
    )
    with pytest.raises(ValidationError, match="Fixture source IDs must be unique"):
        generation_inputs(forged, dataset, MANIFEST_PATH)


def test_stale_dataset_identity_cannot_enter_generation() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    forged = manifest.model_copy(update={"dataset_sha256": "0" * 64})
    with pytest.raises(ValueError, match="dataset identity/hash"):
        generation_inputs(forged, dataset, MANIFEST_PATH)
    dataset.task("planning-launch-001").task_text = "Revised dataset task"
    with pytest.raises(ValueError, match="dataset identity/hash"):
        generation_inputs(manifest, dataset, MANIFEST_PATH)


def test_gap_matching_is_exact_and_unmatched_gap_stays_unanswered() -> None:
    manifest = load_fixture_manifest(MANIFEST_PATH, load_dataset(DATASET_PATH))
    match = manifest.answer_for_gap(
        GapMatchKey(dimension="audience", question_target="  Who  is the workshop for? ")
    )
    assert match is not None and match.fixture_id == "synthetic-answer-1"
    assert (
        manifest.answer_for_gap(
            GapMatchKey(dimension="audience", question_target="What is the audience size?")
        )
        is None
    )


def test_ambiguous_normalized_gap_keys_are_rejected() -> None:
    data = manifest_data()
    answers = data["clarification_answers"]
    assert isinstance(answers, list)
    duplicate = copy.deepcopy(answers[0])
    duplicate["fixture_id"] = "synthetic-answer-2"
    duplicate["gap_key"]["question_target"] = "  WHO   is the workshop for?  "
    answers.append(duplicate)
    with pytest.raises(ValidationError, match="Duplicate or ambiguous clarification gap keys"):
        parsed(data)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "v2", "schema_version"),
        ("task_id", "nonexistent-task", "source"),
        ("fixture_kind", "unknown", "fixture_kind"),
    ],
)
def test_invalid_manifest_identity_fields_are_rejected(
    field: str, value: str, message: str
) -> None:
    data = manifest_data()
    data[field] = value
    with pytest.raises(ValidationError, match=message):
        parsed(data)


def test_unknown_task_and_stale_dataset_hash_are_rejected() -> None:
    dataset = load_dataset(DATASET_PATH)
    data = manifest_data()
    data["task_id"] = "unknown-task"
    for source in [
        data["original_task"],
        *data["project_facts"],
        *data["clarification_answers"],
        *data["frozen_documents"],
        *data["evaluation_only"],
    ]:
        source["task_id"] = "unknown-task"
    with pytest.raises(ValueError, match="unknown task_id"):
        validate_manifest(parsed(data), dataset, MANIFEST_PATH)
    data = manifest_data()
    data["dataset_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="dataset identity/hash"):
        validate_manifest(parsed(data), dataset, MANIFEST_PATH)


def test_original_task_must_match_source_dataset() -> None:
    data = manifest_data()
    original = data["original_task"]
    original["content"] = "Changed task"
    original["content_sha256"] = hashlib.sha256(b"Changed task").hexdigest()
    with pytest.raises(ValueError, match="Original-task content differs"):
        validate_manifest(parsed(data), load_dataset(DATASET_PATH), MANIFEST_PATH)


def test_source_type_and_cross_task_references_are_rejected() -> None:
    data = manifest_data()
    data["project_facts"][0]["source_type"] = "evaluation_only"
    with pytest.raises(ValidationError):
        parsed(data)
    data = manifest_data()
    data["project_facts"][0]["task_id"] = "writing-email-001"
    with pytest.raises(ValidationError, match="reference the manifest task_id"):
        parsed(data)


def test_synthetic_fixture_cannot_claim_human_approval() -> None:
    data = manifest_data()
    data["review"] = {
        "status": "human_approved",
        "reviewer_id": "invented-reviewer",
        "reviewed_at": "2026-01-01T00:00:00Z",
    }
    with pytest.raises(ValidationError, match="Synthetic fixtures cannot claim human review"):
        parsed(data)


def test_experimental_review_requires_real_fields_and_excludes_synthetic_sources() -> None:
    data = manifest_data()
    data["fixture_kind"] = "experimental_candidate"
    data["review"] = {"status": "human_approved", "reviewer_id": None, "reviewed_at": None}
    with pytest.raises(ValidationError, match="requires reviewer_id and reviewed_at"):
        parsed(data)
    data["review"] = {
        "status": "human_approved",
        "reviewer_id": "reviewer-record",
        "reviewed_at": "bad-date",
    }
    with pytest.raises(ValidationError, match="reviewed_at"):
        parsed(data)
    data["review"]["reviewed_at"] = "2026-01-01T00:00:00Z"
    with pytest.raises(ValidationError, match="cannot contain synthetic test sources"):
        parsed(data)


@pytest.mark.parametrize("value", [0, 0.0, True, "0", float("nan"), float("inf")])
def test_review_timestamp_rejects_non_iso_scalars(value: object) -> None:
    data = manifest_data()
    data["fixture_kind"] = "experimental_candidate"
    data["project_facts"] = []
    data["clarification_answers"] = []
    data["frozen_documents"] = []
    data["evaluation_only"] = []
    data["review"] = {
        "status": "human_approved",
        "reviewer_id": "unverified-unit-test-reviewer",
        "reviewed_at": value,
    }
    with pytest.raises(ValidationError, match="timezone-aware ISO-8601"):
        parsed(data)


def test_review_timestamp_requires_timezone_and_accepts_trusted_datetime() -> None:
    data = manifest_data()
    data["fixture_kind"] = "experimental_candidate"
    data["project_facts"] = []
    data["clarification_answers"] = []
    data["frozen_documents"] = []
    data["evaluation_only"] = []
    data["review"] = {
        "status": "human_approved",
        "reviewer_id": "unverified-unit-test-reviewer",
        "reviewed_at": "2026-02-01T12:00:00",
    }
    with pytest.raises(ValidationError, match="include a timezone"):
        parsed(data)

    data["review"]["reviewed_at"] = datetime(2026, 2, 1, 12, tzinfo=UTC)
    manifest = parsed(data)
    assert manifest.review.reviewed_at == datetime(2026, 2, 1, 12, tzinfo=UTC)


def test_numeric_review_timestamp_cannot_bypass_validation_with_model_copy() -> None:
    dataset = load_dataset(DATASET_PATH)
    manifest = load_fixture_manifest(MANIFEST_PATH, dataset)
    forged_review = manifest.review.model_copy(update={"reviewed_at": 0})
    forged = manifest.model_copy(update={"review": forged_review})
    with pytest.raises(ValidationError, match="timezone-aware ISO-8601"):
        validate_manifest(forged, dataset, MANIFEST_PATH)


def test_frozen_document_bytes_must_match_checksum(tmp_path: Path) -> None:
    data = manifest_data()
    (tmp_path / "synthetic_manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "synthetic_workshop.txt").write_bytes(b"tampered document")
    with pytest.raises(ValueError, match="content_sha256 does not match"):
        load_fixture_manifest(tmp_path / "synthetic_manifest.json", load_dataset(DATASET_PATH))


def test_document_path_cannot_escape_manifest_directory(tmp_path: Path) -> None:
    data = manifest_data()
    data["frozen_documents"][0]["path"] = "../outside.txt"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="path must stay within"):
        load_fixture_manifest(path, load_dataset(DATASET_PATH))
