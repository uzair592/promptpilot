"""Regression tests protecting invariants discovered during the PR #10 audit.

Each test protects a real code-path invariant, not a comment: the
launch gate, provider authorization, spending authorization, fixture
eligibility, baseline isolation, judge blinding, judge failure
handling, monetary budget, settled cost, and export immutability.
"""

import copy
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import (
    EXPERIMENT_DATASET,
    EXPERIMENT_MANIFEST,
    bind_offline_fixture,
    experiment_owner,
    protocol_payload,
    technical_admission,
)

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_call_ledger import (
    AttemptSuccess,
    BenchmarkCallLedger,
    BudgetSnapshot,
    LedgerError,
    ReservationDeclaration,
    RoleCallBudget,
)
from promptpilot_backend.benchmark_experiment_authorization import (
    LaunchGateBlocker,
    LaunchGateReport,
)
from promptpilot_backend.benchmark_experiment_execution import (
    EXECUTION_MODES,
    ExecutionGateError,
    ExecutionMode,
    ProviderCallExecutor,
    verify_fixture_before_target_execution,
)
from promptpilot_backend.benchmark_experiment_results import (
    build_export,
    load_export_lock,
    write_export,
)
from promptpilot_backend.benchmark_fixtures import (
    FixtureManifest,
    manifest_sha256,
)
from promptpilot_backend.benchmark_live_runner import (
    LedgerGate,
    LedgerGatedExecutionProvider,
)
from promptpilot_backend.benchmark_provider_adapter import OfflineProviderAdapter
from promptpilot_backend.benchmark_stop_rules import StopRuleEvaluator
from promptpilot_backend.db import SessionLocal
from promptpilot_backend.evaluation_service import ResponseEvaluationService
from promptpilot_backend.models import (
    BenchmarkExperimentRun,
    Message,
    ModelRun,
)
from promptpilot_backend.production_benchmark_protocol import LiveStudyProtocol
from promptpilot_backend.schemas import LLMJudgeOutput, ResponseScore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ready_gate_report(**overrides) -> LaunchGateReport:
    """An internally consistent launch-gate report claiming readiness."""

    fields: dict = {
        "protocol_locked": True,
        "admission_ready": True,
        "fixtures_live_eligible": True,
        "fixture_ids": ("fixture-a",),
        "authorization_present": True,
        "authorization_binds_protocol": True,
        "provider_authorized": True,
        "spending_authorized": True,
        "provider_model_authorized": True,
        "budget_authorized": True,
        "pricing_snapshot_valid": True,
        "provider_configuration_valid": True,
        "technical_ready": True,
        "ready": True,
        "blockers": (),
        "software_verification_limit": "test limit",
    }
    fields.update(overrides)
    return LaunchGateReport(**fields)


class _RecordingProvider:
    """A provider that records every invocation."""

    offline_fixture = True

    def __init__(self) -> None:
        self.calls: list = []

    def generate(self, prompt, parameters=None):
        self.calls.append((prompt, parameters))
        return {
            "content": "recorded",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "cost_estimate": 0.0,
            "currency": "USD",
            "response_metadata": {"finish_reason": "stop"},
        }


class _CapturingTargetAdapter(OfflineProviderAdapter):
    """An offline target adapter that records the exact provider request."""

    def __init__(self, provider_name: str, model_name: str) -> None:
        super().__init__("target_execution", provider_name, model_name)
        self.captured: list[tuple[str, dict]] = []

    def generate(self, prompt, parameters=None):
        self.captured.append((prompt, parameters))
        return super().generate(prompt, parameters)


class _FailingJudge:
    name = "judge-provider"
    model = "judge-model"

    def judge_response(self, task, response_a, response_b, evidence=None):
        raise ValueError("judge unavailable")


class _CapturingJudge:
    name = "judge-provider"
    model = "judge-model"

    def __init__(self) -> None:
        self.calls: list = []

    def judge_response(self, task, response_a, response_b, evidence=None):
        self.calls.append((task, response_a, response_b, evidence))
        return LLMJudgeOutput(
            response_a=ResponseScore(
                relevance=10,
                completeness=10,
                instruction_following=10,
                contextual_grounding=10,
                clarity=10,
            ),
            response_b=ResponseScore(
                relevance=90,
                completeness=90,
                instruction_following=90,
                contextual_grounding=90,
                clarity=90,
            ),
        )


def _budgeted_protocol_payload() -> dict:
    """The synthetic protocol with a monetary budget attached."""

    payload = copy.deepcopy(protocol_payload())
    payload["monetary_budget"] = {
        "currency": "USD",
        "maximum_cost": 10.0,
        "pricing_snapshot_reference": "https://pricing.example/snapshot",
    }
    return payload


def _stage_budgeted_run(client, tmp_path) -> UUID:
    """Stage and start a run whose protocol carries a monetary budget."""

    owner = experiment_owner(client)
    manifest_payload = json.loads(EXPERIMENT_MANIFEST.read_text(encoding="utf-8"))
    manifest_payload.update(
        {
            "project_facts": [],
            "clarification_answers": [],
            "frozen_documents": [],
            "evaluation_only": [],
        }
    )
    frozen = _budgeted_protocol_payload()
    selection = frozen["selected_fixtures"][0]
    manifest_payload["fixture_id"] = selection["fixture_id"]
    manifest = FixtureManifest.model_validate(manifest_payload)
    manifest_path = tmp_path / "budgeted_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    digest = manifest_sha256(manifest)
    selection["manifest_path"] = manifest_path.name
    selection["manifest_sha256"] = digest
    selection["attestation"]["fixture_id"] = selection["fixture_id"]
    selection["attestation"]["manifest_sha256"] = digest
    protocol = LiveStudyProtocol.model_validate(frozen)
    with SessionLocal() as session:
        run = BenchmarkCallLedger.stage_run(
            session, owner, protocol, technical_admission(protocol)
        )
        BenchmarkCallLedger.start_run(session, run.id)
        return run.id


def _run_frozen(run_id) -> tuple[str, str, dict]:
    """Return the run's frozen protocol hash, dataset hash, and role bindings."""

    with SessionLocal() as db:
        run = db.get(BenchmarkExperimentRun, run_id)
        assert run is not None
        return (
            run.protocol_sha256,
            run.dataset_sha256,
            json.loads(run.frozen_role_bindings_json),
        )


def _declaration(
    run_id, role="analysis", estimated_cost=None, currency=None
):
    protocol_sha256, dataset_sha256, bindings = _run_frozen(run_id)
    binding = bindings[role]
    return ReservationDeclaration(
        stable_unit_id="unit-1",
        fixture_id="fixture-1",
        task_id="task-1",
        repetition=1,
        provider_role=role,
        target_condition=None,
        idempotency_key=f"idem-{uuid4()}",
        configured_provider=binding["provider"],
        configured_model=binding["model"],
        generation_parameter_sha256=binding["generation_parameter_sha256"],
        request_artifact_sha256="1" * 64,
        protocol_sha256=protocol_sha256,
        dataset_sha256=dataset_sha256,
        estimated_cost=estimated_cost,
        currency=currency,
    )


def _register_pair(client):
    """Create a project, conversation, source message and paired runs."""

    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "audit@example.com",
                "display_name": "Audit User",
                "password": "correct horse battery",
            },
        ).status_code
        == 201
    )
    project = client.post("/api/v1/projects", json={"name": "Audit Project"}).json()
    conversation = client.post(
        f"/api/v1/projects/{project['id']}/conversations",
        json={"title": "Audit conversation"},
    ).json()
    with SessionLocal() as db:
        message = Message(
            conversation_id=UUID(conversation["id"]),
            role="user",
            content="Explain the audit task.",
            sequence=1,
        )
        db.add(message)
        db.flush()
        baseline = ModelRun(
            project_id=UUID(project["id"]),
            conversation_id=UUID(conversation["id"]),
            source_message_id=message.id,
            execution_strategy="baseline",
            optimized_prompt=message.content,
            response_text="The first response text.",
            provider="deterministic",
            model="fixture",
            status="succeeded",
        )
        promptpilot = ModelRun(
            project_id=UUID(project["id"]),
            conversation_id=UUID(conversation["id"]),
            source_message_id=message.id,
            execution_strategy="promptpilot",
            optimized_prompt=message.content + " Include extra context.",
            response_text="The second response text.",
            provider="deterministic",
            model="fixture",
            status="succeeded",
        )
        db.add_all([baseline, promptpilot])
        db.commit()
        return (
            project["id"],
            conversation["id"],
            str(baseline.id),
            str(promptpilot.id),
        )


def _export_unit() -> object:
    from promptpilot_backend.benchmark_experiment_results import ExperimentUnit

    return ExperimentUnit(
        execution_mode="offline_dry_run",
        unit_id="unit-1",
        task_id="task-1",
        task_category="general",
        repetition=1,
        fixture_id="fixture-1",
        fixture_manifest_sha256="4" * 64,
        dataset_name="dataset",
        dataset_sha256="5" * 64,
        protocol_id="protocol-1",
        protocol_sha256="6" * 64,
        disposition="complete_pair",
        condition_order=("baseline", "promptpilot"),
        fallback_state="none",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# 1. Documentation / runtime execution-mode consistency
# ---------------------------------------------------------------------------


def test_operations_doc_matches_runtime_execution_modes():
    doc = (
        Path(__file__).resolve().parents[3]
        / "docs/research/live-runner-operations-v1.md"
    )
    text = doc.read_text(encoding="utf-8")

    # The document must describe both execution modes that exist in code.
    assert "offline_dry_run" in text
    assert "`live`" in text
    # The document must describe the live runner and executor that exist.
    assert "LiveExperimentRunner" in text
    assert "ProviderCallExecutor" in text
    # The document must not contain stale claims contradicted by the code.
    for stale in (
        "does NOT enable live execution",
        "No live runner",
        "No real provider adapter",
        "exactly one member",
        "next milestone implements live runner",
        "No live runner, no CLI entrypoint",
    ):
        assert stale not in text, f"stale claim present: {stale!r}"

    # The runtime must expose exactly the two modes the document describes.
    assert set(EXECUTION_MODES) == {"offline_dry_run", "live"}
    assert set(ExecutionMode.__args__) == {"offline_dry_run", "live"}


# ---------------------------------------------------------------------------
# 2-4. Launch gate / provider authorization / spending authorization
# ---------------------------------------------------------------------------


def test_launch_gate_failure_prevents_provider_invocation(experiment_env):
    report = _ready_gate_report(ready=False, blockers=(LaunchGateBlocker(
        code="human_admission_unverified", message="unverified",
    ),))
    provider = _RecordingProvider()

    with pytest.raises(ExecutionGateError) as caught:
        ProviderCallExecutor(
            SessionLocal(),
            experiment_env.run_id,
            experiment_env.binding,
            execution_mode="live",
            launch_gate_report=report,
        )

    assert caught.value.code == "launch_gate_not_passed"
    # The executor was never constructed, so execute() was never reached
    # and the provider was never invoked.
    assert provider.calls == []


def test_provider_authorization_mismatch_prevents_provider_invocation(experiment_env):
    report = _ready_gate_report(provider_authorized=False)
    provider = _RecordingProvider()

    with pytest.raises(ExecutionGateError) as caught:
        ProviderCallExecutor(
            SessionLocal(),
            experiment_env.run_id,
            experiment_env.binding,
            execution_mode="live",
            launch_gate_report=report,
        )

    assert caught.value.code == "launch_gate_inconsistent"
    assert provider.calls == []


def test_spending_authorization_missing_prevents_provider_invocation(experiment_env):
    report = _ready_gate_report(spending_authorized=False)
    provider = _RecordingProvider()

    with pytest.raises(ExecutionGateError) as caught:
        ProviderCallExecutor(
            SessionLocal(),
            experiment_env.run_id,
            experiment_env.binding,
            execution_mode="live",
            launch_gate_report=report,
        )

    assert caught.value.code == "launch_gate_inconsistent"
    assert provider.calls == []


# ---------------------------------------------------------------------------
# 5. Fixture becomes ineligible immediately before target execution
# ---------------------------------------------------------------------------


def test_fixture_ineligible_before_target_execution_blocks_target_call(tmp_path):
    binding, protocol = bind_offline_fixture(tmp_path)
    dataset = load_dataset(EXPERIMENT_DATASET)
    manifest = FixtureManifest.model_validate(
        json.loads(
            (tmp_path / "bound_manifest.json").read_text(encoding="utf-8")
        )
    )
    manifest_path = tmp_path / "bound_manifest.json"
    fixture_id = protocol.selected_fixtures[0].fixture_id

    # The synthetic fixture is permanently not live-eligible, so a live
    # target call must be blocked at the re-verification boundary.
    with pytest.raises(ExecutionGateError) as caught:
        verify_fixture_before_target_execution(
            binding=binding,
            fixture_id=fixture_id,
            manifest=manifest,
            dataset=dataset,
            manifest_path=manifest_path,
            execution_mode="live",
        )
    assert caught.value.code == "fixture_not_live_eligible"

    # The stop-rule evaluator wired into the live runner reaches the same
    # fail-closed decision before the target provider is reached.
    evaluator = StopRuleEvaluator(protocol, binding, None, dataset=dataset)
    snapshot = BudgetSnapshot(
        run_id=uuid4(),
        status="running",
        ceilings=RoleCallBudget(
            analysis=24,
            question_generation=48,
            prompt_generation=24,
            target_execution=48,
            judge=24,
        ),
        total_ceiling=168,
        consumed_by_role=RoleCallBudget(
            analysis=0,
            question_generation=0,
            prompt_generation=0,
            target_execution=0,
            judge=0,
        ),
        reserved=0,
        succeeded=0,
        failed=0,
        cancelled=0,
        remaining_by_role=RoleCallBudget(
            analysis=24,
            question_generation=48,
            prompt_generation=24,
            target_execution=48,
            judge=24,
        ),
        remaining_total=168,
        max_spend=None,
        spent_amount=0.0,
        spent_currency=None,
        budget_currency=None,
        remaining_spend=None,
    )
    decision = evaluator.evaluate_before_target_execution(
        unit_id="unit-1",
        task_id="task-1",
        fixture_id=fixture_id,
        repetition=1,
        condition_order=("baseline", "promptpilot"),
        target_provider=binding.target_provider,
        target_model=binding.target_model,
        target_parameters={},
        fixture_manifest=manifest,
        dataset=dataset,
        manifest_path=manifest_path,
        protocol=protocol,
        budget_snapshot=snapshot,
        launch_gate_passed=True,
    )
    assert decision.should_stop is True
    assert decision.reason_code.value == "fixture_not_live_eligible"


# ---------------------------------------------------------------------------
# 6-7. Baseline isolation at the actual provider boundary
# ---------------------------------------------------------------------------


def _run_baseline_through_provider_boundary(experiment_env, original_task):
    """Execute one baseline target call and return the captured request."""

    binding = experiment_env.binding
    protocol = experiment_env.protocol
    adapter = _CapturingTargetAdapter(
        binding.target_provider, binding.target_model
    )
    executor = ProviderCallExecutor(
        SessionLocal(), experiment_env.run_id, binding, execution_mode="offline_dry_run"
    )
    stop_evaluator = StopRuleEvaluator(protocol, binding, None)
    gate = LedgerGate(
        executor=executor,
        stop_evaluator=stop_evaluator,
        unit_id="unit-1",
        task_id="task-1",
        fixture_id=protocol.selected_fixtures[0].fixture_id,
        repetition=1,
    )
    provider = LedgerGatedExecutionProvider(gate, adapter, "baseline")
    params = binding.target_parameters
    target_parameters = {
        "temperature": params.temperature,
        "max_tokens": params.max_tokens,
        "top_p": params.top_p,
        "seed": params.seed,
        "stop": list(params.stop),
        "presence_penalty": params.presence_penalty,
        "frequency_penalty": params.frequency_penalty,
    }
    provider.generate_response(
        {
            "prompt": original_task,
            "system_instruction": None,
            "parameters": target_parameters,
        }
    )
    return adapter, target_parameters


def test_baseline_payload_is_exactly_the_original_task(experiment_env):
    original_task = "Create a practical plan for launching a small community workshop."
    adapter, target_parameters = _run_baseline_through_provider_boundary(
        experiment_env, original_task
    )

    assert len(adapter.captured) == 1
    captured_prompt, captured_parameters = adapter.captured[0]
    # The target provider receives exactly the original task and nothing else.
    assert captured_prompt == original_task
    assert captured_parameters == target_parameters


def test_treatment_artifacts_cannot_enter_baseline_request(experiment_env):
    original_task = "Create a practical plan for launching a small community workshop."
    adapter, _ = _run_baseline_through_provider_boundary(
        experiment_env, original_task
    )
    captured_prompt, _ = adapter.captured[0]

    # No PromptPilot treatment artifact may be appended to the baseline prompt.
    assert captured_prompt == original_task
    for artifact in (
        "analysis",
        "question",
        "answer",
        "memory",
        "document",
        "retrieved",
        "context",
        "optimized",
        "PromptVersion",
        "treatment",
    ):
        assert artifact.lower() not in captured_prompt.lower()


# ---------------------------------------------------------------------------
# 8-9. Judge blinding and judge failure handling
# ---------------------------------------------------------------------------


def test_judge_receives_blinded_ab_labels(client):
    project_id, conversation_id, baseline_id, promptpilot_id = _register_pair(client)
    judge = _CapturingJudge()

    with SessionLocal() as db:
        ResponseEvaluationService(
            judge_provider=judge, assignment=lambda: True
        ).evaluate_pair(
            db,
            UUID(conversation_id),
            UUID(baseline_id),
            UUID(promptpilot_id),
            "Explain the audit task.",
            "llm_judge",
        )

    assert len(judge.calls) == 1
    task, response_a, response_b, evidence = judge.calls[0]
    # The judge receives the two response texts under neutral labels, never
    # the condition identity.
    assert {response_a, response_b} == {
        "The first response text.",
        "The second response text.",
    }
    assert "baseline" not in response_a.lower()
    assert "promptpilot" not in response_a.lower()
    assert "baseline" not in response_b.lower()
    assert "promptpilot" not in response_b.lower()
    # The judge's own evidence carries only neutral A/B response text.
    assert evidence["response_a"] == response_a
    assert evidence["response_b"] == response_b
    assert "condition" not in evidence
    assert "strategy" not in evidence


def test_judge_failure_cannot_produce_a_successful_evaluation(client):
    project_id, conversation_id, baseline_id, promptpilot_id = _register_pair(client)

    with SessionLocal() as db:
        service = ResponseEvaluationService(
            judge_provider=_FailingJudge(), assignment=lambda: True
        )
        # A judge failure must surface as a failure, never as a successful
        # evaluation with fabricated scores. The original exception type
        # propagates; it is never swallowed into a fabricated result.
        with pytest.raises(ValueError):
            service.evaluate_pair(
                db,
                UUID(conversation_id),
                UUID(baseline_id),
                UUID(promptpilot_id),
                "Explain the audit task.",
                "llm_judge",
            )
        assert (
            db.query(ModelRun).filter(
                ModelRun.id.in_([UUID(baseline_id), UUID(promptpilot_id)])
            ).count()
            == 2
        )


# ---------------------------------------------------------------------------
# 10-11. Monetary budget enforcement
# ---------------------------------------------------------------------------


def test_monetary_budget_cannot_be_exceeded_under_concurrent_reservation(
    client, tmp_path
):
    run_id = _stage_budgeted_run(client, tmp_path)
    # Two concurrent reservations each estimate 6.0 against a 10.0 budget,
    # so at most one can be accepted.
    declarations = [
        _declaration(run_id, estimated_cost=6.0, currency="USD") for _ in range(2)
    ]
    outcomes: list = []
    barrier = threading.Barrier(2)

    def reserve(declaration):
        barrier.wait()
        with SessionLocal() as db:
            try:
                BenchmarkCallLedger.reserve_call(db, run_id, declaration)
                outcomes.append("reserved")
            except LedgerError as error:
                outcomes.append(error.code)

    threads = [threading.Thread(target=reserve, args=(d,)) for d in declarations]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("reserved") == 1
    assert outcomes.count("monetary_budget_exhausted") == 1


def test_settled_cost_cannot_exceed_reserved_cost(client, tmp_path):
    run_id = _stage_budgeted_run(client, tmp_path)
    declaration = _declaration(run_id, estimated_cost=5.0, currency="USD")

    with SessionLocal() as db:
        attempt = BenchmarkCallLedger.reserve_call(db, run_id, declaration)
        BenchmarkCallLedger.mark_started(db, attempt.id)
        # The settled cost (6.0) exceeds the reserved cost (5.0), so the
        # settlement must be rejected rather than silently overspending.
        with pytest.raises(LedgerError) as caught:
            BenchmarkCallLedger.mark_succeeded(
                db,
                attempt.id,
                AttemptSuccess(
                    input_tokens=1,
                    output_tokens=1,
                    total_tokens=2,
                    cost_estimate=6.0,
                    currency="USD",
                ),
            )
        assert caught.value.code == "actual_cost_exceeds_reservation"


# ---------------------------------------------------------------------------
# 12. Export immutability
# ---------------------------------------------------------------------------


def test_export_tampering_is_detected_by_export_lock(tmp_path):
    export = build_export(
        units=(_export_unit(),),
        protocol_id="protocol-1",
        protocol_sha256="6" * 64,
        dataset_name="dataset",
        dataset_sha256="5" * 64,
        execution_mode="offline_dry_run",
        call_ceiling_total=168,
    )
    path = tmp_path / "export.json"
    lock = write_export(export, path)

    # The lock verifies the untouched bytes.
    assert lock.verify_file(path) is not None

    # Tamper with the exported JSON bytes after writing.
    original = path.read_bytes()
    tampered = original.replace(b'"unit-1"', b'"unit-tampered"')
    assert tampered != original
    path.write_bytes(tampered)

    # The lock must reject the tampered file.
    with pytest.raises(ValueError, match="does not match the export file bytes"):
        lock.verify_file(path)

    # A freshly loaded lock also rejects the tampered bytes.
    reloaded = load_export_lock(path)
    with pytest.raises(ValueError, match="does not match the export file bytes"):
        reloaded.verify_file(path)
