"""Fail-closed study-preparation and admission-readiness tests.

These tests verify the preparation milestone only. They never
execute a live study, never contact a provider, and never
manufacture a human decision. Every test uses visibly unverified
human-approval claims that exist only inside the test.

The ``LiveStudyProtocol`` model already enforces several research
invariants at validation time (identical condition parameters,
unique fixture IDs, matching target providers, judge required for
llm_judge, and stratum/fallback consistency). Those invariants are
therefore tested here at the model boundary, while the readiness
report is tested for the decisions that remain human-supplied and
unverified (pricing, budget, authorization, timeout, and fixture
evidence).
"""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_fixtures import (
    FixtureManifest,
    manifest_sha256,
    text_sha256,
)
from promptpilot_backend.benchmark_study_preparation import (
    FROZEN_CALL_CEILING,
    FROZEN_CALL_CEILING_TOTAL,
    FROZEN_REPETITIONS,
    FROZEN_TASK_COUNT,
    FROZEN_UNIT_COUNT,
    StudyPreparationError,
    build_study_configuration,
    evaluate_study_readiness,
    rehearse_study_preparation,
)
from promptpilot_backend.production_benchmark_protocol import LiveStudyProtocol

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmark_dataset.json"
FIXTURES = ROOT / "tests/fixtures/production_pipeline"
PROTOCOL = FIXTURES / "synthetic_protocol.json"


def protocol_data() -> dict:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def production_shape_protocol() -> dict:
    """The frozen production shape: 8 fixtures, R=3, Q=2, llm_judge."""

    data = protocol_data()
    data["study_title"] = "Unverified study-preparation shape test"
    base_selection = data["selected_fixtures"][0]
    selections = []
    for index in range(1, 9):
        selection = copy.deepcopy(base_selection)
        fixture_id = f"unverified-unit-test-task-{index:02d}"
        selection["fixture_id"] = fixture_id
        selection["attestation"]["fixture_id"] = fixture_id
        selections.append(selection)
    data["selected_fixtures"] = selections
    data["repetitions"] = FROZEN_REPETITIONS
    data["question_cap"] = 2
    data["evaluation"] = {"primary": "llm_judge", "secondary": None}
    data["providers"]["judge"] = {"provider": "offline-test", "model": "judge-test-model"}
    data["comparison_policy"]["unmatched_gap"] = "skip"
    data["comparison_policy"]["unanswered_question"] = "skip"
    for key in ("baseline_target_parameters", "promptpilot_target_parameters"):
        data[key]["seed"] = None
        data[key]["max_tokens"] = 300
    return data


def _write_manifest(
    tmp_path: Path, fixture_id: str, task_id: str, original_content: str
) -> tuple[dict, Path, str]:
    manifest_data = json.loads((FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8"))
    manifest_data.update(
        {
            "fixture_id": fixture_id,
            "fixture_kind": "experimental_candidate",
            "review": {
                "status": "human_approved",
                "reviewer_id": "unverified-unit-test-reviewer",
                "reviewed_at": "2026-02-01T12:00:00Z",
            },
            "task_id": task_id,
            "project_facts": [],
            "clarification_answers": [],
            "frozen_documents": [],
            "evaluation_only": [],
        }
    )
    manifest_data["original_task"]["task_id"] = task_id
    manifest_data["original_task"]["content"] = original_content
    manifest_data["original_task"]["content_sha256"] = text_sha256(original_content)
    manifest = FixtureManifest.model_validate(manifest_data)
    manifest_path = tmp_path / f"{fixture_id}.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    return manifest_data, manifest_path, manifest_sha256(manifest)


def _build_study_environment(
    tmp_path: Path,
) -> tuple[LiveStudyProtocol, Path, dict[str, FixtureManifest]]:
    """Build an 8-fixture production-shape protocol with live-eligible manifests."""

    dataset = load_dataset(DATASET)
    data = production_shape_protocol()
    task_ids = [task.task_id for task in dataset.tasks]
    manifests: dict[str, FixtureManifest] = {}
    for index, selection in enumerate(data["selected_fixtures"]):
        fixture_id = selection["fixture_id"]
        task_id = task_ids[index % len(task_ids)]
        original_content = dataset.task(task_id).task_text
        manifest_data, manifest_path, digest = _write_manifest(
            tmp_path, fixture_id, task_id, original_content
        )
        selection["manifest_path"] = manifest_path.name
        selection["manifest_sha256"] = digest
        selection["attestation"]["manifest_sha256"] = digest
        selection["attestation"]["reviewer_id"] = "unverified-unit-test-reviewer"
        selection["attestation"]["reviewed_at"] = "2026-02-01T12:00:00Z"
        selection["attestation"]["test_only"] = False
        manifests[fixture_id] = FixtureManifest.model_validate(manifest_data)
    protocol_path = tmp_path / "study_protocol.json"
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    return LiveStudyProtocol.model_validate(data), protocol_path, manifests


def test_frozen_study_constants_match_the_design() -> None:
    assert FROZEN_TASK_COUNT == 8
    assert FROZEN_REPETITIONS == 3
    assert FROZEN_UNIT_COUNT == 24
    assert FROZEN_CALL_CEILING == {
        "analysis": 24,
        "question_generation": 48,
        "prompt_generation": 24,
        "target_execution": 48,
        "judge": 24,
    }
    assert FROZEN_CALL_CEILING_TOTAL == 168


def test_readiness_is_blocked_without_human_decisions(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    report = evaluate_study_readiness(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert report.state == "blocked"
    assert report.technical_ready is False
    assert report.human_approval is False
    assert report.authorized is False
    assert report.live_execution_ready is False
    assert report.ready is False
    blocker_codes = {blocker.code for blocker in report.blockers}
    assert "pricing_snapshot_missing" in blocker_codes
    assert "monetary_budget_missing" in blocker_codes
    assert "launch_authorization_absent" in blocker_codes


def test_readiness_requires_explicit_timeout_decision(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    report = evaluate_study_readiness(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=None,
    )
    assert any(blocker.code == "target_timeout_missing" for blocker in report.blockers)
    assert any(check.name == "timeout_chosen" and not check.ready for check in report.checks)


def test_readiness_rejects_nonpositive_timeout(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    report = evaluate_study_readiness(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=0,
    )
    assert any(blocker.code == "target_timeout_invalid" for blocker in report.blockers)


def test_model_rejects_missing_max_tokens() -> None:
    data = production_shape_protocol()
    for key in ("baseline_target_parameters", "promptpilot_target_parameters"):
        data[key]["max_tokens"] = 0
    with pytest.raises(ValidationError):
        LiveStudyProtocol.model_validate(data)


def test_model_rejects_non_frozen_temperature() -> None:
    data = production_shape_protocol()
    for key in ("baseline_target_parameters", "promptpilot_target_parameters"):
        data[key]["temperature"] = 0.7
    protocol = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=Path("unused"),
        manifests={},
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "target_temperature_not_frozen" for blocker in report.blockers)


def test_model_rejects_divergent_condition_parameters() -> None:
    data = production_shape_protocol()
    data["promptpilot_target_parameters"]["max_tokens"] = 400
    with pytest.raises(ValidationError, match="target parameters must match"):
        LiveStudyProtocol.model_validate(data)


def test_model_rejects_divergent_target_providers() -> None:
    data = production_shape_protocol()
    data["providers"]["promptpilot_target"] = {
        "provider": "offline-test",
        "model": "different-model",
    }
    with pytest.raises(ValidationError, match="target provider/model must match"):
        LiveStudyProtocol.model_validate(data)


def test_model_rejects_duplicate_fixture_ids() -> None:
    data = production_shape_protocol()
    data["selected_fixtures"][1]["fixture_id"] = data["selected_fixtures"][0]["fixture_id"]
    data["selected_fixtures"][1]["attestation"]["fixture_id"] = (
        data["selected_fixtures"][0]["fixture_id"]
    )
    with pytest.raises(ValidationError, match="unique"):
        LiveStudyProtocol.model_validate(data)


def test_model_rejects_missing_judge_assignment() -> None:
    data = production_shape_protocol()
    data["providers"]["judge"] = None
    with pytest.raises(ValidationError, match="judge provider/model"):
        LiveStudyProtocol.model_validate(data)


def test_model_rejects_secondary_evaluator_equal_to_primary() -> None:
    data = production_shape_protocol()
    data["evaluation"] = {"primary": "llm_judge", "secondary": "llm_judge"}
    with pytest.raises(ValidationError, match="differ from primary"):
        LiveStudyProtocol.model_validate(data)


def test_readiness_rejects_wrong_fixture_count(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["selected_fixtures"] = data["selected_fixtures"][:7]
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    shortened = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=shortened,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "fixture_count_not_eight" for blocker in report.blockers)


def test_readiness_rejects_non_frozen_repetitions(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["repetitions"] = 2
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    changed = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=changed,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "repetition_count_not_frozen" for blocker in report.blockers)


def test_readiness_rejects_non_frozen_question_cap(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["question_cap"] = 3
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    changed = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=changed,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "question_cap_not_frozen" for blocker in report.blockers)


def test_readiness_rejects_non_skip_policies(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["comparison_policy"]["unmatched_gap"] = "stop"
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    changed = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=changed,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "skip_policy_not_frozen" for blocker in report.blockers)


def test_readiness_rejects_separate_stratum_fallback(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["comparison_policy"]["fallback_admission"] = "admit_separate_stratum"
    data["analysis_stratum"] = {
        "name": "hybrid_product_behavior",
        "fallback_containing_runs_admissible": True,
    }
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    changed = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=changed,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "fallback_policy_not_frozen" for blocker in report.blockers)


def test_readiness_rejects_secondary_evaluator(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["evaluation"] = {"primary": "llm_judge", "secondary": "heuristic"}
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    changed = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=changed,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "evaluation_plan_not_frozen" for blocker in report.blockers)


def test_readiness_rejects_unlocked_protocol(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["review"] = {"status": "pending", "reviewer_id": None, "locked_at": None}
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    unlocked = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=unlocked,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "protocol_not_locked" for blocker in report.blockers)
    assert any(check.name == "protocol_locked" and not check.ready for check in report.checks)


def test_readiness_rejects_dataset_identity_mismatch(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["dataset_sha256"] = "0" * 64
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    mismatched = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=mismatched,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "dataset_identity_mismatch" for blocker in report.blockers)


def test_readiness_flags_stale_fixture_hash(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    stale_hash = "0" * 64
    data["selected_fixtures"][0]["manifest_sha256"] = stale_hash
    data["selected_fixtures"][0]["attestation"]["manifest_sha256"] = stale_hash
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    stale = LiveStudyProtocol.model_validate(data)
    report = evaluate_study_readiness(
        protocol=stale,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "fixture_hash_mismatch" for blocker in report.blockers)


def test_readiness_flags_missing_manifest(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    trimmed = {
        key: value
        for key, value in manifests.items()
        if key != protocol.selected_fixtures[0].fixture_id
    }
    report = evaluate_study_readiness(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=trimmed,
        target_timeout_seconds=30.0,
    )
    assert any(blocker.code == "fixture_manifest_missing" for blocker in report.blockers)


def test_build_study_configuration_binds_every_frozen_decision(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    configuration = build_study_configuration(
        protocol,
        load_dataset(DATASET),
        manifests,
        protocol_path=protocol_path,
        target_timeout_seconds=30.0,
    )
    assert len(configuration.fixture_ids) == FROZEN_TASK_COUNT
    assert len(set(configuration.fixture_ids)) == FROZEN_TASK_COUNT
    assert len(configuration.fixture_sha256) == FROZEN_TASK_COUNT
    assert configuration.repetitions == FROZEN_REPETITIONS
    assert configuration.question_cap == 2
    assert configuration.call_ceiling == FROZEN_CALL_CEILING
    assert configuration.call_ceiling_total == FROZEN_CALL_CEILING_TOTAL
    assert configuration.rubric_version == "v1"
    assert configuration.evaluator == {"primary": "llm_judge", "secondary": None}
    assert configuration.skip_policies == {
        "unmatched_gap": "skip",
        "unanswered_question": "skip",
    }
    assert configuration.fallback_policy == "reject"
    assert configuration.target_parameters["temperature"] == 0
    assert configuration.target_parameters["top_p"] == 1.0
    assert configuration.target_parameters["stop"] == []
    assert configuration.target_parameters["presence_penalty"] == 0
    assert configuration.target_parameters["frequency_penalty"] == 0
    assert configuration.target_parameters["seed"] is None
    assert configuration.target_parameters["max_tokens"] == 300
    assert configuration.target_timeout_seconds == 30.0
    assert configuration.condition_order == [
        ["baseline", "promptpilot"],
        ["promptpilot", "baseline"],
        ["baseline", "promptpilot"],
    ]
    assert configuration.configuration_sha256
    assert configuration.protocol_sha256
    assert configuration.dataset_sha256


def test_build_study_configuration_rejects_wrong_fixture_count(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    data = json.loads(protocol_path.read_text(encoding="utf-8"))
    data["selected_fixtures"] = data["selected_fixtures"][:7]
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    shortened = LiveStudyProtocol.model_validate(data)
    with pytest.raises(StudyPreparationError) as excinfo:
        build_study_configuration(
            shortened,
            load_dataset(DATASET),
            manifests,
            protocol_path=protocol_path,
            target_timeout_seconds=30.0,
        )
    assert excinfo.value.code == "fixture_count_not_eight"


def test_build_study_configuration_rejects_missing_timeout(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    with pytest.raises(StudyPreparationError) as excinfo:
        build_study_configuration(
            protocol,
            load_dataset(DATASET),
            manifests,
            protocol_path=protocol_path,
            target_timeout_seconds=None,
        )
    assert excinfo.value.code == "target_timeout_missing"


def test_build_study_configuration_rejects_nonpositive_timeout(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    with pytest.raises(StudyPreparationError) as excinfo:
        build_study_configuration(
            protocol,
            load_dataset(DATASET),
            manifests,
            protocol_path=protocol_path,
            target_timeout_seconds=0,
        )
    assert excinfo.value.code == "target_timeout_invalid"


def test_rehearsal_is_offline_and_zero_cost(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    rehearsal = rehearse_study_preparation(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert rehearsal["rehearsal_mode"] == "offline_dry_run"
    assert rehearsal["network_calls"] == 0
    assert rehearsal["live_provider_calls"] == 0
    assert rehearsal["cost"] == 0
    assert rehearsal["live_eligible_fixtures_produced"] == 0
    assert rehearsal["human_approvals_created"] == 0
    assert rehearsal["call_ceiling"]["total"] == FROZEN_CALL_CEILING_TOTAL
    assert rehearsal["call_ceiling"]["fixture_count"] == FROZEN_TASK_COUNT
    assert rehearsal["call_ceiling"]["unit_count"] == FROZEN_UNIT_COUNT
    assert rehearsal["configuration_sha256"]
    assert rehearsal["readiness_state"] == "blocked"
    assert rehearsal["readiness_technical_ready"] is False


def test_rehearsal_plan_matches_frozen_shape(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    rehearsal = rehearse_study_preparation(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    plan = rehearsal["plan"]
    assert plan["task_count"] == FROZEN_TASK_COUNT
    assert plan["repetitions"] == FROZEN_REPETITIONS
    assert plan["question_cap"] == 2
    assert plan["judge_enabled"] is True


def test_readiness_report_separates_technical_from_human_state(tmp_path: Path) -> None:
    protocol, protocol_path, manifests = _build_study_environment(tmp_path)
    report = evaluate_study_readiness(
        protocol=protocol,
        dataset=load_dataset(DATASET),
        protocol_path=protocol_path,
        manifests=manifests,
        target_timeout_seconds=30.0,
    )
    assert report.software_verification_limit
    assert "never authorize live execution" in report.software_verification_limit
    assert "unverified claim" in report.software_verification_limit
    check_names = {check.name for check in report.checks}
    assert "protocol_locked" in check_names
    assert "dataset_locked" in check_names
    assert "exactly_eight_eligible_fixtures" in check_names
    assert "all_fixture_hashes_current" in check_names
    assert "all_required_review_evidence_present" in check_names
    assert "target_parameters_identical" in check_names
    assert "max_tokens_chosen" in check_names
    assert "timeout_chosen" in check_names
    assert "provider_and_model_selected" in check_names
    assert "pricing_snapshot_verified" in check_names
    assert "budget_configured" in check_names
    assert "currency_configured" in check_names
    assert "provider_authorization_supplied" in check_names
    assert "spending_authorization_supplied" in check_names
    assert "external_human_authorization_supplied" in check_names
    assert "technical_admission_ready" in check_names
    assert "launch_gate_capable_of_passing" in check_names
