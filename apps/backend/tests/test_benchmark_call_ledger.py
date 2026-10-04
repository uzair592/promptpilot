"""Durable benchmark provider-call ledger and atomic budget tests."""

import json
import threading
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError

from promptpilot_backend.benchmark_call_ledger import (
    AttemptSuccess,
    BenchmarkCallLedger,
    LedgerError,
    ReservationDeclaration,
    canonical_artifact_sha256,
    generation_parameters_sha256,
)
from promptpilot_backend.db import SessionLocal, engine
from promptpilot_backend.llm_provider import ProviderUnavailable
from promptpilot_backend.models import (
    BenchmarkExperimentRun,
    BenchmarkProviderCallAttempt,
    User,
)
from promptpilot_backend.production_benchmark_protocol import (
    AdmissionReport,
    HumanApprovalBoundary,
    LiveStudyProtocol,
    calculate_call_ceiling,
    protocol_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "tests/fixtures/production_pipeline/synthetic_protocol.json"
MIGRATION_PATH = ROOT / "migrations/013_benchmark_provider_call_ledger.sql"


def protocol() -> LiveStudyProtocol:
    return LiveStudyProtocol.model_validate(
        json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    )


def ready_admission(value: LiveStudyProtocol) -> AdmissionReport:
    return AdmissionReport(
        protocol_id=value.protocol_id,
        technical_ready=True,
        ready=True,
        protocol_sha256=protocol_sha256(value),
        dataset_sha256=value.dataset_sha256,
        admitted_fixture_ids=tuple(item.fixture_id for item in value.selected_fixtures),
        call_ceiling=calculate_call_ceiling(value),
        blockers=(),
        human_approval=HumanApprovalBoundary(
            externally_verified=False,
            statement="Unverified technical unit-test claim",
        ),
        authorization_statement="Technical validation does not authorize a live run.",
    )


def owner_id(client) -> UUID:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "ledger-owner@example.com",
            "display_name": "Ledger Owner",
            "password": "correct horse battery",
        },
    )
    assert response.status_code in {201, 409}
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "ledger-owner@example.com"))
        assert owner is not None
        return owner.id


def staged_run(db_session, client, value: LiveStudyProtocol | None = None):
    selected = value or protocol()
    return BenchmarkCallLedger.stage_run(
        db_session,
        owner_id(client),
        selected,
        ready_admission(selected),
        repository_commit_sha="a" * 40,
    )


def running_run(db_session, client, value: LiveStudyProtocol | None = None):
    run = staged_run(db_session, client, value)
    return BenchmarkCallLedger.start_run(db_session, run.id)


def declaration(
    value: LiveStudyProtocol,
    *,
    role: str = "analysis",
    key: str = "call-1",
    request_marker: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    parameter_hash: str | None = None,
    protocol_hash: str | None = None,
    dataset_hash: str | None = None,
    condition: str | None = None,
    estimated_cost: float | None = None,
    currency: str | None = None,
) -> ReservationDeclaration:
    assignments = {
        "analysis": value.providers.analysis,
        "question_generation": value.providers.question_generation,
        "prompt_generation": value.providers.prompt_generation,
        "target_execution": value.providers.baseline_target,
        "judge": value.providers.judge,
    }
    assignment = assignments[role]
    assert assignment is not None
    expected_parameter_hash = (
        generation_parameters_sha256(value)
        if role == "target_execution"
        else canonical_artifact_sha256({})
    )
    data = {
        "stable_unit_id": "synthetic-planning-workshop-v1:planning-launch-001:r1",
        "fixture_id": "synthetic-planning-workshop-v1",
        "task_id": "planning-launch-001",
        "repetition": 1,
        "provider_role": role,
        "target_condition": (condition or "baseline") if role == "target_execution" else None,
        "idempotency_key": key,
        "configured_provider": provider or assignment.provider,
        "configured_model": model or assignment.model,
        "generation_parameter_sha256": parameter_hash or expected_parameter_hash,
        "request_artifact_sha256": canonical_artifact_sha256(
            {"safe_test_artifact": request_marker or key}
        ),
        "protocol_sha256": protocol_hash or protocol_sha256(value),
        "dataset_sha256": dataset_hash or value.dataset_sha256,
    }
    if estimated_cost is not None:
        data["estimated_cost"] = estimated_cost
    if currency is not None:
        data["currency"] = currency
    return ReservationDeclaration(**data)


def test_migration_and_orm_tables_apply_with_required_constraints(client) -> None:
    tables = set(inspect(engine).get_table_names())
    assert {"benchmark_experiment_runs", "benchmark_provider_call_attempts"} <= tables
    uniques = inspect(engine).get_unique_constraints("benchmark_provider_call_attempts")
    assert {item["name"] for item in uniques} >= {
        "uq_benchmark_attempts_run_idempotency",
        "uq_benchmark_attempts_run_sequence",
    }
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "external_human_approval_verified = false" in migration
    assert "ck_benchmark_attempts_cost_finite" in migration
    assert "authorization" not in migration.casefold()


def test_staging_binds_ready_protocol_without_claiming_external_approval(
    client, db_session
) -> None:
    value = protocol()
    run = staged_run(db_session, client, value)
    ceiling = calculate_call_ceiling(value)
    assert run.status == "staged"
    assert run.protocol_sha256 == protocol_sha256(value)
    assert run.dataset_sha256 == value.dataset_sha256
    assert run.total_call_ceiling == ceiling.total == 12
    assert run.analysis_call_ceiling == ceiling.by_role.analysis
    assert run.target_execution_call_ceiling == ceiling.by_role.target_execution
    assert run.external_human_approval_verified is False
    assert run.execution_mode == "technical_ledger_only"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"ready": False}, "protocol_not_ready"),
        ({"technical_ready": False}, "protocol_not_ready"),
        ({"protocol_sha256": "0" * 64}, "protocol_hash_mismatch"),
        ({"dataset_sha256": "0" * 64}, "dataset_hash_mismatch"),
        ({"admitted_fixture_ids": ()}, "fixture_admission_mismatch"),
        ({"call_ceiling": None}, "call_ceiling_mismatch"),
    ],
)
def test_staging_rejects_unbound_admission(client, db_session, change, code) -> None:
    value = protocol()
    report = ready_admission(value).model_copy(update=change)
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.stage_run(db_session, owner_id(client), value, report)
    assert caught.value.code == code


@pytest.mark.parametrize("analysis_budget", [1, 3])
def test_staging_rejects_protocol_budgets_different_from_calculated_ceiling(
    client, db_session, analysis_budget
) -> None:
    value = protocol()
    changed_roles = value.call_budgets.by_role.model_copy(
        update={"analysis": analysis_budget}
    )
    changed_budgets = value.call_budgets.model_copy(update={"by_role": changed_roles})
    forged = value.model_copy(update={"call_budgets": changed_budgets})
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.stage_run(
            db_session, owner_id(client), forged, ready_admission(forged)
        )
    assert caught.value.code == "protocol_budget_mismatch"


def test_per_role_budget_and_idempotency_are_enforced(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    first = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="analysis-1")
    )
    replay = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="analysis-1")
    )
    second = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="analysis-2")
    )
    assert replay.id == first.id
    assert second.sequence_number == first.sequence_number + 1
    snapshot = BenchmarkCallLedger.budget_snapshot(db_session, run.id)
    assert snapshot.reserved == 2
    assert snapshot.consumed_by_role.analysis == 2
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.reserve_call(
            db_session, run.id, declaration(value, key="analysis-3")
        )
    assert caught.value.code == "role_budget_exhausted"
    assert db_session.scalar(
        select(BenchmarkProviderCallAttempt).where(
            BenchmarkProviderCallAttempt.experiment_run_id == run.id
        ).with_only_columns(BenchmarkProviderCallAttempt.id)
    ) is not None
    assert len(
        list(
            db_session.scalars(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run.id
                )
            )
        )
    ) == 2


def test_conflicting_idempotency_key_is_rejected(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    BenchmarkCallLedger.reserve_call(db_session, run.id, declaration(value, key="same"))
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.reserve_call(
            db_session,
            run.id,
            declaration(value, key="same", request_marker="different"),
        )
    assert caught.value.code == "idempotency_conflict"
    assert BenchmarkCallLedger.budget_snapshot(db_session, run.id).reserved == 1


def test_exact_budget_staging_requires_declared_total_equal_to_role_sum(client, db_session) -> None:
    """A frozen protocol must declare total == sum(role ceilings); anything else is rejected.

    ``>=`` is not sufficient: the protocol budget is an exact ceiling, not a floor.
    """

    value = protocol()
    roles = value.call_budgets.by_role.model_dump()
    exact = sum(roles.values())
    too_low = value.model_copy(
        update={"call_budgets": value.call_budgets.model_copy(update={"total": exact - 1})}
    )
    too_high = value.model_copy(
        update={"call_budgets": value.call_budgets.model_copy(update={"total": exact + 1})}
    )
    for candidate in (too_low, too_high):
        with pytest.raises(LedgerError) as caught:
            BenchmarkCallLedger.stage_run(
                db_session, owner_id(client), candidate, ready_admission(candidate)
            )
        assert caught.value.code == "protocol_budget_mismatch"

    # Equal is accepted.
    run = staged_run(db_session, client, value)
    assert run.total_call_ceiling == exact == 12


def test_database_rejects_frozen_run_with_inconsistent_role_and_total_ceilings(
    client, db_session
) -> None:
    """The ceiling-total CHECK constraint is the final backstop for exact budgets."""

    value = protocol()
    run = running_run(db_session, client, value)
    with pytest.raises(IntegrityError):
        db_session.execute(
            update(BenchmarkExperimentRun)
            .where(BenchmarkExperimentRun.id == run.id)
            .values(analysis_call_ceiling=1)
        )
    db_session.rollback()


def test_total_budget_gate_is_independent(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    db_session.execute(
        update(BenchmarkExperimentRun)
        .where(BenchmarkExperimentRun.id == run.id)
        .values(
            analysis_call_ceiling=1,
            question_generation_call_ceiling=0,
            prompt_generation_call_ceiling=0,
            target_execution_call_ceiling=0,
            judge_call_ceiling=0,
            total_call_ceiling=1,
        )
    )
    db_session.commit()
    BenchmarkCallLedger.reserve_call(db_session, run.id, declaration(value, key="one"))
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.reserve_call(
            db_session, run.id, declaration(value, role="prompt_generation", key="two")
        )
    assert caught.value.code == "role_budget_exhausted"
    assert BenchmarkCallLedger.budget_snapshot(db_session, run.id).reserved == 1


def test_concurrent_final_budget_reservations_cannot_both_succeed(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    db_session.execute(
        update(BenchmarkExperimentRun)
        .where(BenchmarkExperimentRun.id == run.id)
        .values(
            analysis_call_ceiling=1,
            question_generation_call_ceiling=0,
            prompt_generation_call_ceiling=0,
            target_execution_call_ceiling=0,
            judge_call_ceiling=0,
            total_call_ceiling=1,
        )
    )
    db_session.commit()
    barrier = threading.Barrier(2)
    successes: list[UUID] = []
    failures: list[str] = []
    lock = threading.Lock()

    def reserve(key: str) -> None:
        with SessionLocal() as db:
            barrier.wait()
            try:
                attempt = BenchmarkCallLedger.reserve_call(
                    db, run.id, declaration(value, key=key)
                )
            except LedgerError as error:
                with lock:
                    failures.append(error.code)
            else:
                with lock:
                    successes.append(attempt.id)

    threads = [threading.Thread(target=reserve, args=(f"race-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0] in {"role_budget_exhausted", "total_budget_exhausted"}
    with SessionLocal() as db:
        attempts = list(
            db.scalars(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run.id
                )
            )
        )
        snapshot = BenchmarkCallLedger.budget_snapshot(db, run.id)
    assert len(attempts) == 1 and snapshot.reserved == 1


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"provider": "different-provider"}, "provider_assignment_mismatch"),
        ({"model": "different-model"}, "provider_assignment_mismatch"),
        ({"parameter_hash": "0" * 64}, "generation_parameter_mismatch"),
        ({"protocol_hash": "0" * 64}, "protocol_hash_mismatch"),
        ({"dataset_hash": "0" * 64}, "dataset_hash_mismatch"),
    ],
)
def test_frozen_bindings_and_hashes_are_enforced(client, db_session, kwargs, code) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.reserve_call(
            db_session, run.id, declaration(value, key=f"bad-{code}", **kwargs)
        )
    assert caught.value.code == code


def test_target_conditions_share_one_frozen_provider_model(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    baseline = BenchmarkCallLedger.reserve_call(
        db_session,
        run.id,
        declaration(value, role="target_execution", condition="baseline", key="target-b"),
    )
    promptpilot = BenchmarkCallLedger.reserve_call(
        db_session,
        run.id,
        declaration(
            value, role="target_execution", condition="promptpilot", key="target-p"
        ),
    )
    assert baseline.configured_provider == promptpilot.configured_provider
    assert baseline.configured_model == promptpilot.configured_model
    assert baseline.generation_parameter_sha256 == promptpilot.generation_parameter_sha256
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.reserve_call(
            db_session,
            run.id,
            declaration(
                value,
                role="target_execution",
                condition="baseline",
                key="target-mismatch",
                model="other-target",
            ),
        )
    assert caught.value.code == "provider_assignment_mismatch"


def test_attempt_lifecycle_usage_cost_cancel_and_snapshot(client, db_session) -> None:
    value = protocol()
    data = value.model_dump(mode="python")
    data["monetary_budget"] = {
        "currency": "USD",
        "maximum_cost": 10,
        "pricing_snapshot_reference": "unverified-unit-test://pricing",
    }
    value = LiveStudyProtocol.model_validate(data)
    run = running_run(db_session, client, value)
    succeeded = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="success", estimated_cost=0.01, currency="USD")
    )
    reserved_snapshot = BenchmarkCallLedger.budget_snapshot(db_session, run.id)
    assert reserved_snapshot.spent_amount == 0
    assert reserved_snapshot.remaining_spend == pytest.approx(9.99)
    assert db_session.get(BenchmarkExperimentRun, run.id).reserved_spend == pytest.approx(0.01)
    BenchmarkCallLedger.mark_started(db_session, succeeded.id)
    succeeded = BenchmarkCallLedger.mark_succeeded(
        db_session,
        succeeded.id,
        AttemptSuccess(
            input_tokens=2,
            output_tokens=3,
            total_tokens=5,
            cost_estimate=0.01,
            currency="USD",
            response_artifact_sha256=canonical_artifact_sha256({"response": "safe"}),
        ),
    )
    assert succeeded.status == "succeeded" and succeeded.total_tokens == 5
    settled_snapshot = BenchmarkCallLedger.budget_snapshot(db_session, run.id)
    assert settled_snapshot.spent_amount == pytest.approx(0.01)
    assert settled_snapshot.remaining_spend == pytest.approx(9.99)
    assert db_session.get(BenchmarkExperimentRun, run.id).reserved_spend == 0

    cancelled = BenchmarkCallLedger.reserve_call(
        db_session,
        run.id,
        declaration(value, key="cancel", estimated_cost=0.02, currency="USD"),
    )
    BenchmarkCallLedger.cancel_reservation(db_session, cancelled.id)
    snapshot = BenchmarkCallLedger.budget_snapshot(db_session, run.id)
    assert snapshot.reserved == 0
    assert snapshot.succeeded == 1 and snapshot.cancelled == 1
    assert snapshot.consumed_by_role.analysis == 1
    assert snapshot.spent_amount == pytest.approx(0.01)
    assert snapshot.remaining_spend == pytest.approx(9.99)
    assert db_session.get(BenchmarkExperimentRun, run.id).reserved_spend == 0


def test_failed_started_call_conservatively_settles_reserved_cost(client, db_session) -> None:
    value = protocol()
    data = value.model_dump(mode="python")
    data["monetary_budget"] = {
        "currency": "USD",
        "maximum_cost": 10,
        "pricing_snapshot_reference": "unverified-unit-test://pricing",
    }
    value = LiveStudyProtocol.model_validate(data)
    run = running_run(db_session, client, value)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session,
        run.id,
        declaration(value, key="failed-cost", estimated_cost=0.25, currency="USD"),
    )
    BenchmarkCallLedger.mark_started(db_session, attempt.id)
    BenchmarkCallLedger.mark_failed_from_exception(
        db_session,
        attempt.id,
        RuntimeError("offline test failure"),
        safe_error_code="provider_unavailable",
    )

    snapshot = BenchmarkCallLedger.budget_snapshot(db_session, run.id)
    assert snapshot.spent_amount == pytest.approx(0.25)
    assert snapshot.remaining_spend == pytest.approx(9.75)
    assert db_session.get(BenchmarkExperimentRun, run.id).reserved_spend == 0


def test_invalid_transitions_terminal_runs_and_finalize_consistency(client, db_session) -> None:
    value = protocol()
    staged = staged_run(db_session, client, value)
    with pytest.raises(LedgerError, match="not running"):
        BenchmarkCallLedger.reserve_call(
            db_session, staged.id, declaration(value, key="too-early")
        )
    BenchmarkCallLedger.start_run(db_session, staged.id)
    with pytest.raises(LedgerError):
        BenchmarkCallLedger.start_run(db_session, staged.id)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, staged.id, declaration(value, key="reserved")
    )
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.finalize_run(db_session, staged.id)
    assert caught.value.code == "inconsistent_ledger"
    BenchmarkCallLedger.abort_run(db_session, staged.id, "study_abort")
    with pytest.raises(LedgerError, match="not running"):
        BenchmarkCallLedger.reserve_call(
            db_session, staged.id, declaration(value, key="after-abort")
        )
    assert db_session.get(BenchmarkProviderCallAttempt, attempt.id).status == "cancelled"

    completed = running_run(db_session, client, value)
    BenchmarkCallLedger.finalize_run(db_session, completed.id)
    with pytest.raises(LedgerError, match="not running"):
        BenchmarkCallLedger.reserve_call(
            db_session, completed.id, declaration(value, key="after-complete")
        )


def test_failure_is_safe_and_never_stores_exception_message(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="failure")
    )
    BenchmarkCallLedger.mark_started(db_session, attempt.id)
    secret = "Authorization: Bearer never-store-this"
    failed = BenchmarkCallLedger.mark_failed_from_exception(
        db_session,
        attempt.id,
        RuntimeError(secret),
        safe_error_code="provider_unavailable",
    )
    assert failed.status == "failed"
    assert failed.safe_error_type == "RuntimeError"
    assert failed.safe_error_code == "provider_unavailable"
    assert secret not in json.dumps(
        {
            column.name: getattr(failed, column.name)
            for column in BenchmarkProviderCallAttempt.__table__.columns
        },
        default=str,
    )
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.finalize_run(db_session, run.id)
    assert caught.value.code == "inconsistent_ledger"
    BenchmarkCallLedger.fail_run(db_session, run.id, "provider_failure")


@pytest.mark.parametrize(
    "success",
    [
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"total_tokens": -1},
        {"cost_estimate": float("nan"), "currency": "USD"},
        {"cost_estimate": float("inf"), "currency": "USD"},
        {"cost_estimate": float("-inf"), "currency": "USD"},
    ],
)
def test_negative_usage_and_non_finite_cost_are_rejected(success) -> None:
    with pytest.raises(ValidationError):
        AttemptSuccess.model_validate(success)


def test_mismatched_currency_and_duplicate_completion_are_rejected(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="currency")
    )
    BenchmarkCallLedger.mark_started(db_session, attempt.id)
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.mark_succeeded(
            db_session,
            attempt.id,
            AttemptSuccess(cost_estimate=0.1, currency="USD"),
        )
    assert caught.value.code == "currency_mismatch"
    completed = BenchmarkCallLedger.mark_succeeded(
        db_session, attempt.id, AttemptSuccess()
    )
    assert completed.status == "succeeded"
    with pytest.raises(LedgerError) as duplicate:
        BenchmarkCallLedger.mark_succeeded(db_session, attempt.id, AttemptSuccess())
    assert duplicate.value.code == "invalid_attempt_transition"


def test_credential_like_declarations_are_rejected_without_echo() -> None:
    value = protocol()
    raw = declaration(value).model_dump(mode="python")
    raw["configured_provider"] = "https://user:password@example.test/model"
    with pytest.raises(ValidationError) as caught:
        ReservationDeclaration.model_validate(raw)
    assert "password" not in str(caught.value).casefold()


def test_attempt_identity_is_immutable(client, db_session) -> None:
    value = protocol()
    run = running_run(db_session, client, value)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="immutable")
    )
    attempt.configured_model = "mutated-model"
    with pytest.raises(ValueError, match="identity is immutable"):
        db_session.commit()
    db_session.rollback()


def test_ledger_never_constructs_or_calls_a_provider(monkeypatch, client, db_session) -> None:
    from promptpilot_backend import llm_provider

    def forbidden_provider(*args, **kwargs):
        raise AssertionError("provider construction is forbidden")

    monkeypatch.setattr(llm_provider.OpenAICompatibleProvider, "__init__", forbidden_provider)
    value = protocol()
    run = running_run(db_session, client, value)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="no-provider")
    )
    assert attempt.status == "reserved"


def test_terminal_run_rejects_reservation_before_any_provider_invocation(
    client, db_session
) -> None:
    """Post-terminal reservations must fail at the ledger boundary, never reach a provider."""

    value = protocol()
    run = running_run(db_session, client, value)
    assert run.status == "running"
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="pre-terminal")
    )
    BenchmarkCallLedger.mark_started(db_session, attempt.id)
    BenchmarkCallLedger.mark_failed_from_exception(
        db_session, attempt.id, RuntimeError("safe"), safe_error_code="provider_failure"
    )
    BenchmarkCallLedger.fail_run(db_session, run.id, "provider_failure")
    terminal = BenchmarkCallLedger._require_run(db_session, run.id)
    assert terminal.status == "failed"
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.reserve_call(
            db_session, run.id, declaration(value, key="after-terminal")
        )
    assert caught.value.code == "run_not_running"


def test_termination_is_claimed_atomically_and_blocks_concurrent_reservations(
    client, db_session
) -> None:
    """Termination uses a conditional UPDATE; a reservation claimed before it stays valid."""

    import threading

    value = protocol()
    run = running_run(db_session, client, value)
    barrier = threading.Barrier(2)
    reserved_before: list[UUID] = []
    rejected_after: list[str] = []
    lock = threading.Lock()

    def reserve_first() -> None:
        with SessionLocal() as db:
            barrier.wait()
            try:
                attempt = BenchmarkCallLedger.reserve_call(
                    db, run.id, declaration(value, key="pre-terminate")
                )
            except LedgerError as error:
                with lock:
                    rejected_after.append(error.code)
            else:
                with lock:
                    reserved_before.append(attempt.id)

    def terminate_after() -> None:
        with SessionLocal() as db:
            barrier.wait()
            try:
                BenchmarkCallLedger.fail_run(db, run.id, "study_failure")
            except LedgerError as error:
                with lock:
                    rejected_after.append(error.code)

    threads = [
        threading.Thread(target=reserve_first),
        threading.Thread(target=terminate_after),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert len(reserved_before) + len(rejected_after) == 1
    with SessionLocal() as db:
        run_state = db.get(BenchmarkExperimentRun, run.id)
        attempts = list(
            db.scalars(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run.id
                )
            )
        )
    assert run_state.status in {"failed", "aborted"}
    if reserved_before:
        # Reservation claimed before termination remains valid and accounted for.
        assert any(attempt.id in reserved_before for attempt in attempts)
        assert all(attempt.status in {"reserved", "started", "cancelled"} for attempt in attempts)
    else:
        # Termination won the race: the concurrent reservation was rejected.
        assert any(code in rejected_after for code in {"run_not_running", "reservation_conflict"})
        assert all(attempt.status == "cancelled" for attempt in attempts)


def test_forged_readiness_cannot_stage_a_run(client, db_session) -> None:
    """A caller cannot bypass budget ceilings or required counts by declaring ready=True."""

    value = protocol()
    ceiling = calculate_call_ceiling(value)
    forged = ready_admission(value).model_copy(update={"ready": False, "technical_ready": False})
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.stage_run(db_session, owner_id(client), value, forged)
    assert caught.value.code == "protocol_not_ready"

    inflated = value.model_copy(
        update={
            "call_budgets": value.call_budgets.model_copy(
                update={
                    "by_role": value.call_budgets.by_role.model_copy(
                        update={"analysis": ceiling.by_role.analysis + 10}
                    ),
                    "total": ceiling.total + 10,
                }
            )
        }
    )
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.stage_run(
            db_session, owner_id(client), inflated, ready_admission(inflated)
        )
    assert caught.value.code == "protocol_budget_mismatch"

    under_sized = value.model_copy(update={"repetitions": 1})
    with pytest.raises(LedgerError) as caught:
        BenchmarkCallLedger.stage_run(
            db_session, owner_id(client), under_sized, ready_admission(under_sized)
        )
    assert caught.value.code == "protocol_budget_mismatch"


def test_provider_call_boundary_reserves_before_invocation(client, db_session) -> None:
    """Reservation must precede any provider interaction; a failed call is still accounted."""

    value = protocol()
    run = running_run(db_session, client, value)
    attempt = BenchmarkCallLedger.reserve_call(
        db_session, run.id, declaration(value, key="boundary")
    )
    assert attempt.status == "reserved"
    BenchmarkCallLedger.mark_started(db_session, attempt.id)
    # Simulate a provider failure: the reservation is consumed and auditable.
    failed = BenchmarkCallLedger.mark_failed_from_exception(
        db_session,
        attempt.id,
        ProviderUnavailable("synthetic provider failure"),
        safe_error_code="provider_unavailable",
    )
    assert failed.status == "failed"
    assert failed.observation_outcome == "failed"
    assert failed.safe_error_type == "ProviderUnavailable"
    snapshot = BenchmarkCallLedger.budget_snapshot(db_session, run.id)
    assert snapshot.failed == 1 and snapshot.reserved == 0
