"""Fail-closed admission tests for the future live-study protocol."""

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_fixtures import FixtureManifest, manifest_sha256
from promptpilot_backend.production_benchmark_protocol import (
    AdmissionReport,
    LiveStudyProtocol,
    _write_reserved,
    admit_protocol,
    calculate_call_ceiling,
    main,
    protocol_sha256,
    validate_to_report,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmark_dataset.json"
FIXTURES = ROOT / "tests/fixtures/production_pipeline"
PROTOCOL = FIXTURES / "synthetic_protocol.json"


def protocol_data() -> dict[str, object]:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def parsed(data: dict[str, object] | None = None) -> LiveStudyProtocol:
    return LiveStudyProtocol.model_validate(data or protocol_data())


def positive_protocol(tmp_path: Path) -> tuple[LiveStudyProtocol, Path, str]:
    """Build visibly unverified human-approval claims only inside a temporary test."""

    fixture_id = "unverified-unit-test-candidate-v1"
    reviewer_id = "unverified-unit-test-reviewer"
    reviewed_at = "2026-02-01T12:00:00Z"
    manifest_data = json.loads(
        (FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8")
    )
    manifest_data.update(
        {
            "fixture_id": fixture_id,
            "fixture_kind": "experimental_candidate",
            "review": {
                "status": "human_approved",
                "reviewer_id": reviewer_id,
                "reviewed_at": reviewed_at,
            },
            "project_facts": [],
            "clarification_answers": [],
            "frozen_documents": [],
            "evaluation_only": [],
        }
    )
    manifest = FixtureManifest.model_validate(manifest_data)
    manifest_path = tmp_path / "unverified_unit_test_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    digest = manifest_sha256(manifest)

    data = protocol_data()
    data["study_title"] = "Unverified unit-test technical admission"
    selection = data["selected_fixtures"][0]
    selection.update(
        {
            "fixture_id": fixture_id,
            "manifest_path": manifest_path.name,
            "manifest_sha256": digest,
            "attestation": {
                "attestation_version": "v1",
                "fixture_id": fixture_id,
                "manifest_sha256": digest,
                "reviewer_id": reviewer_id,
                "reviewed_at": reviewed_at,
                "provenance_consent_evidence_reference": (
                    "unverified-unit-test://evidence-claim"
                ),
                "test_only": False,
            },
        }
    )
    protocol_path = tmp_path / "unverified_unit_test_protocol.json"
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    return parsed(data), protocol_path, fixture_id


def test_synthetic_fixture_keeps_independent_regression_policies() -> None:
    """The synthetic fixture is an offline regression artifact, not the production study.

    Its clarification policies deliberately differ from the frozen production
    protocol (skip) so the two declarations cannot drift into each other.
    """

    policy = parsed().comparison_policy
    assert policy.unmatched_gap == "stop"
    assert policy.unanswered_question == "stop"
    assert policy.fallback_admission == "reject"
    assert policy.baseline_input == "exact_original_task"
    assert policy.execution_order == "alternating_paired"
    assert policy.unit_isolation == "task_repetition"
    assert policy.incomplete_pair_evaluation == "prohibited"


def test_skip_policies_remain_admissible_for_the_production_declaration() -> None:
    data = protocol_data()
    data["comparison_policy"]["unmatched_gap"] = "skip"
    data["comparison_policy"]["unanswered_question"] = "skip"
    policy = parsed(data).comparison_policy
    assert policy.unmatched_gap == "skip"
    assert policy.unanswered_question == "skip"


def production_shape_protocol() -> dict[str, object]:
    """Build the frozen production_pipeline_paired_v1 shape (F=8, R=3, Q=2, J=1)."""

    data = protocol_data()
    data["study_title"] = "Unverified production-shape budget test"
    base_selection = data["selected_fixtures"][0]
    selections = []
    for index in range(1, 9):
        selection = copy.deepcopy(base_selection)
        fixture_id = f"unverified-unit-test-task-{index:02d}"
        selection["fixture_id"] = fixture_id
        selection["attestation"]["fixture_id"] = fixture_id
        selections.append(selection)
    data["selected_fixtures"] = selections
    data["repetitions"] = 3
    data["question_cap"] = 2
    data["evaluation"] = {"primary": "llm_judge", "secondary": None}
    data["providers"]["judge"] = {"provider": "offline-test", "model": "judge-test-model"}
    return data


def test_production_paired_call_budget_is_exactly_168_with_no_hidden_calls() -> None:
    ceiling = calculate_call_ceiling(parsed(production_shape_protocol()))
    assert ceiling.fixture_count == 8
    assert ceiling.unit_count == 24
    assert ceiling.by_role.model_dump() == {
        "analysis": 24,
        "question_generation": 48,
        "prompt_generation": 24,
        "target_execution": 48,
        "judge": 24,
    }
    assert ceiling.total == 168


def test_production_shape_has_no_secondary_evaluator_and_identical_targets() -> None:
    protocol = parsed(production_shape_protocol())
    assert protocol.evaluation.primary == "llm_judge"
    assert protocol.evaluation.secondary is None
    assert protocol.providers.baseline_target == protocol.providers.promptpilot_target
    assert protocol.baseline_target_parameters == protocol.promptpilot_target_parameters
    assert protocol.call_budgets.by_role.judge == 0


def test_complete_test_contract_is_structural_but_synthetic_is_never_live_ready() -> None:
    protocol = parsed()
    report = admit_protocol(protocol, load_dataset(DATASET), PROTOCOL)
    assert not report.ready and not report.technical_ready
    assert report.admitted_fixture_ids == ()
    assert {item.code for item in report.blockers} >= {
        "fixture_not_live_eligible",
        "fixture_set_not_fully_admitted",
    }
    assert not report.human_approval.externally_verified
    assert "external human verification" in report.human_approval.statement
    assert "does not authorize" in report.authorization_statement


def test_call_ceiling_is_deterministic_by_role_and_total() -> None:
    ceiling = calculate_call_ceiling(parsed())
    assert ceiling.fixture_count == 1 and ceiling.unit_count == 2
    assert ceiling.by_role.model_dump() == {
        "analysis": 2,
        "question_generation": 4,
        "prompt_generation": 2,
        "target_execution": 4,
        "judge": 0,
    }
    assert ceiling.total == 12

    data = protocol_data()
    data["evaluation"] = {"primary": "llm_judge", "secondary": "heuristic"}
    data["providers"]["judge"] = {"provider": "offline-test", "model": "judge-test-model"}
    data["call_budgets"]["by_role"]["judge"] = 2
    data["call_budgets"]["total"] = 14
    judged = calculate_call_ceiling(parsed(data))
    assert judged.by_role.judge == 2 and judged.total == 14


def test_temporary_unverified_candidate_passes_only_technical_admission(
    tmp_path: Path,
) -> None:
    protocol, protocol_path, fixture_id = positive_protocol(tmp_path)
    report = admit_protocol(protocol, load_dataset(DATASET), protocol_path)

    assert report.technical_ready is True
    assert report.ready is True
    assert report.blockers == ()
    assert report.admitted_fixture_ids == (fixture_id,)
    assert report.call_ceiling is not None
    assert report.call_ceiling.by_role.model_dump() == {
        "analysis": 2,
        "question_generation": 4,
        "prompt_generation": 2,
        "target_execution": 4,
        "judge": 0,
    }
    assert report.call_ceiling.total == 12
    assert report.human_approval.externally_verified is False
    assert "does not authorize" in report.authorization_statement


def test_timezone_aware_iso_timestamps_survive_revalidation_and_hashing(
    tmp_path: Path,
) -> None:
    protocol, protocol_path, _ = positive_protocol(tmp_path)
    revalidated = LiveStudyProtocol.model_validate(
        protocol.model_dump(mode="python", warnings=False)
    )
    assert revalidated.review.locked_at is not None
    assert revalidated.review.locked_at.utcoffset() is not None
    assert revalidated.selected_fixtures[0].attestation.reviewed_at.utcoffset() is not None
    assert protocol_sha256(revalidated) == protocol_sha256(protocol)
    assert admit_protocol(revalidated, load_dataset(DATASET), protocol_path).ready is True


@pytest.mark.parametrize("value", [0, 0.0, True, "0", float("nan"), float("inf")])
def test_attestation_review_timestamp_rejects_non_iso_scalars(value: object) -> None:
    data = protocol_data()
    data["selected_fixtures"][0]["attestation"]["reviewed_at"] = value
    with pytest.raises(ValidationError, match="timezone-aware ISO-8601"):
        parsed(data)


@pytest.mark.parametrize("value", [0, 0.0, False, "0", float("nan"), float("inf")])
def test_protocol_lock_timestamp_rejects_non_iso_scalars(value: object) -> None:
    data = protocol_data()
    data["review"]["locked_at"] = value
    with pytest.raises(ValidationError, match="timezone-aware ISO-8601"):
        parsed(data)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("selected_fixtures", 0, "attestation", "reviewed_at"), "2026-02-01T12:00:00"),
        (("review", "locked_at"), "2026-02-01T12:00:00"),
    ],
)
def test_protocol_timestamps_reject_timezone_naive_iso_strings(path, value) -> None:
    data = protocol_data()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError, match="include a timezone"):
        parsed(data)


def test_numeric_timestamp_in_referenced_manifest_cannot_be_ready(tmp_path: Path) -> None:
    protocol, protocol_path, _ = positive_protocol(tmp_path)
    manifest_path = tmp_path / protocol.selected_fixtures[0].manifest_path
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["review"]["reviewed_at"] = 0
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    report = admit_protocol(protocol, load_dataset(DATASET), protocol_path)
    assert report.ready is False and report.technical_ready is False
    assert any(blocker.code == "fixture_validation_failed" for blocker in report.blockers)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("repetitions",), True),
        (("repetitions",), "2"),
        (("question_cap",), "2"),
        (("baseline_target_parameters", "max_tokens"), "300"),
        (("baseline_target_parameters", "max_tokens"), True),
        (("baseline_target_parameters", "seed"), "7"),
        (("baseline_target_parameters", "seed"), False),
        (("call_budgets", "by_role", "analysis"), "2"),
        (("call_budgets", "by_role", "target_execution"), True),
        (("call_budgets", "total"), "12"),
        (("call_budgets", "total"), False),
        (("stop_rules", "maximum_consecutive_provider_failures"), "1"),
        (("stop_rules", "maximum_consecutive_provider_failures"), True),
        (("stop_rules", "stop_on_budget_exhaustion"), 1),
        (("stop_rules", "stop_on_manifest_change"), "true"),
        (("analysis_stratum", "fallback_containing_runs_admissible"), 0),
        (("selected_fixtures", 0, "attestation", "test_only"), 1),
        (("baseline_target_parameters", "temperature"), "0"),
        (("baseline_target_parameters", "top_p"), "1"),
        (("baseline_target_parameters", "presence_penalty"), False),
    ],
)
def test_external_scalar_coercion_is_rejected(path, value) -> None:
    data = protocol_data()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        parsed(data)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"study_title": "   "}),
        lambda data: data.update({"study_version": "\t"}),
        lambda data: data["providers"]["analysis"].update({"provider": "  "}),
        lambda data: data["providers"]["analysis"].update({"model": "\n"}),
        lambda data: data["selected_fixtures"][0].update({"fixture_id": "   "}),
        lambda data: data["selected_fixtures"][0].update({"manifest_path": "\t"}),
        lambda data: data["selected_fixtures"][0]["attestation"].update(
            {"fixture_id": "  "}
        ),
        lambda data: data["selected_fixtures"][0]["attestation"].update(
            {"reviewer_id": "  "}
        ),
        lambda data: data["selected_fixtures"][0]["attestation"].update(
            {"provenance_consent_evidence_reference": "\n"}
        ),
        lambda data: data["review"].update({"reviewer_id": "  "}),
    ],
)
def test_blank_semantic_values_are_rejected(mutation) -> None:
    data = protocol_data()
    mutation(data)
    with pytest.raises(ValidationError, match="non-whitespace"):
        parsed(data)


def test_blank_pricing_reference_is_rejected() -> None:
    data = protocol_data()
    data["monetary_budget"] = {
        "currency": "USD",
        "maximum_cost": 10,
        "pricing_snapshot_reference": "   ",
    }
    with pytest.raises(ValidationError, match="non-whitespace"):
        parsed(data)


@pytest.mark.parametrize("value", ["10", True])
def test_monetary_cost_scalar_coercion_is_rejected(value) -> None:
    data = protocol_data()
    data["monetary_budget"] = {
        "currency": "USD",
        "maximum_cost": value,
        "pricing_snapshot_reference": "unverified-unit-test://pricing",
    }
    with pytest.raises(ValidationError):
        parsed(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_monetary_values_are_rejected(value: float) -> None:
    data = protocol_data()
    data["monetary_budget"] = {
        "currency": "USD",
        "maximum_cost": value,
        "pricing_snapshot_reference": "unverified-unit-test://pricing",
    }
    with pytest.raises(ValidationError, match="finite number"):
        parsed(data)


@pytest.mark.parametrize(
    "field", ["temperature", "top_p", "presence_penalty", "frequency_penalty"]
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_target_parameters_are_rejected(field: str, value: float) -> None:
    data = protocol_data()
    data["baseline_target_parameters"][field] = value
    data["promptpilot_target_parameters"][field] = value
    with pytest.raises(ValidationError, match="finite number"):
        parsed(data)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("comparison_policy", "baseline_input"), "rewritten", "baseline_input"),
        (("comparison_policy", "execution_order"), "randomized", "execution_order"),
        (("comparison_policy", "incomplete_pair_evaluation"), "allowed", "incomplete"),
        (("comparison_policy", "unmatched_gap"), "TBD", "placeholder"),
        (("review", "status"), "pending", "review"),
    ],
)
def test_fixed_or_incomplete_policies_cannot_be_admitted(path, value, message) -> None:
    data = protocol_data()
    data[path[0]][path[1]] = value
    if path == ("review", "status"):
        data["review"] = {"status": "pending", "reviewer_id": None, "locked_at": None}
        report = admit_protocol(parsed(data), load_dataset(DATASET), PROTOCOL)
        assert any(item.code == "protocol_not_locked" for item in report.blockers)
    else:
        with pytest.raises(ValidationError, match=message):
            parsed(data)


def test_target_provider_model_and_parameters_must_match() -> None:
    data = protocol_data()
    data["providers"]["promptpilot_target"]["model"] = "different-model"
    with pytest.raises(ValidationError, match="provider/model must match"):
        parsed(data)
    data = protocol_data()
    data["promptpilot_target_parameters"]["temperature"] = 0.5
    with pytest.raises(ValidationError, match="target parameters must match"):
        parsed(data)


def test_judge_assignment_rules_are_enforced() -> None:
    data = protocol_data()
    data["providers"]["judge"] = {"provider": "offline-test", "model": "unused-judge"}
    with pytest.raises(ValidationError, match="must not assign a judge"):
        parsed(data)
    data = protocol_data()
    data["evaluation"] = {"primary": "llm_judge", "secondary": None}
    with pytest.raises(ValidationError, match="requires a judge"):
        parsed(data)


def test_insufficient_per_role_and_total_budgets_are_explicit_blockers() -> None:
    data = protocol_data()
    data["call_budgets"]["by_role"]["target_execution"] = 3
    data["call_budgets"]["total"] = 11
    report = admit_protocol(parsed(data), load_dataset(DATASET), PROTOCOL)
    codes = [item.code for item in report.blockers]
    assert "insufficient_role_budget" in codes
    assert "insufficient_total_budget" in codes
    assert report.call_ceiling is not None and report.call_ceiling.total == 12


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"api_key": "not-a-real-key"}),
        lambda data: data["providers"]["analysis"].update(
            {"provider": "Authorization: Bearer secret-material"}
        ),
        lambda data: data["baseline_target_parameters"].update({"token": "secret"}),
    ],
)
def test_credential_like_fields_and_values_are_rejected_without_echo(mutation) -> None:
    data = protocol_data()
    mutation(data)
    with pytest.raises(ValidationError) as caught:
        parsed(data)
    assert "secret-material" not in str(caught.value)


def test_missing_or_mismatched_attestations_are_rejected() -> None:
    data = protocol_data()
    del data["selected_fixtures"][0]["attestation"]
    with pytest.raises(ValidationError, match="attestation"):
        parsed(data)
    data = protocol_data()
    data["selected_fixtures"][0]["attestation"]["fixture_id"] = "different-fixture"
    with pytest.raises(ValidationError, match="attestation does not match"):
        parsed(data)


def test_stale_dataset_and_manifest_hashes_block_admission() -> None:
    data = protocol_data()
    data["dataset_sha256"] = "0" * 64
    report = admit_protocol(parsed(data), load_dataset(DATASET), PROTOCOL)
    assert any(item.code == "dataset_identity_mismatch" for item in report.blockers)

    data = protocol_data()
    wrong_hash = "1" * 64
    data["selected_fixtures"][0]["manifest_sha256"] = wrong_hash
    data["selected_fixtures"][0]["attestation"]["manifest_sha256"] = wrong_hash
    report = admit_protocol(parsed(data), load_dataset(DATASET), PROTOCOL)
    assert any(item.code == "manifest_hash_mismatch" for item in report.blockers)


def test_changed_frozen_document_bytes_block_admission(tmp_path: Path) -> None:
    copied = tmp_path / "protocol.json"
    manifest = tmp_path / "synthetic_manifest.json"
    copied.write_text(PROTOCOL.read_text(encoding="utf-8"), encoding="utf-8")
    manifest.write_text(
        (FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "synthetic_workshop.txt").write_bytes(b"changed frozen bytes")
    report = admit_protocol(parsed(), load_dataset(DATASET), copied)
    assert any(item.code == "fixture_validation_failed" for item in report.blockers)


def test_pending_manifest_is_not_live_admitted(tmp_path: Path) -> None:
    manifest_data = json.loads(
        (FIXTURES / "synthetic_manifest.json").read_text(encoding="utf-8")
    )
    manifest_data.update(
        {
            "fixture_id": "pending-planning-workshop-v1",
            "fixture_kind": "experimental_candidate",
            "review": {"status": "pending", "reviewer_id": None, "reviewed_at": None},
            "project_facts": [],
            "clarification_answers": [],
            "frozen_documents": [],
            "evaluation_only": [],
        }
    )
    manifest = FixtureManifest.model_validate(manifest_data)
    manifest_path = tmp_path / "pending_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    digest = manifest_sha256(manifest)
    data = protocol_data()
    selection = data["selected_fixtures"][0]
    selection["fixture_id"] = manifest.fixture_id
    selection["manifest_path"] = manifest_path.name
    selection["manifest_sha256"] = digest
    selection["attestation"].update(
        {"fixture_id": manifest.fixture_id, "manifest_sha256": digest}
    )
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(data), encoding="utf-8")
    report = admit_protocol(parsed(data), load_dataset(DATASET), protocol_path)
    assert any(item.code == "fixture_not_live_eligible" for item in report.blockers)


def test_models_and_nested_collections_cannot_be_mutated_or_forged_ready() -> None:
    protocol = parsed()
    with pytest.raises(ValidationError, match="frozen_instance"):
        protocol.repetitions = 1
    with pytest.raises(ValidationError, match="frozen_instance"):
        protocol.providers.baseline_target.model = "changed"
    with pytest.raises(TypeError):
        protocol.selected_fixtures[0] = protocol.selected_fixtures[0]
    forged = protocol.model_copy(
        update={"promptpilot_target_parameters": protocol.promptpilot_target_parameters.model_copy(
            update={"temperature": 1.0}
        )}
    )
    with pytest.raises(ValidationError, match="target parameters must match"):
        calculate_call_ceiling(forged)


def test_existing_output_is_rejected_before_validation_or_provider_construction(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "report.json"
    output.write_text("keep", encoding="utf-8")
    called = False

    def forbidden_load(_path):
        nonlocal called
        called = True
        raise AssertionError("validation work must not start")

    monkeypatch.setattr(
        "promptpilot_backend.production_benchmark_protocol.load_dataset", forbidden_load
    )
    with pytest.raises(FileExistsError):
        validate_to_report(DATASET, PROTOCOL, output)
    assert not called and output.read_text(encoding="utf-8") == "keep"


def test_cli_writes_machine_readable_failure_without_constructing_provider(
    monkeypatch, tmp_path: Path
) -> None:
    from promptpilot_backend import llm_provider

    def forbidden_provider(*args, **kwargs):
        raise AssertionError("provider construction is forbidden")

    monkeypatch.setattr(llm_provider.OpenAICompatibleProvider, "__init__", forbidden_provider)
    output = tmp_path / "admission.json"
    result = main(
        [
            "validate",
            "--dataset",
            str(DATASET),
            "--protocol",
            str(PROTOCOL),
            "--output",
            str(output),
        ]
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 1 and report["ready"] is False
    assert report["call_ceiling"]["total"] == 12
    assert "secret" not in json.dumps(report).casefold()


def test_independent_revalidation_rejects_nested_model_copy_bypass() -> None:
    protocol = parsed()
    policies = protocol.comparison_policy.model_copy(update={"baseline_input": "rewritten"})
    forged = protocol.model_copy(update={"comparison_policy": policies})
    with pytest.raises(ValidationError, match="baseline_input"):
        admit_protocol(forged, load_dataset(DATASET), PROTOCOL)


def test_model_copy_cannot_inject_unsafe_scalars_or_non_finite_hash_material() -> None:
    protocol = parsed()
    forged_repetitions = protocol.model_copy(update={"repetitions": True})
    with pytest.raises(ValidationError):
        admit_protocol(forged_repetitions, load_dataset(DATASET), PROTOCOL)

    unsafe_parameters = protocol.baseline_target_parameters.model_copy(
        update={"temperature": float("nan")}
    )
    forged_float = protocol.model_copy(
        update={
            "baseline_target_parameters": unsafe_parameters,
            "promptpilot_target_parameters": unsafe_parameters,
        }
    )
    with pytest.raises(ValidationError, match="finite number"):
        protocol_sha256(forged_float)
    with pytest.raises(ValidationError, match="finite number"):
        admit_protocol(forged_float, load_dataset(DATASET), PROTOCOL)


def test_non_finite_value_cannot_enter_serialized_admission_report(tmp_path: Path) -> None:
    report = admit_protocol(parsed(), load_dataset(DATASET), PROTOCOL)
    assert report.call_ceiling is not None
    forged_ceiling = report.call_ceiling.model_copy(update={"total": float("inf")})
    forged_report = report.model_copy(update={"call_ceiling": forged_ceiling})
    with pytest.raises(ValidationError):
        AdmissionReport.model_validate(
            forged_report.model_dump(mode="python", warnings=False)
        )

    output = tmp_path / "reserved.json"
    with output.open("x+", encoding="utf-8") as handle:
        with pytest.raises(ValidationError):
            _write_reserved(handle, forged_report)
    assert output.read_text(encoding="utf-8") == ""


def test_forged_report_scalar_types_are_rejected_before_serialization(
    tmp_path: Path,
) -> None:
    report = admit_protocol(parsed(), load_dataset(DATASET), PROTOCOL)
    assert report.call_ceiling is not None
    forged_reports = [
        report.model_copy(update={"technical_ready": 1}),
        report.model_copy(update={"ready": 0}),
        report.model_copy(
            update={
                "human_approval": report.human_approval.model_copy(
                    update={"externally_verified": 0}
                )
            }
        ),
        report.model_copy(
            update={
                "call_ceiling": report.call_ceiling.model_copy(
                    update={"fixture_count": True}
                )
            }
        ),
        report.model_copy(
            update={
                "call_ceiling": report.call_ceiling.model_copy(
                    update={"unit_count": "2"}
                )
            }
        ),
        report.model_copy(
            update={
                "call_ceiling": report.call_ceiling.model_copy(update={"total": 12.0})
            }
        ),
    ]
    for index, forged in enumerate(forged_reports):
        output = tmp_path / f"forged-report-{index}.json"
        with output.open("x+", encoding="utf-8") as handle:
            with pytest.raises(ValidationError):
                _write_reserved(handle, forged)
        assert output.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize("value", [0, 0.0, True, "0", float("nan"), float("inf")])
def test_timestamp_model_copy_bypass_is_rejected(value: object, tmp_path: Path) -> None:
    protocol, protocol_path, _ = positive_protocol(tmp_path)
    selection = protocol.selected_fixtures[0]
    forged_attestation = selection.attestation.model_copy(update={"reviewed_at": value})
    forged_selection = selection.model_copy(update={"attestation": forged_attestation})
    forged_attestation_protocol = protocol.model_copy(
        update={"selected_fixtures": (forged_selection,)}
    )
    with pytest.raises(ValidationError, match="timezone-aware ISO-8601"):
        admit_protocol(forged_attestation_protocol, load_dataset(DATASET), protocol_path)

    forged_review = protocol.review.model_copy(update={"locked_at": value})
    forged_review_protocol = protocol.model_copy(update={"review": forged_review})
    with pytest.raises(ValidationError, match="timezone-aware ISO-8601"):
        protocol_sha256(forged_review_protocol)


def test_positive_admission_mismatches_cannot_be_forged_with_model_copy(
    tmp_path: Path,
) -> None:
    protocol, protocol_path, _ = positive_protocol(tmp_path)
    selection = protocol.selected_fixtures[0]
    changed_reviewer = selection.attestation.model_copy(
        update={"reviewer_id": "different-unverified-unit-test-reviewer"}
    )
    reviewer_forgery = protocol.model_copy(
        update={
            "selected_fixtures": (
                selection.model_copy(update={"attestation": changed_reviewer}),
            )
        }
    )
    reviewer_report = admit_protocol(
        reviewer_forgery, load_dataset(DATASET), protocol_path
    )
    assert reviewer_report.ready is False
    assert any(
        blocker.code == "attestation_review_mismatch"
        for blocker in reviewer_report.blockers
    )

    changed_time = selection.attestation.model_copy(
        update={"reviewed_at": selection.attestation.reviewed_at + timedelta(seconds=1)}
    )
    time_forgery = protocol.model_copy(
        update={
            "selected_fixtures": (
                selection.model_copy(update={"attestation": changed_time}),
            )
        }
    )
    time_report = admit_protocol(time_forgery, load_dataset(DATASET), protocol_path)
    assert any(
        blocker.code == "attestation_review_mismatch" for blocker in time_report.blockers
    )

    blank_evidence = selection.attestation.model_copy(
        update={"provenance_consent_evidence_reference": "   "}
    )
    evidence_forgery = protocol.model_copy(
        update={
            "selected_fixtures": (
                selection.model_copy(update={"attestation": blank_evidence}),
            )
        }
    )
    with pytest.raises(ValidationError, match="non-whitespace"):
        admit_protocol(evidence_forgery, load_dataset(DATASET), protocol_path)

    changed_hash = "f" * 64
    hash_forgery = protocol.model_copy(
        update={
            "selected_fixtures": (
                selection.model_copy(
                    update={
                        "manifest_sha256": changed_hash,
                        "attestation": selection.attestation.model_copy(
                            update={"manifest_sha256": changed_hash}
                        ),
                    }
                ),
            )
        }
    )
    hash_report = admit_protocol(hash_forgery, load_dataset(DATASET), protocol_path)
    assert any(blocker.code == "manifest_hash_mismatch" for blocker in hash_report.blockers)

    changed_id = "different-unverified-unit-test-fixture"
    id_forgery = protocol.model_copy(
        update={
            "selected_fixtures": (
                selection.model_copy(
                    update={
                        "fixture_id": changed_id,
                        "attestation": selection.attestation.model_copy(
                            update={"fixture_id": changed_id}
                        ),
                    }
                ),
            )
        }
    )
    id_report = admit_protocol(id_forgery, load_dataset(DATASET), protocol_path)
    assert any(blocker.code == "fixture_id_mismatch" for blocker in id_report.blockers)
