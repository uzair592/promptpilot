"""Fail-closed admission tests for the future live-study protocol."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_fixtures import FixtureManifest, manifest_sha256
from promptpilot_backend.production_benchmark_protocol import (
    LiveStudyProtocol,
    admit_protocol,
    calculate_call_ceiling,
    main,
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
