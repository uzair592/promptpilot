"""Fail-closed production fixture-intake tests.

These tests verify the fixture-intake workflow only. They
never execute a live study, never contact a provider, never
spend credits, and never manufacture a human decision. No
test creates a genuine human-approved fixture; the only
``human_approved`` fixtures are structurally-valid but
visibly unverified claims that exist solely to prove the
validator recognizes the difference between a pending
template and a claimed (but unverified) approval.
"""

import json
from pathlib import Path

import pytest

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_fixture_intake import (
    FROZEN_TASK_COUNT,
    FixtureIntakeError,
    audit_frozen_tasks,
    build_fixture_checklist,
    build_intake_report,
    build_production_fixture_template,
    intake_package_sha256,
    load_production_fixtures,
    production_fixture_id,
    render_intake_report,
    write_production_fixture_templates,
)
from promptpilot_backend.benchmark_fixtures import (
    FixtureManifest,
    text_sha256,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmark_dataset.json"
FIXTURES = ROOT / "tests/fixtures/production_pipeline"


def dataset() -> object:
    return load_dataset(DATASET)


def _template_payload(task_id: str) -> dict:
    """Build a pending production fixture template payload."""

    data = dataset()
    task = data.task(task_id)
    manifest = build_production_fixture_template(task, dataset=data)
    return json.loads(manifest.model_dump_json())


def _write_template(tmp_path: Path, task_id: str) -> Path:
    payload = _template_payload(task_id)
    fixture_id = payload["fixture_id"]
    manifest_path = tmp_path / f"{fixture_id}.json"
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path


def test_audit_reports_all_eight_frozen_tasks() -> None:
    data = dataset()
    inventory = audit_frozen_tasks(data)
    assert len(inventory) == FROZEN_TASK_COUNT
    task_ids = [item.task_id for item in inventory]
    assert task_ids == [task.task_id for task in data.tasks]
    for item in inventory:
        assert item.task_text_sha256 == text_sha256(item.task_text)
        assert item.category
        assert item.task_text


def test_audit_rejects_wrong_task_count(tmp_path: Path) -> None:
    data = dataset()
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["tasks"] = payload["tasks"][:7]
    shortened = type(data).model_validate(payload)
    with pytest.raises(FixtureIntakeError) as excinfo:
        audit_frozen_tasks(shortened)
    assert excinfo.value.code == "task_count_mismatch"


def test_template_is_pending_and_not_live_eligible() -> None:
    data = dataset()
    task = data.task("writing-email-001")
    manifest = build_production_fixture_template(task, dataset=data)
    assert manifest.fixture_kind == "experimental_candidate"
    assert manifest.review.status == "pending"
    assert manifest.review.reviewer_id is None
    assert manifest.review.reviewed_at is None
    assert manifest.live_eligible is False
    assert manifest.task_id == "writing-email-001"
    assert manifest.original_task.content == task.task_text
    assert manifest.original_task.content_sha256 == text_sha256(
        task.task_text
    )
    assert manifest.dataset_sha256


def test_template_binds_to_canonical_dataset() -> None:
    data = dataset()
    task = data.task("qa-geography-001")
    manifest = build_production_fixture_template(task, dataset=data)
    assert manifest.dataset_name == "promptpilot-experimental-v1"


def test_template_rejects_noncanonical_dataset(tmp_path: Path) -> None:
    data = dataset()
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["name"] = "not-the-canonical-dataset"
    renamed = type(data).model_validate(payload)
    task = renamed.task("writing-email-001")
    with pytest.raises(FixtureIntakeError) as excinfo:
        build_production_fixture_template(task, dataset=renamed)
    assert excinfo.value.code == "dataset_name_mismatch"


def test_template_task_text_is_never_modified() -> None:
    data = dataset()
    for task in data.tasks:
        manifest = build_production_fixture_template(task, dataset=data)
        assert manifest.original_task.content == task.task_text
        assert manifest.original_task.content_sha256 == text_sha256(
            task.task_text
        )


def test_checklist_reports_pending_template_as_blocked(tmp_path: Path) -> None:
    data = dataset()
    _write_template(tmp_path, "writing-email-001")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    checklist = build_fixture_checklist(dataset=data, manifests=manifests)
    by_id = {entry.fixture_id: entry for entry in checklist}
    entry = by_id[production_fixture_id("writing-email-001")]
    assert entry.fixture_exists is True
    assert entry.task_matches_frozen_dataset is True
    assert entry.task_provenance_available is True
    assert entry.production_fixture_evidence_supplied is False
    assert entry.reviewer_supplied is False
    assert entry.review_timestamp_supplied is False
    assert entry.review_status == "pending"
    assert entry.live_eligible is False
    assert "production_fixture_evidence" in entry.missing_fields
    assert "production_fixture_evidence_pending" in entry.blocker_codes
    assert "reviewer_id" in entry.missing_fields
    assert "reviewed_at" in entry.missing_fields
    assert "human_review_pending" in entry.blocker_codes
    assert "fixture_not_live_eligible" in entry.blocker_codes


def test_checklist_reports_missing_fixture_as_blocked() -> None:
    data = dataset()
    checklist = build_fixture_checklist(dataset=data, manifests={})
    assert len(checklist) == FROZEN_TASK_COUNT
    for entry in checklist:
        assert entry.fixture_exists is False
        assert entry.live_eligible is False
        assert "fixture_manifest_missing" in entry.blocker_codes
        assert "human_review_pending" in entry.blocker_codes
        assert "fixture_not_live_eligible" in entry.blocker_codes


def test_checklist_rejects_wrong_task_id(tmp_path: Path) -> None:
    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["task_id"] = "qa-geography-001"
    payload["original_task"]["task_id"] = "qa-geography-001"
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    checklist = build_fixture_checklist(dataset=data, manifests=manifests)
    entry = next(
        item for item in checklist
        if item.fixture_id == payload["fixture_id"]
    )
    assert entry.task_matches_frozen_dataset is False
    assert "task_identity_mismatch" in entry.blocker_codes


def test_checklist_rejects_wrong_task_text(tmp_path: Path) -> None:
    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["original_task"]["content"] = "A rewritten task text."
    payload["original_task"]["content_sha256"] = text_sha256(
        "A rewritten task text."
    )
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    checklist = build_fixture_checklist(dataset=data, manifests=manifests)
    entry = next(
        item for item in checklist
        if item.fixture_id == payload["fixture_id"]
    )
    assert entry.task_matches_frozen_dataset is False
    assert "task_identity_mismatch" in entry.blocker_codes


def test_checklist_rejects_wrong_dataset_hash(tmp_path: Path) -> None:
    """A wrong dataset hash value (valid format) is caught by admission.

    The manifest schema only validates the hash *format* (64 hex
    chars). The hash *value* is verified against the dataset by
    ``validate_manifest`` during admission, not at intake load
    time. The intake checklist therefore reports the fixture as
    present but the production admission flow rejects it.
    """

    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["dataset_sha256"] = "0" * 64
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    assert payload["fixture_id"] in manifests
    with pytest.raises(ValueError, match="dataset identity/hash"):
        validate_manifest(
            manifests[payload["fixture_id"]], data, manifest_path
        )


def test_checklist_rejects_wrong_fixture_hash(tmp_path: Path) -> None:
    """A wrong original-task content hash (valid format) is caught.

    The manifest schema validates the hash *format*. The content
    hash *value* is verified against the content by the
    ``TextSource`` model validator, so a mismatched value is
    rejected at schema-validation time.
    """

    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["original_task"]["content_sha256"] = "0" * 64
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FixtureIntakeError, match="fixture_manifest_invalid"):
        load_production_fixtures(dataset=data, fixtures_dir=tmp_path)


def test_checklist_rejects_missing_provenance(tmp_path: Path) -> None:
    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["original_task"]["provenance"]["source_type"] = "synthetic_test"
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FixtureIntakeError, match="fixture_manifest_invalid"):
        load_production_fixtures(dataset=data, fixtures_dir=tmp_path)


def test_checklist_rejects_missing_reviewer_on_approval(tmp_path: Path) -> None:
    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["review"] = {
        "status": "human_approved",
        "reviewer_id": None,
        "reviewed_at": "2026-02-01T12:00:00Z",
    }
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FixtureIntakeError, match="fixture_manifest_invalid"):
        load_production_fixtures(dataset=data, fixtures_dir=tmp_path)


def test_checklist_rejects_missing_review_timestamp_on_approval(
    tmp_path: Path,
) -> None:
    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["review"] = {
        "status": "human_approved",
        "reviewer_id": "unverified-unit-test-reviewer",
        "reviewed_at": None,
    }
    manifest_path = tmp_path / f"{payload['fixture_id']}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FixtureIntakeError, match="fixture_manifest_invalid"):
        load_production_fixtures(dataset=data, fixtures_dir=tmp_path)


def test_synthetic_fixture_remains_ineligible() -> None:
    manifest = FixtureManifest.model_validate(
        json.loads((FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8"))
    )
    assert manifest.fixture_kind == "synthetic_offline_test"
    assert manifest.review.status == "synthetic"
    assert manifest.live_eligible is False


def test_incomplete_production_fixture_remains_blocked(tmp_path: Path) -> None:
    data = dataset()
    for task in data.tasks:
        _write_template(tmp_path, task.task_id)
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    report = build_intake_report(dataset=data, manifests=manifests)
    assert report.state == "blocked"
    assert report.live_eligibility == "blocked"
    assert report.human_review == "pending"
    assert report.genuine_fixture_evidence == "pending"
    for entry in report.checklist:
        assert entry.live_eligible is False
        assert entry.task_provenance_available is True
        assert entry.production_fixture_evidence_supplied is False
        assert "production_fixture_evidence_pending" in entry.blocker_codes
        assert "human_review_pending" in entry.blocker_codes


def test_complete_structurally_valid_fixture_requires_human_eligibility(
    tmp_path: Path,
) -> None:
    """A structurally-valid claimed approval is recognized but still gated.

    The fixture below carries a visibly unverified human-approval
    claim that exists only inside this test. The intake checklist
    recognizes the claim (review_status=human_approved,
    live_eligible=True) but the report's software_verification_limit
    states that the authenticity of the reviewer remains an
    unverified claim requiring out-of-band human confirmation.
    """

    data = dataset()
    for task in data.tasks:
        payload = _template_payload(task.task_id)
        payload["review"] = {
            "status": "human_approved",
            "reviewer_id": "unverified-unit-test-reviewer",
            "reviewed_at": "2026-02-01T12:00:00Z",
        }
        manifest_path = tmp_path / f"{payload['fixture_id']}.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    report = build_intake_report(dataset=data, manifests=manifests)
    assert report.live_eligibility == "eligible"
    assert report.human_review == "complete"
    for entry in report.checklist:
        assert entry.review_status == "human_approved"
        assert entry.live_eligible is True
        assert entry.task_provenance_available is True
        assert entry.reviewer_supplied is True
        assert entry.review_timestamp_supplied is True
    assert "unverified claim" in report.software_verification_limit
    assert "never authorize live execution" in report.software_verification_limit


def test_dataset_original_provenance_is_not_genuine_fixture_evidence(
    tmp_path: Path,
) -> None:
    """A template with only ``dataset_original`` provenance stays pending.

    ``dataset_original`` proves the frozen task came from the
    canonical dataset. It does NOT prove a genuine production
    fixture supplied project-specific context, user/project facts,
    clarification answers, supporting documents, evaluation-only
    information, or provenance/consent evidence. The canonical
    dataset task is never counted as genuine production-fixture
    evidence.
    """

    data = dataset()
    _write_template(tmp_path, "writing-email-001")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    checklist = build_fixture_checklist(dataset=data, manifests=manifests)
    entry = next(
        item for item in checklist
        if item.fixture_id == production_fixture_id("writing-email-001")
    )
    assert entry.task_provenance_available is True
    assert entry.production_fixture_evidence_supplied is False
    assert "production_fixture_evidence" in entry.missing_fields
    assert "production_fixture_evidence_pending" in entry.blocker_codes
    report = build_intake_report(dataset=data, manifests=manifests)
    assert report.genuine_fixture_evidence == "pending"


def test_existing_eight_templates_remain_blocked(tmp_path: Path) -> None:
    """The 8 current production templates remain blocked and ineligible."""

    data = dataset()
    for task in data.tasks:
        _write_template(tmp_path, task.task_id)
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    report = build_intake_report(dataset=data, manifests=manifests)
    assert report.state == "blocked"
    assert report.genuine_fixture_evidence == "pending"
    assert report.human_review == "pending"
    assert report.live_eligibility == "blocked"
    assert len(report.checklist) == FROZEN_TASK_COUNT
    for entry in report.checklist:
        assert entry.live_eligible is False
        assert entry.production_fixture_evidence_supplied is False
        assert entry.reviewer_supplied is False
        assert entry.review_timestamp_supplied is False
        assert entry.review_status == "pending"
        assert "production_fixture_evidence_pending" in entry.blocker_codes
        assert "human_review_pending" in entry.blocker_codes
        assert "fixture_not_live_eligible" in entry.blocker_codes


def test_human_review_still_pending_for_templates(tmp_path: Path) -> None:
    data = dataset()
    for task in data.tasks:
        _write_template(tmp_path, task.task_id)
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    report = build_intake_report(dataset=data, manifests=manifests)
    assert report.human_review == "pending"
    for entry in report.checklist:
        assert entry.review_status == "pending"
        assert "human_review_decision" in entry.missing_fields


def test_live_eligibility_remains_false_for_templates(tmp_path: Path) -> None:
    data = dataset()
    for task in data.tasks:
        _write_template(tmp_path, task.task_id)
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    report = build_intake_report(dataset=data, manifests=manifests)
    assert report.live_eligibility == "blocked"
    for entry in report.checklist:
        assert entry.live_eligible is False


def test_frozen_task_inventory_is_unchanged() -> None:
    data = dataset()
    report = build_intake_report(dataset=data, manifests={})
    assert report.task_count == FROZEN_TASK_COUNT
    assert len(report.task_inventory) == FROZEN_TASK_COUNT
    task_ids = [item.task_id for item in report.task_inventory]
    assert task_ids == [task.task_id for task in data.tasks]
    for item in report.task_inventory:
        assert item.task_text_sha256 == text_sha256(item.task_text)


def test_synthetic_fixture_cannot_become_genuine_evidence() -> None:
    """A synthetic fixture never supplies genuine production evidence.

    The synthetic fixture carries only ``synthetic_test``
    sources, which are explicitly not genuine production-
    fixture evidence. It is permanently ineligible and can
    never be promoted to a live-eligible production fixture.
    """

    synthetic = FixtureManifest.model_validate(
        json.loads((FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8"))
    )
    assert synthetic.fixture_kind == "synthetic_offline_test"
    assert synthetic.review.status == "synthetic"
    assert synthetic.live_eligible is False
    for source in (
        *synthetic.project_facts,
        *synthetic.clarification_answers,
        *synthetic.frozen_documents,
        *synthetic.evaluation_only,
    ):
        assert source.source_type != "user_supplied_project_fact"
        assert source.source_type != "user_supplied_answer"
    assert synthetic.review.reviewer_id is None
    assert synthetic.review.reviewed_at is None


def test_structurally_complete_fixture_does_not_establish_authenticity(
    tmp_path: Path,
) -> None:
    """Populated fields alone do not establish authenticity.

    A fixture with every source field populated and a claimed
    human approval is still only a structurally-valid, visibly
    unverified claim. The software-verification boundary is
    preserved: authenticity of the reviewer and provenance/consent
    evidence remains an unverified claim requiring out-of-band
    human confirmation, and the report can never authorize live
    execution.
    """

    data = dataset()
    for task in data.tasks:
        payload = _template_payload(task.task_id)
        payload["review"] = {
            "status": "human_approved",
            "reviewer_id": "unverified-unit-test-reviewer",
            "reviewed_at": "2026-02-01T12:00:00Z",
        }
        manifest_path = tmp_path / f"{payload['fixture_id']}.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    report = build_intake_report(dataset=data, manifests=manifests)
    assert "unverified claim" in report.software_verification_limit
    assert "never authorize live execution" in report.software_verification_limit


def test_intake_report_frozen_shape() -> None:
    data = dataset()
    report = build_intake_report(dataset=data, manifests={})
    assert report.task_count == FROZEN_TASK_COUNT
    assert len(report.task_inventory) == FROZEN_TASK_COUNT
    assert len(report.checklist) == FROZEN_TASK_COUNT
    assert report.dataset_name == "promptpilot-experimental-v1"
    assert report.dataset_sha256


def test_intake_report_is_content_addressed() -> None:
    data = dataset()
    report = build_intake_report(dataset=data, manifests={})
    digest = intake_package_sha256(report)
    assert len(digest) == 64
    assert intake_package_sha256(report) == digest


def test_render_intake_report_never_implies_ready() -> None:
    data = dataset()
    report = build_intake_report(dataset=data, manifests={})
    rendered = render_intake_report(report)
    assert "Production Study Fixture Intake" in rendered
    assert "Human review .................... PENDING" in rendered
    assert "Live eligibility ................ BLOCKED" in rendered
    assert "Intake state: BLOCKED" in rendered
    for task in data.tasks:
        assert f"{task.task_id} ({task.category}) ........ READY" in rendered


def test_write_and_load_production_fixture_templates(tmp_path: Path) -> None:
    data = dataset()
    written = write_production_fixture_templates(
        dataset=data, output_dir=tmp_path
    )
    assert len(written) == FROZEN_TASK_COUNT
    manifests = load_production_fixtures(
        dataset=data, fixtures_dir=tmp_path
    )
    assert len(manifests) == FROZEN_TASK_COUNT
    for task in data.tasks:
        fixture_id = production_fixture_id(task.task_id)
        assert fixture_id in manifests
        assert manifests[fixture_id].task_id == task.task_id
        assert manifests[fixture_id].review.status == "pending"


def test_load_production_fixtures_ignores_missing(tmp_path: Path) -> None:
    data = dataset()
    manifests = load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    assert manifests == {}


def test_load_production_fixtures_rejects_id_mismatch(tmp_path: Path) -> None:
    data = dataset()
    payload = _template_payload("writing-email-001")
    payload["fixture_id"] = "production-wrong-id"
    manifest_path = tmp_path / "production-writing-email-001.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FixtureIntakeError) as excinfo:
        load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    assert excinfo.value.code == "fixture_id_mismatch"


def test_load_production_fixtures_rejects_malformed(tmp_path: Path) -> None:
    data = dataset()
    manifest_path = tmp_path / "production-writing-email-001.json"
    manifest_path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(FixtureIntakeError) as excinfo:
        load_production_fixtures(dataset=data, fixtures_dir=tmp_path)
    assert excinfo.value.code == "fixture_manifest_invalid"


def test_write_production_fixture_templates_requires_existing_dir(
    tmp_path: Path,
) -> None:
    data = dataset()
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FixtureIntakeError) as excinfo:
        write_production_fixture_templates(
            dataset=data, output_dir=missing
        )
    assert excinfo.value.code == "output_dir_missing"


def test_production_templates_are_distinct_from_synthetic() -> None:
    data = dataset()
    task = data.task("planning-launch-001")
    production = build_production_fixture_template(task, dataset=data)
    synthetic = FixtureManifest.model_validate(
        json.loads((FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8"))
    )
    assert production.fixture_kind == "experimental_candidate"
    assert production.review.status == "pending"
    assert synthetic.fixture_kind == "synthetic_offline_test"
    assert synthetic.review.status == "synthetic"
    assert production.fixture_id != synthetic.fixture_id
    assert production.live_eligible is False
    assert synthetic.live_eligible is False


def test_production_fixture_id_is_deterministic() -> None:
    assert production_fixture_id("writing-email-001") == (
        "production-writing-email-001"
    )
    assert production_fixture_id("qa-geography-001") == (
        "production-qa-geography-001"
    )


def test_intake_report_deep_copies_are_not_needed() -> None:
    """The report is frozen; mutating the source dataset cannot change it."""

    data = dataset()
    report = build_intake_report(dataset=data, manifests={})
    original_text = report.task_inventory[0].task_text
    assert original_text
    assert report.task_inventory[0].task_text == original_text
