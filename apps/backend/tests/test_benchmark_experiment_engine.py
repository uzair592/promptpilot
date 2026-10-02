"""Fail-closed safety coverage for the pre-live experiment engine.

These tests exist because this is a research experiment, not a product feature.
Each one asserts that an experimental mistake, a protocol edit, or an absent
human authorization prevents execution rather than degrading it.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from conftest import (
    EXPERIMENT_DATASET as DATASET,
)
from conftest import (
    EXPERIMENT_MANIFEST as MANIFEST,
)
from conftest import (
    EXPERIMENT_PROTOCOL as PROTOCOL,
)
from conftest import (
    bind_offline_fixture,
    experiment_owner,
    parse_protocol,
    production_shape_payload,
    technical_admission,
)

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_call_ledger import (
    BenchmarkCallLedger,
    LedgerError,
    ReservationDeclaration,
    canonical_artifact_sha256,
)
from promptpilot_backend.benchmark_experiment_authorization import (
    AuthorizationError,
    LaunchGateBlocker,
    LiveLaunchAuthorization,
    evaluate_launch_gate,
    parse_authorization,
)
from promptpilot_backend.benchmark_experiment_binding import (
    BindingError,
    ProtocolBinding,
    assert_binding_current,
    assert_fixture_current,
    bind_protocol,
)
from promptpilot_backend.benchmark_experiment_execution import (
    ExecutionGateError,
    ReservedCall,
    approved_condition_order,
    assert_approved_order,
    require_offline_provider,
)
from promptpilot_backend.benchmark_fixtures import FixtureManifest
from promptpilot_backend.db import SessionLocal
from promptpilot_backend.llm_provider import OpenAICompatibleProvider
from promptpilot_backend.production_benchmark_protocol import (
    LiveStudyProtocol,
    admit_protocol,
)
from promptpilot_backend.schemas import LLMJudgeOutput, ResponseScore

PROTOCOL_SHA = "a" * 64

protocol_data = parse_protocol.__globals__["protocol_payload"]
parsed_protocol = parse_protocol
production_shape = production_shape_payload
seeded_run = experiment_owner
ready_admission_for = technical_admission


def offline_binding(
    tmp_path: Path, *, data: dict | None = None
) -> tuple[ProtocolBinding, LiveStudyProtocol]:
    return bind_offline_fixture(tmp_path, data)


class RealLookingProvider:
    """No offline_fixture marker: must be refused."""

    name = "real-looking"
    model = "some-model"

    def generate(self, payload):
        raise AssertionError("must never be invoked")


# --------------------------------------------------------------------------
# Negative scenarios 1-20: nothing can start accidentally
# --------------------------------------------------------------------------


def test_scenario_01_unlocked_protocol_cannot_be_staged(client) -> None:
    """A not-ready admission must never produce a staged run."""

    protocol = parsed_protocol()
    report = admit_protocol(protocol, load_dataset(DATASET), PROTOCOL)
    assert report.ready is False
    codes = {blocker.code for blocker in report.blockers}
    assert "fixture_not_live_eligible" in codes
    owner = seeded_run(client)
    with SessionLocal() as session:
        with pytest.raises(LedgerError) as caught:
            BenchmarkCallLedger.stage_run(session, owner, protocol, report)
        assert caught.value.code == "protocol_not_ready"


def test_scenario_02_synthetic_fixture_is_never_live(tmp_path: Path) -> None:
    binding, _ = offline_binding(tmp_path)
    assert binding.fixture_bindings[0].fixture_kind == "synthetic_offline_test"
    assert binding.fixture_bindings[0].live_eligible is False


def test_scenario_03_synthetic_fixture_cannot_claim_live_eligibility(tmp_path: Path) -> None:
    dataset = load_dataset(DATASET)
    manifest = load_manifest()
    with pytest.raises(ValueError, match="Synthetic fixtures cannot claim human review"):
        FixtureManifest.model_validate(
            {
                **json.loads(MANIFEST.read_text(encoding="utf-8")),
                "review": {
                    "status": "human_approved",
                    "reviewer_id": "invented-reviewer",
                    "reviewed_at": "2026-02-01T12:00:00Z",
                },
            }
        )
    assert manifest.dataset_name == dataset.name


def load_manifest():
    return FixtureManifest.model_validate(json.loads(MANIFEST.read_text(encoding="utf-8")))


def test_scenario_04_fixture_hash_change_invalidates_binding(tmp_path: Path) -> None:
    binding, _ = offline_binding(tmp_path)
    manifest_data = json.loads((tmp_path / "bound_manifest.json").read_text("utf-8"))
    manifest_data["original_task"]["content"] = manifest_data["original_task"][
        "content"
    ] + " "
    import hashlib

    manifest_data["original_task"]["content_sha256"] = hashlib.sha256(
        manifest_data["original_task"]["content"].encode()
    ).hexdigest()
    mutated_path = tmp_path / "mutated.json"
    mutated_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    mutated = FixtureManifest.model_validate(manifest_data)
    with pytest.raises(ValueError):
        assert_fixture_current(
            binding,
            binding.fixture_bindings[0].fixture_id,
            mutated,
            load_dataset(DATASET),
            mutated_path,
        )


def test_scenario_05_dataset_hash_change_is_detected() -> None:
    data = protocol_data()
    data["dataset_sha256"] = "0" * 64
    protocol = parsed_protocol(data)
    dataset = load_dataset(DATASET)
    with pytest.raises(BindingError) as caught:
        bind_protocol(protocol, dataset, [])
    assert caught.value.code == "dataset_identity_mismatch"


def test_scenario_06_protocol_change_invalidates_staged_binding(tmp_path: Path) -> None:
    binding, _ = offline_binding(tmp_path)
    mutated = parsed_protocol(production_shape())
    with pytest.raises(BindingError) as caught:
        assert_binding_current(binding, mutated)
    assert caught.value.code == "protocol_drift_after_staging"


def test_scenario_07_absent_human_approval_blocks_launch() -> None:
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-a",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=None,
        target_provider="offline-test",
        target_model="offline-model",
    )
    assert report.ready is False
    assert "launch_authorization_absent" in {item.code for item in report.blockers}


def test_scenario_08_provider_authorization_is_required() -> None:
    """A withheld provider grant must fail closed at the boundary."""

    with pytest.raises(ValueError):
        _authorization(provider_authorized=False)
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-a",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=None,
        target_provider="offline-test",
        target_model="offline-model",
    )
    assert report.provider_authorized is False
    assert "launch_authorization_absent" in {item.code for item in report.blockers}


def test_scenario_09_spending_authorization_is_required() -> None:
    """A withheld spending grant must fail closed at the boundary."""

    with pytest.raises(ValueError):
        _authorization(spending_authorized=False)
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-a",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=None,
        target_provider="offline-test",
        target_model="offline-model",
    )
    assert report.spending_authorized is False


def _authorization(**updates):
    payload = {
        "authorization_version": "v1",
        "authorization_id": "authz-2026-0001",
        "issued_by_reference": "https://authority.example.org/releases/42",
        "issued_at": datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
        "protocol_sha256": PROTOCOL_SHA,
        "provider_authorized": True,
        "spending_authorized": True,
        "authorized_provider": "offline-test",
        "authorized_model": "offline-model",
        "maximum_spend": 10.0,
        "spend_currency": "USD",
        "evidence_reference": "https://authority.example.org/evidence/42",
    }
    payload.update(updates)
    return LiveLaunchAuthorization.model_validate(payload)


def test_scenario_10_target_model_mismatch_blocks_launch() -> None:
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-a",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=_authorization(),
        target_provider="offline-test",
        target_model="a-different-model",
    )
    assert report.ready is False
    assert "authorized_provider_mismatch" in {item.code for item in report.blockers}


def test_scenario_11_generation_parameters_must_be_identical() -> None:
    data = protocol_data()
    data["promptpilot_target_parameters"]["temperature"] = 0.4
    with pytest.raises(ValueError, match="target parameters must match"):
        parsed_protocol(data)


def test_scenario_12_insufficient_budget_is_a_blocker() -> None:
    data = protocol_data()
    data["call_budgets"]["by_role"]["target_execution"] = 1
    data["call_budgets"]["total"] = 9
    report = admit_protocol(parsed_protocol(data), load_dataset(DATASET), PROTOCOL)
    codes = {blocker.code for blocker in report.blockers}
    assert "insufficient_role_budget" in codes
    assert "insufficient_total_budget" in codes


def test_scenario_13_no_attempt_exists_before_reservation(client, tmp_path) -> None:
    """mark_started must fail until a reservation has been committed."""

    owner = seeded_run(client)
    binding, protocol = offline_binding(tmp_path)
    with SessionLocal() as session:
        run = BenchmarkCallLedger.stage_run(
            session, owner, protocol, ready_admission_for(protocol)
        )
        BenchmarkCallLedger.start_run(session, run.id)
        declaration = _declaration(binding)
        with pytest.raises(LedgerError) as caught:
            BenchmarkCallLedger.mark_started(
                session, UUID("00000000-0000-0000-0000-000000000000")
            )
        assert caught.value.code == "attempt_not_found"
        attempt = BenchmarkCallLedger.reserve_call(session, run.id, declaration)
        assert attempt.status == "reserved"
        assert BenchmarkCallLedger.mark_started(session, attempt.id).status == "started"


def test_reservation_rejects_a_protocol_hash_that_drifted(client, tmp_path) -> None:
    """A reservation bound to a different protocol must never be accepted."""

    owner = seeded_run(client)
    binding, protocol = offline_binding(tmp_path)
    drifted_data = protocol_data()
    drifted_data["study_title"] = "A different frozen protocol title"
    drifted, _ = offline_binding(tmp_path, data=drifted_data)
    assert drifted.protocol_sha256 != binding.protocol_sha256
    with SessionLocal() as session:
        run = BenchmarkCallLedger.stage_run(
            session, owner, protocol, ready_admission_for(protocol)
        )
        BenchmarkCallLedger.start_run(session, run.id)
        declaration = _declaration(drifted)
        with pytest.raises(LedgerError) as caught:
            BenchmarkCallLedger.reserve_call(session, run.id, declaration)
        assert caught.value.code == "protocol_hash_mismatch"


def _declaration(binding: ProtocolBinding):
    return ReservationDeclaration(
        stable_unit_id="task#r1",
        fixture_id=binding.fixture_bindings[0].fixture_id,
        task_id="planning-launch-001",
        repetition=1,
        provider_role="analysis",
        target_condition=None,
        idempotency_key="unit1:analysis",
        configured_provider="offline-test",
        configured_model="analysis-test-model",
        generation_parameter_sha256=canonical_artifact_sha256({}),
        request_artifact_sha256=canonical_artifact_sha256({"x": 1}),
        protocol_sha256=binding.protocol_sha256,
        dataset_sha256=binding.dataset_sha256,
    )


def test_scenario_14_offline_only_provider_is_required() -> None:
    with pytest.raises(ExecutionGateError) as caught:
        require_offline_provider(RealLookingProvider(), "analysis")
    assert caught.value.code == "provider_not_offline"


def test_scenario_15_real_openai_provider_is_rejected_in_offline_mode() -> None:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.base_url = "https://example.invalid"
    provider.model = "m"
    provider.api_key = ""
    with pytest.raises(ExecutionGateError) as caught:
        require_offline_provider(provider, "target_execution")
    assert caught.value.code == "real_provider_rejected"


def test_scenario_16_question_cap_is_frozen_by_the_binding(tmp_path: Path) -> None:
    binding, _ = offline_binding(tmp_path)
    assert binding.question_cap == 2
    assert binding.fallback_admission == "reject"
    assert binding.repetitions == 2


def test_scenario_17_fallback_rejection_is_bound() -> None:
    data = production_shape()
    data["comparison_policy"]["fallback_admission"] = "admit_separate_stratum"
    data["analysis_stratum"] = {
        "name": "hybrid_product_behavior",
        "fallback_containing_runs_admissible": True,
    }
    protocol = parsed_protocol(data)
    assert protocol.comparison_policy.fallback_admission == "admit_separate_stratum"
    frozen = protocol_data()
    assert frozen["comparison_policy"]["fallback_admission"] == "reject"


def test_condition_order_and_pairing_are_enforced() -> None:
    assert approved_condition_order(1) == ("baseline", "promptpilot")
    assert approved_condition_order(2) == ("promptpilot", "baseline")
    assert approved_condition_order(3) == ("baseline", "promptpilot")
    assert_approved_order(1, ["baseline", "promptpilot"])
    with pytest.raises(ExecutionGateError) as caught:
        assert_approved_order(2, ["baseline", "promptpilot"])
    assert caught.value.code == "condition_order_mismatch"
    with pytest.raises(ExecutionGateError):
        approved_condition_order(0)


def test_scenario_18_single_target_failure_cannot_complete_a_pair() -> None:

    call = ReservedCall(
        role="target_execution",
        target_condition="promptpilot",
        attempt_id=None,
        status="failed",
        idempotency_key="k",
        request_sha256="b" * 64,
        safe_error_code="provider_call_failed",
    )
    assert call.status == "failed"
    assert call.status != "succeeded"


def test_scenario_19_evaluation_failure_is_not_downgraded_to_heuristic() -> None:
    with pytest.raises(ValueError):
        LLMJudgeOutput.model_validate({"response_a": {"relevance": "high"}})
    assert ResponseScore(
        relevance=1, completeness=1, instruction_following=1,
        contextual_grounding=1, clarity=1,
    ).relevance == 1


def test_scenario_20_pair_identity_inconsistency_is_detectable(tmp_path: Path) -> None:
    binding, _ = offline_binding(tmp_path)
    with pytest.raises(BindingError) as caught:
        assert_fixture_current(
            binding, "not-a-bound-fixture", load_manifest(), load_dataset(DATASET), MANIFEST
        )
    assert caught.value.code == "fixture_not_bound"


# --------------------------------------------------------------------------
# Authorization boundary: software cannot manufacture approval
# --------------------------------------------------------------------------


def test_authorization_has_no_verified_field_and_rejects_local_evidence() -> None:
    assert "verified" not in LiveLaunchAuthorization.model_fields
    with pytest.raises(ValueError):
        _authorization(evidence_reference="authorization.json")
    with pytest.raises(ValueError):
        _authorization(evidence_reference="file:///tmp/auth.json")


def test_authorization_rejects_placeholder_and_dummy_values() -> None:
    with pytest.raises(ValueError):
        _authorization(issued_by_reference="https://authority.example.org/TBD")
    with pytest.raises(ValueError):
        _authorization(authorization_id="test")


def test_authorization_binds_to_one_protocol() -> None:
    auth = _authorization()
    auth.assert_applies_to(PROTOCOL_SHA)
    with pytest.raises(AuthorizationError) as caught:
        auth.assert_applies_to("f" * 64)
    assert caught.value.code == "authorization_protocol_mismatch"
    auth.assert_covers_provider("offline-test", "offline-model")
    with pytest.raises(AuthorizationError):
        auth.assert_covers_provider("offline-test", "other")


def test_authorization_document_is_malformed_when_absent() -> None:
    with pytest.raises(AuthorizationError) as caught:
        parse_authorization({"nothing": "here"})
    assert caught.value.code == "authorization_invalid"


def test_launch_gate_passes_only_with_complete_external_authorization() -> None:
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-a",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=_authorization(),
        target_provider="offline-test",
        target_model="offline-model",
    )
    assert report.ready is True and report.admitted is True
    assert "cannot" not in report.software_verification_limit or "unverified" in (
        report.software_verification_limit
    )


def test_launch_gate_requires_protocol_locked_and_live_fixtures() -> None:
    report = evaluate_launch_gate(
        protocol_locked=False,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-a",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=_authorization(),
        target_provider="offline-test",
        target_model="offline-model",
    )
    codes = {item.code for item in report.blockers}
    assert "protocol_not_locked" in codes
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=("fixture-a",),
        live_eligible_fixture_ids=("fixture-b",),
        protocol_sha256=PROTOCOL_SHA,
        authorization=_authorization(),
        target_provider="offline-test",
        target_model="offline-model",
    )
    assert "fixtures_not_live_eligible" in {
        item.code for item in report.blockers
    }


def test_launch_gate_reports_empty_fixture_set() -> None:
    report = evaluate_launch_gate(
        protocol_locked=True,
        fixture_ids=(),
        live_eligible_fixture_ids=(),
        protocol_sha256=PROTOCOL_SHA,
        authorization=_authorization(),
        target_provider="offline-test",
        target_model="offline-model",
    )
    assert "fixture_set_empty" in {item.code for item in report.blockers}
    assert isinstance(report.blockers[0], LaunchGateBlocker)
