"""Ledger-gated execution, dry-run planning, export, and analysis coverage."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from conftest import EXPERIMENT_TASK_IDS as TASK_IDS
from sqlalchemy import select

from promptpilot_backend.benchmark_call_ledger import (
    LedgerError,
    canonical_artifact_sha256,
)
from promptpilot_backend.benchmark_experiment_analysis import (
    PRIMARY_STRATA,
    aggregate_units,
    frozen_study_call_ceiling,
    plan_dry_run,
)
from promptpilot_backend.benchmark_experiment_binding import (
    ProtocolBinding,
    assert_target_parameters_identical,
)
from promptpilot_backend.benchmark_experiment_execution import (
    BaselineProtectionError,
    ExecutionGateError,
    ProviderCallExecutor,
)
from promptpilot_backend.benchmark_experiment_results import (
    EvaluationArtifact,
    ExperimentUnit,
    HumanReviewPlan,
    HumanReviewRecord,
    HumanReviewSampleSlot,
    QuestionArtifact,
    build_export,
    load_export,
    load_export_lock,
    lock_export,
    write_export,
)
from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import BenchmarkProviderCallAttempt

DATASET_SHA = "8b7aca964ffae59151a3c8c24a3412823b7d96ff7739d66e9b79ab71648cc53d"
PROTOCOL_SHA = "a" * 64


class OfflineProvider:
    offline_fixture = True
    name = "offline-engine"
    model = "offline-engine-model"

    def __init__(self, payload: object | None = None) -> None:
        self.payload = payload if payload is not None else {"ok": True}
        self.calls = 0

    def invoke(self) -> object:
        self.calls += 1
        return self.payload


class ExplodingProvider(OfflineProvider):
    def invoke(self) -> object:
        self.calls += 1
        raise RuntimeError("simulated offline provider failure")


class NotMarkedOffline:
    name = "unmarked"

    def invoke(self) -> object:  # pragma: no cover - must never run
        raise AssertionError("must never be invoked")


def make_executor(env) -> ProviderCallExecutor:
    return ProviderCallExecutor(SessionLocal(), env.run_id, env.binding)


# --------------------------------------------------------------------------
# Provider-call execution gate
# --------------------------------------------------------------------------


def test_executor_refuses_unmarked_offline_provider(experiment_env) -> None:
    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    with pytest.raises(ExecutionGateError) as caught:
        executor.execute(
            provider=NotMarkedOffline(),
            role="analysis",
            stable_unit_id="task#r1",
            task_id="planning-launch-001",
            fixture_id=executor.binding.fixture_bindings[0].fixture_id,
            repetition=1,
            provider_name="offline-test",
            model_name="analysis-test-model",
            request_payload={"p": 1},
            invoke=lambda: {"ok": True},
            stable_token="unit1:analysis",
        )
    assert caught.value.code == "provider_not_offline"
    _assert_no_attempts(run_id)


def test_executor_rejects_a_live_execution_mode() -> None:
    with pytest.raises(ExecutionGateError) as caught:
        ProviderCallExecutor(
            SessionLocal(), UUID(int=0), ProtocolBinding.model_construct(), execution_mode="live"
        )
    assert caught.value.code == "unsupported_execution_mode"


def test_executor_accounts_a_successful_call(experiment_env) -> None:
    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    provider = OfflineProvider()
    call = executor.execute(
        provider=provider,
        role="analysis",
        stable_unit_id="task#r1",
        task_id="planning-launch-001",
        fixture_id=executor.binding.fixture_bindings[0].fixture_id,
        repetition=1,
        provider_name="offline-test",
        model_name="analysis-test-model",
        request_payload={"p": 1},
        invoke=provider.invoke,
        stable_token="unit1:analysis",
    )
    assert call.status == "succeeded"
    assert provider.calls == 1
    assert call.request_sha256 == canonical_artifact_sha256({"p": 1})
    _assert_attempt(run_id, "analysis", "succeeded")


def test_executor_marks_provider_failure_without_retry(experiment_env) -> None:
    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    provider = ExplodingProvider()
    call = executor.execute(
        provider=provider,
        role="analysis",
        stable_unit_id="task#r1",
        task_id="planning-launch-001",
        fixture_id=executor.binding.fixture_bindings[0].fixture_id,
        repetition=1,
        provider_name="offline-test",
        model_name="analysis-test-model",
        request_payload={"p": 2},
        invoke=provider.invoke,
        stable_token="unit1:analysis",
    )
    assert call.status == "failed"
    assert call.safe_error_code == "provider_call_failed"
    assert provider.calls == 1, "a failed call must never be silently retried"
    _assert_attempt(run_id, "analysis", "failed")


def test_executor_is_idempotent_per_unit_and_role(experiment_env) -> None:
    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    provider = OfflineProvider()
    kwargs = dict(
        role="analysis",
        stable_unit_id="task#r1",
        task_id="planning-launch-001",
        fixture_id=executor.binding.fixture_bindings[0].fixture_id,
        repetition=1,
        provider_name="offline-test",
        model_name="analysis-test-model",
        request_payload={"p": 3},
        invoke=provider.invoke,
        stable_token="unit1:analysis",
    )
    first = executor.execute(provider=provider, **kwargs)
    second = executor.execute(provider=provider, **kwargs)
    assert first.attempt_id == second.attempt_id
    assert provider.calls == 1
    assert len(_attempts(run_id)) == 1


def test_executor_rejects_a_declared_provider_binding_mismatch(experiment_env) -> None:
    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    provider = OfflineProvider()
    with pytest.raises(LedgerError) as caught:
        executor.execute(
            provider=provider,
            role="analysis",
            stable_unit_id="task#r1",
            task_id="planning-launch-001",
            fixture_id=executor.binding.fixture_bindings[0].fixture_id,
            repetition=1,
            provider_name="a-different-provider",
            model_name="analysis-test-model",
            request_payload={"p": 4},
            invoke=provider.invoke,
            stable_token="unit1:analysis",
        )
    assert caught.value.code == "provider_assignment_mismatch"
    _assert_no_attempts(run_id)


def test_executor_rejects_target_calls_without_a_condition(experiment_env) -> None:
    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    provider = OfflineProvider()
    with pytest.raises(ValueError, match="Target reservations require"):
        executor.execute(
            provider=provider,
            role="target_execution",
            stable_unit_id="task#r1",
            task_id="planning-launch-001",
            fixture_id=executor.binding.fixture_bindings[0].fixture_id,
            repetition=1,
            provider_name="offline-test",
            model_name="target-test-model",
            request_payload={"p": 5},
            invoke=provider.invoke,
            target_condition=None,
            stable_token="unit1:target",
        )
    _assert_no_attempts(run_id)


def _attempts(run_id) -> list[BenchmarkProviderCallAttempt]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run_id
                )
            )
        )


def test_provider_call_lifecycle_order_is_reserve_start_invoke_settle(
    experiment_env, experiment_attempts
) -> None:
    """A provider may only run after a reservation exists and is started.

    The injected offline provider records the ledger attempt status at the
    moment it is invoked, proving the invocation cannot precede either step.
    No network provider is involved.
    """

    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    observed: list[tuple[str | None, int]] = []

    def attempt_status() -> str | None:
        rows = _attempts(run_id)
        return rows[0].status if rows else None

    provider = OfflineProvider()
    original = provider.invoke

    def observing_invoke() -> object:
        observed.append((attempt_status(), len(_attempts(run_id))))
        return original()

    provider.invoke = observing_invoke  # type: ignore[method-assign]
    assert attempt_status() is None

    call = executor.execute(
        provider=provider,
        role="analysis",
        stable_unit_id="task#r1",
        task_id="planning-launch-001",
        fixture_id=executor.binding.fixture_bindings[0].fixture_id,
        repetition=1,
        provider_name="offline-test",
        model_name="analysis-test-model",
        request_payload={"p": "lifecycle"},
        invoke=observing_invoke,
        stable_token="unit1:analysis:lifecycle",
    )

    # 1. a reservation existed before the provider ran, and it was already started
    assert observed == [("started", 1)]
    # 2. the outcome is only recorded after the invocation returned
    assert call.status == "succeeded"
    assert attempt_status() == "succeeded"
    assert [row.status for row in experiment_attempts(run_id)] == ["succeeded"]


def test_provider_invocation_never_precedes_mark_started_on_failure(
    experiment_env,
) -> None:
    """Even a failing provider is invoked only after reserve + start."""

    executor = make_executor(experiment_env)
    run_id = experiment_env.run_id
    observed: list[str | None] = []

    def observing_invoke() -> object:
        rows = _attempts(run_id)
        observed.append(rows[0].status if rows else None)
        raise RuntimeError("simulated offline provider failure")

    call = executor.execute(
        provider=ExplodingProvider(),
        role="analysis",
        stable_unit_id="task#r2",
        task_id="planning-launch-001",
        fixture_id=executor.binding.fixture_bindings[0].fixture_id,
        repetition=2,
        provider_name="offline-test",
        model_name="analysis-test-model",
        request_payload={"p": "lifecycle-fail"},
        invoke=observing_invoke,
        stable_token="unit1:analysis:lifecycle-fail",
    )
    assert observed == ["started"]
    assert call.status == "failed"
    assert _attempts(run_id)[0].status == "failed"


def _assert_no_attempts(run_id) -> None:
    assert _attempts(run_id) == []


def _assert_attempt(run_id, role: str, status: str) -> None:
    attempts = _attempts(run_id)
    assert len(attempts) == 1
    assert attempts[0].provider_role == role
    assert attempts[0].status == status


# --------------------------------------------------------------------------
# Baseline protection
# --------------------------------------------------------------------------


def test_baseline_prompt_must_equal_the_original_task() -> None:
    from promptpilot_backend.benchmark_experiment_execution import assert_baseline_prompt

    assert_baseline_prompt("original", "original")
    with pytest.raises(BaselineProtectionError) as caught:
        assert_baseline_prompt("original", "original\n\nOptimized: do more")
    assert caught.value.code == "baseline_prompt_contaminated"


def test_baseline_rejects_every_treatment_artifact() -> None:
    from promptpilot_backend.benchmark_experiment_execution import (
        assert_baseline_has_no_treatment_artifacts,
    )

    assert_baseline_has_no_treatment_artifacts(
        prompt_version_id=None,
        analysis_ids=[],
        answer_ids=[],
        memory_ids=[],
        document_ids=[],
        context_source_ids=[],
    )
    for kwargs in (
        {"prompt_version_id": "pv-1"},
        {"analysis_ids": ["a1"]},
        {"answer_ids": ["q1"]},
        {"memory_ids": ["m1"]},
        {"document_ids": ["d1"]},
        {"context_source_ids": ["c1"]},
    ):
        payload = {
            "prompt_version_id": None,
            "analysis_ids": [],
            "answer_ids": [],
            "memory_ids": [],
            "document_ids": [],
            "context_source_ids": [],
            **kwargs,
        }
        with pytest.raises(BaselineProtectionError):
            assert_baseline_has_no_treatment_artifacts(**payload)


def test_frozen_target_parameters_are_shared_by_both_conditions(
    experiment_env,
) -> None:
    protocol = experiment_env.protocol
    bound = assert_target_parameters_identical(protocol)
    assert bound.temperature == protocol.baseline_target_parameters.temperature
    assert bound.max_tokens == protocol.baseline_target_parameters.max_tokens
    assert bound.seed == protocol.baseline_target_parameters.seed


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------


def test_dry_run_reproduces_the_frozen_168_call_ceiling() -> None:
    plan = plan_dry_run(
        task_ids=TASK_IDS, repetitions=3, question_cap=2, judge_enabled=True
    )
    assert plan.unit_count == 24
    assert len(plan.units) == 24
    assert plan.calls_by_role.model_dump() == {
        "analysis": 24,
        "question_generation": 48,
        "prompt_generation": 24,
        "target_execution": 48,
        "judge": 24,
    }
    assert plan.total_calls == 168
    assert plan.network_calls == 0 and plan.cost_estimate == 0
    plan.assert_matches_ceiling(frozen_study_call_ceiling(), 168)


def test_dry_run_condition_order_is_the_frozen_alternation() -> None:
    plan = plan_dry_run(
        task_ids=["only-task"], repetitions=3, question_cap=2, judge_enabled=True
    )
    assert [unit.condition_order for unit in plan.units] == [
        ("baseline", "promptpilot"),
        ("promptpilot", "baseline"),
        ("baseline", "promptpilot"),
    ]


def test_dry_run_rejects_empty_or_invalid_shape() -> None:
    with pytest.raises(ValueError):
        plan_dry_run(task_ids=[], repetitions=3, question_cap=2, judge_enabled=True)
    with pytest.raises(ValueError):
        plan_dry_run(task_ids=TASK_IDS, repetitions=0, question_cap=2, judge_enabled=True)


def test_dry_run_never_enables_a_judge_when_absent() -> None:
    plan = plan_dry_run(task_ids=TASK_IDS, repetitions=3, question_cap=2, judge_enabled=False)
    assert plan.calls_by_role.judge == 0
    assert plan.total_calls == 144


# --------------------------------------------------------------------------
# Export contract and analysis
# --------------------------------------------------------------------------


def _unit(**overrides) -> ExperimentUnit:
    payload = {
        "execution_mode": "offline_dry_run",
        "unit_id": "planning-launch-001#r1",
        "task_id": "planning-launch-001",
        "task_category": "planning",
        "repetition": 1,
        "fixture_id": "fixture-a",
        "fixture_manifest_sha256": "b" * 64,
        "dataset_name": "promptpilot-experimental-v1",
        "dataset_sha256": DATASET_SHA,
        "protocol_id": "production_pipeline_paired_v1",
        "protocol_sha256": PROTOCOL_SHA,
        "repository_sha": None,
        "disposition": "complete_pair",
        "condition_order": ("baseline", "promptpilot"),
        "fallback_state": "none",
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "evaluation": EvaluationArtifact(
            evaluation_id="ev-1",
            method="llm_judge",
            baseline_score=60.0,
            promptpilot_score=72.0,
            overall_delta=12.0,
            winner="promptpilot",
            dimension_scores={
                "baseline": {"relevance": 60.0},
                "promptpilot": {"relevance": 72.0},
            },
        ),
    }
    payload.update(overrides)
    return ExperimentUnit(**payload)


def test_export_preserves_every_disposition(tmp_path: Path) -> None:
    units = (
        _unit(),
        _unit(unit_id="a#r1", disposition="partial_unit", failure_reason="question_cap_reached"),
        _unit(unit_id="b#r1", disposition="failed_unit", failure_reason="provider_call_failed"),
        _unit(unit_id="c#r1", disposition="invalid_pair", failure_reason="budget_exhausted"),
    )
    export = build_export(
        units=units,
        protocol_id="production_pipeline_paired_v1",
        protocol_sha256=PROTOCOL_SHA,
        dataset_name="promptpilot-experimental-v1",
        dataset_sha256=DATASET_SHA,
        execution_mode="offline_dry_run",
        call_ceiling_total=168,
    )
    assert export.unit_count == 4
    assert export.disposition_counts == {
        "complete_pair": 1,
        "partial_unit": 1,
        "failed_unit": 1,
        "invalid_pair": 1,
    }
    path = tmp_path / "export.json"
    lock = write_export(export, path)
    assert len(lock.export_sha256) == 64
    assert lock.export_sha256 == export.content_sha256()
    assert lock.protocol_sha256 == PROTOCOL_SHA
    assert lock.dataset_sha256 == DATASET_SHA
    assert lock.export_unit_count == 4
    assert load_export(path).unit_count == 4
    lock.verify(load_export(path))
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        write_export(export, path)
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        write_export(export, path)


def test_export_lock_is_deterministic_and_external_to_the_export(
    tmp_path: Path,
) -> None:
    """The lock must not perturb the bytes it hashes."""

    export = build_export(
        units=(_unit(),),
        protocol_id="production_pipeline_paired_v1",
        protocol_sha256=PROTOCOL_SHA,
        dataset_name="promptpilot-experimental-v1",
        dataset_sha256=DATASET_SHA,
        execution_mode="offline_dry_run",
        call_ceiling_total=168,
    )
    stamp = datetime(2026, 4, 1, tzinfo=UTC)
    first = lock_export(export, locked_at=stamp)
    second = lock_export(export, locked_at=stamp)
    assert first == second
    assert first.export_sha256 == second.export_sha256
    # The lock is not a field of the export, so it cannot feed back into the hash.
    assert "export_sha256" not in export.model_dump(mode="json")
    path = tmp_path / "export.json"
    write_export(export, path, locked_at=stamp)
    assert load_export_lock(path) == first
    lock_file = path.with_suffix(f"{path.suffix}.lock.json")
    assert lock_file.exists()
    assert "export_sha256" not in path.read_text(encoding="utf-8")


def test_export_lock_detects_a_tampered_export() -> None:
    export = build_export(
        units=(_unit(),),
        protocol_id="production_pipeline_paired_v1",
        protocol_sha256=PROTOCOL_SHA,
        dataset_name="promptpilot-experimental-v1",
        dataset_sha256=DATASET_SHA,
        execution_mode="offline_dry_run",
        call_ceiling_total=168,
    )
    lock = lock_export(export, locked_at=datetime(2026, 4, 1, tzinfo=UTC))
    lock.verify(export)
    tampered = build_export(
        units=(
            _unit(),
            _unit(unit_id="b#r1"),
        ),
        protocol_id="production_pipeline_paired_v1",
        protocol_sha256=PROTOCOL_SHA,
        dataset_name="promptpilot-experimental-v1",
        dataset_sha256=DATASET_SHA,
        execution_mode="offline_dry_run",
        call_ceiling_total=168,
    )
    with pytest.raises(ValueError, match="does not match the export content hash"):
        lock.verify(tampered)


def test_analysis_reports_primary_and_exploratory_separately() -> None:
    units = (
        _unit(unit_id="a#r1", task_category="planning"),
        _unit(
            unit_id="a#r2",
            task_category="planning",
            repetition=2,
            condition_order=("promptpilot", "baseline"),
        ),
        _unit(unit_id="b#r1", task_category="writing"),
    )
    report = aggregate_units(
        units, protocol_sha256=PROTOCOL_SHA, dataset_sha256=DATASET_SHA
    )
    assert report.complete_pairs == 3
    assert [item.stratum for item in report.primary] == ["overall"] + ["task_category"] * len(
        {unit.task_category for unit in units}
    )
    assert all(item.tier == "primary" for item in report.primary)
    assert all(item.tier == "exploratory" for item in report.exploratory)
    assert report.significance_testing_performed is False
    assert report.superiority_claim is False
    assert tuple(item.stratum for item in report.primary[:1]) == PRIMARY_STRATA[:1]


def test_analysis_keeps_incomplete_units_visible() -> None:
    units = (
        _unit(),
        _unit(unit_id="b#r1", disposition="partial_unit", evaluation=None),
    )
    report = aggregate_units(
        units, protocol_sha256=PROTOCOL_SHA, dataset_sha256=DATASET_SHA
    )
    assert report.total_units == 2
    assert report.complete_pairs == 1
    assert report.excluded_from_scoring == 1
    overall = report.primary[0]
    assert overall.incomplete_unit_count == 1


# --------------------------------------------------------------------------
# Human review schema: shape only, never fabricated data
# --------------------------------------------------------------------------


def test_human_review_plan_supports_the_approved_shape_without_scores() -> None:
    plan = HumanReviewPlan(
        pair_count=8,
        reviewer_count=2,
        disagreement_threshold_points=20,
        adjudication_required_above_threshold=True,
    )
    assert plan.populated is False
    assert plan.review_record_count == 0
    assert plan.pair_count == 8 and plan.reviewer_count == 2
    assert plan.disagreement_threshold_points == 20


def test_blinded_sample_has_no_score_bearing_reviewer_field() -> None:
    """The pre-review artifact is structurally incapable of holding scores."""

    fields = set(HumanReviewSampleSlot.model_fields)
    for forbidden in ("reviewers", "scores", "human_review_scores", "score"):
        assert forbidden not in fields
    assert "reviewer_id" not in fields
    assert "HumanReviewRecord" not in HumanReviewSampleSlot.__doc__ or "only" in (
        HumanReviewSampleSlot.__doc__
    )
    serialized = HumanReviewSampleSlot(
        pair_id="pair-1",
        task_id="planning-launch-001",
        repetition=1,
        preselected=True,
        response_a="neutral text",
        response_b="neutral text",
        neutral_label_mapping_stored_separately=True,
    ).model_dump(mode="json")
    for key in ("reviewers", "scores", "score", "reviewer_id"):
        assert key not in serialized
    assert serialized["review_status"] == "pending"
    assert serialized["adjudication_status"] == "not_required"


def test_blinded_sample_rejects_a_reviewers_field_entirely() -> None:
    """Because the model forbids extra fields, scores cannot be smuggled in."""

    with pytest.raises(ValueError):
        HumanReviewSampleSlot(
            pair_id="pair-1",
            task_id="planning-launch-001",
            repetition=1,
            preselected=True,
            response_a="a",
            response_b="b",
            neutral_label_mapping_stored_separately=True,
            reviewers=(
                HumanReviewRecord(
                    pair_id="pair-1",
                    reviewer_id="external-ref-1",
                    dimension="clarity",
                    score=90,
                ),
            ),
        )


def test_blinded_sample_exposes_no_condition_or_model_identity() -> None:
    sample = HumanReviewSampleSlot(
        pair_id="pair-1",
        task_id="planning-launch-001",
        repetition=1,
        preselected=True,
        response_a="neutral text",
        response_b="neutral text",
        neutral_label_mapping_stored_separately=True,
    )
    payload = sample.model_dump_json().casefold()
    for identity in ("baseline", "promptpilot", "model", "provider", "condition"):
        assert identity not in payload
    assert sample.awaiting_review is True


def test_review_records_live_only_in_the_separate_structure() -> None:
    plan = HumanReviewPlan(
        pair_count=8,
        reviewer_count=2,
        disagreement_threshold_points=20,
        adjudication_required_above_threshold=True,
        slots=(
            HumanReviewSampleSlot(
                pair_id="pair-1",
                task_id="planning-launch-001",
                repetition=1,
                preselected=True,
                response_a="neutral text",
                response_b="neutral text",
                neutral_label_mapping_stored_separately=True,
            ),
        ),
    )
    assert plan.review_record_count == 0
    assert "records" not in plan.slots[0].model_dump(mode="json")
    record = HumanReviewRecord(
        pair_id="pair-1",
        reviewer_id="external-ref-1",
        dimension="clarity",
        score=88,
        flagged_disagreement=True,
    )
    with_records = plan.model_copy(update={"records": (record,)})
    assert with_records.review_record_count == 1
    assert len(with_records.disagreements_above_threshold()) == 1
    assert "score" not in plan.slots[0].model_dump(mode="json")


def test_review_records_enforce_v1_dimensions_and_score_range() -> None:
    record = HumanReviewRecord(
        pair_id="pair-1",
        reviewer_id="external-ref-1",
        dimension="clarity",
        score=88,
    )
    assert record.flagged_disagreement is False
    for dimension in (
        "relevance",
        "completeness",
        "instruction_following",
        "contextual_grounding",
        "clarity",
    ):
        assert HumanReviewRecord(
            pair_id="p", reviewer_id="r", dimension=dimension, score=0
        ).score == 0
        assert HumanReviewRecord(
            pair_id="p", reviewer_id="r", dimension=dimension, score=100
        ).score == 100
    with pytest.raises(ValueError):
        HumanReviewRecord(
            pair_id="p", reviewer_id="r", dimension="invented_dimension", score=50
        )
    with pytest.raises(ValueError):
        HumanReviewRecord(pair_id="p", reviewer_id="r", dimension="clarity", score=101)
    with pytest.raises(ValueError):
        HumanReviewRecord(pair_id="p", reviewer_id="r", dimension="clarity", score=-1)


# --------------------------------------------------------------------------
# Question artifacts
# --------------------------------------------------------------------------


def test_question_artifacts_never_fabricate_answers() -> None:
    artifact = QuestionArtifact(
        question_id="q-1",
        gap_id="g-1",
        question_text="Which region?",
        resolution="skip",
        reason="no_matching_fixture_answer",
        answer_existed=False,
    )
    assert artifact.resolution == "skip"
    assert artifact.answer_existed is False
    with pytest.raises(ValueError):
        QuestionArtifact(
            question_id="q-2",
            gap_id="g-2",
            question_text="Which?",
            resolution="answered",
            reason=None,
            answer_existed=False,
        )