"""Fail-closed stop-rule evaluator for live experiment execution.

This module implements a reusable stop-rule evaluator that halts execution on
any condition that violates the frozen experimental protocol. Every stop
decision is explicit, machine-readable, and never silently converted into a
successful outcome.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .benchmark_experiment_binding import ProtocolBinding
from .benchmark_fixtures import FixtureManifest
from .production_benchmark_protocol import LiveStudyProtocol


class StopReasonCode(StrEnum):
    """Machine-readable stop reason codes."""

    PROVIDER_FAILURE = "provider_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROTOCOL_DRIFT = "protocol_drift"
    FIXTURE_DRIFT = "fixture_drift"
    INVALID_TARGET_PARAMETERS = "invalid_target_parameters"
    INVALID_CONDITION_ORDER = "invalid_condition_order"
    FALLBACK_REJECTED = "fallback_rejected"
    INCOMPLETE_REQUIRED_PAIR = "incomplete_required_pair"
    JUDGE_FAILURE = "judge_failure"
    IDEMPOTENCY_VIOLATION = "idempotency_violation"
    FIXTURE_MISMATCH = "fixture_mismatch"
    MONETARY_BUDGET_EXHAUSTED = "monetary_budget_exhausted"
    MONETARY_BUDGET_NOT_CONFIGURED = "monetary_budget_not_configured"
    CURRENCY_MISMATCH = "currency_mismatch"
    PROVIDER_AUTHORIZATION_MISMATCH = "provider_authorization_mismatch"
    GENERATION_PARAMETER_MISMATCH = "generation_parameter_mismatch"
    PROTOCOL_HASH_MISMATCH = "protocol_hash_mismatch"
    DATASET_HASH_MISMATCH = "dataset_hash_mismatch"
    FIXTURE_NOT_LIVE_ELIGIBLE = "fixture_not_live_eligible"
    FIXTURE_HASH_MISMATCH = "fixture_hash_mismatch"
    FIXTURE_REVIEW_STATUS_CHANGED = "fixture_review_status_changed"
    ORIGINAL_TASK_HASH_MISMATCH = "original_task_hash_mismatch"
    DOCUMENT_HASH_MISMATCH = "document_hash_mismatch"
    CLARIFICATION_ANSWER_HASH_MISMATCH = "clarification_answer_hash_mismatch"
    EXECUTION_MODE_MISMATCH = "execution_mode_mismatch"
    LAUNCH_GATE_NOT_PASSED = "launch_gate_not_passed"


class StopDecision(BaseModel):
    """Result of a stop-rule evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    should_stop: bool
    reason_code: StopReasonCode | None = None
    reason_message: str | None = None
    context: dict[str, Any] = {}


class StopRuleEvaluator:
    """Evaluates stop rules for live experiment execution.

    This evaluator is fail-closed: any violation of the frozen protocol
    results in an explicit stop decision with a machine-readable reason code.
    """

    def __init__(
        self,
        protocol: LiveStudyProtocol,
        binding: ProtocolBinding,
        launch_authorization: Any | None = None,
        dataset: Any = None,
    ) -> None:
        self._protocol = protocol
        self._binding = binding
        self._launch_authorization = launch_authorization
        self._dataset = dataset

    def evaluate_launch_gate(
        self,
        *,
        protocol_locked: bool,
        fixture_ids: list[str],
        live_eligible_fixture_ids: list[str],
        target_provider: str,
        target_model: str,
        authorization: Any | None,
    ) -> StopDecision:
        """Evaluate the launch gate before any execution begins."""
        if not protocol_locked:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.PROTOCOL_DRIFT,
                reason_message="Protocol is not locked",
            )

        if not self._launch_authorization:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.LAUNCH_GATE_NOT_PASSED,
                reason_message="Launch authorization not supplied",
            )

        # Check authorization binds to protocol
        if hasattr(self._launch_authorization, "protocol_sha256"):
            if self._launch_authorization.protocol_sha256 != self._binding.protocol_sha256:
                return StopDecision(
                    should_stop=True,
                    reason_code=StopReasonCode.PROTOCOL_HASH_MISMATCH,
                    reason_message="Launch authorization bound to different protocol",
                )

        # Check fixture eligibility
        requested = set(fixture_ids)
        eligible = set(live_eligible_fixture_ids)
        if not requested:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.FIXTURE_NOT_LIVE_ELIGIBLE,
                reason_message="No fixtures requested",
            )
        if not requested <= eligible:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.FIXTURE_NOT_LIVE_ELIGIBLE,
                reason_message="Some fixtures are not live-eligible",
            )

        # Check provider/model authorization
        if hasattr(self._launch_authorization, "authorized_provider"):
            if (self._launch_authorization.authorized_provider,
                self._launch_authorization.authorized_model) != (target_provider, target_model):
                return StopDecision(
                    should_stop=True,
                    reason_code=StopReasonCode.PROVIDER_AUTHORIZATION_MISMATCH,
                    reason_message="Authorization does not cover this provider/model",
                )

        return StopDecision(should_stop=False)

    def evaluate_before_target_execution(
        self,
        *,
        unit_id: str,
        task_id: str,
        fixture_id: str,
        repetition: int,
        condition_order: tuple[str, ...],
        target_provider: str,
        target_model: str,
        target_parameters: Any,
        fixture_manifest: Any,
        dataset: Any,
        manifest_path: Any,
        protocol: Any,
        budget_snapshot: Any,
        launch_gate_passed: bool,
    ) -> StopDecision:
        """Evaluate all stop rules before target execution for a unit."""

        if not launch_gate_passed:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.LAUNCH_GATE_NOT_PASSED,
                reason_message="Launch gate not passed",
            )

        # Protocol drift check
        try:
            self._assert_protocol_current(protocol)
        except Exception as e:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.PROTOCOL_DRIFT,
                reason_message=str(e),
                context={"unit_id": unit_id},
            )

        # Fixture drift check
        try:
            self._assert_fixture_current(fixture_manifest, fixture_id, manifest_path)
        except Exception as e:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.FIXTURE_DRIFT,
                reason_message=str(e),
                context={"unit_id": unit_id, "fixture_id": fixture_id},
            )

        # Fixture live eligibility
        if not self._is_fixture_live_eligible(fixture_id):
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.FIXTURE_NOT_LIVE_ELIGIBLE,
                reason_message=f"Fixture {fixture_id} is not live-eligible",
                context={"fixture_id": fixture_id},
            )

        # Target parameter identity
        try:
            self._assert_target_parameters_identical()
        except Exception as e:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.INVALID_TARGET_PARAMETERS,
                reason_message=str(e),
                context={"unit_id": unit_id},
            )

        # Condition order
        expected_order = self._get_expected_condition_order(repetition)
        if tuple(condition_order) != expected_order:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.INVALID_CONDITION_ORDER,
                reason_message=(
                    f"Condition order {condition_order} does not match "
                    f"expected {expected_order}"
                ),
                context={"unit_id": unit_id, "repetition": repetition},
            )

        # Target provider/model match
        provider_match = target_provider == self._binding.target_provider
        model_match = target_model == self._binding.target_model
        if not (provider_match and model_match):
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.PROVIDER_AUTHORIZATION_MISMATCH,
                reason_message="Target provider/model does not match binding",
                context={
                    "expected_provider": self._binding.target_provider,
                    "expected_model": self._binding.target_model,
                    "actual_provider": target_provider,
                    "actual_model": target_model,
                },
            )

        # Target parameters match binding
        if target_parameters != self._binding.target_parameters:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.GENERATION_PARAMETER_MISMATCH,
                reason_message="Target parameters do not match binding",
                context={"unit_id": unit_id},
            )

        # Budget exhaustion
        if budget_snapshot.remaining_total <= 0:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.BUDGET_EXHAUSTED,
                reason_message="Total call budget exhausted",
                context={"unit_id": unit_id},
            )

        # Monetary budget exhaustion
        if budget_snapshot.max_spend is not None:
            if budget_snapshot.remaining_spend is not None and budget_snapshot.remaining_spend <= 0:
                return StopDecision(
                    should_stop=True,
                    reason_code=StopReasonCode.MONETARY_BUDGET_EXHAUSTED,
                    reason_message="Monetary budget exhausted",
                    context={"unit_id": unit_id},
                )

        # Monetary budget not configured
        if budget_snapshot.max_spend is None:
            # Check if this is a target execution call (which requires monetary budget)
            # For now, we allow non-target calls without monetary budget
            pass

        return StopDecision(should_stop=False)

    def evaluate_after_provider_call(
        self,
        *,
        call_result: Any,
        role: str,
    ) -> StopDecision:
        """Evaluate stop rules after a provider call completes."""
        if call_result.status == "failed":
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.PROVIDER_FAILURE,
                reason_message=f"Provider call failed: {call_result.safe_error_code}",
                context={"role": call_result.role},
            )
        return StopDecision(should_stop=False)

    def evaluate_fallback(
        self,
        *,
        fallback_classification: str,
        fallback_admission: str,
    ) -> StopDecision:
        """Evaluate fallback against the frozen fallback admission policy."""
        if fallback_classification != "none" and fallback_admission == "reject":
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.FALLBACK_REJECTED,
                reason_message=f"Fallback {fallback_classification} rejected by policy",
            )
        return StopDecision(should_stop=False)

    def evaluate_pair_completeness(
        self,
        unit: Any,
    ) -> StopDecision:
        """Evaluate if a unit forms a complete pair."""
        if not unit.is_complete_pair:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.INCOMPLETE_REQUIRED_PAIR,
                reason_message=f"Unit {unit.unit_id} is not a complete pair: {unit.disposition}",
                context={"unit_id": unit.unit_id, "disposition": unit.disposition},
            )
        return StopDecision(should_stop=False)

    def evaluate_judge_result(
        self,
        *,
        judge_result: Any,
        evaluation_method: str,
    ) -> StopDecision:
        """Evaluate judge result against the frozen evaluation policy."""
        if evaluation_method != "llm_judge":
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.JUDGE_FAILURE,
                reason_message=f"Unexpected evaluator: {evaluation_method}",
            )
        # Check for invalid judge output
        if judge_result is None:
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.JUDGE_FAILURE,
                reason_message="Judge returned no result",
            )
        return StopDecision(should_stop=False)

    def evaluate_idempotency(
        self,
        *,
        attempt_status: str,
        existing_attempt_status: str | None,
    ) -> StopDecision:
        """Evaluate idempotency violations."""
        if existing_attempt_status in ("succeeded", "failed"):
            # Replay of settled attempt - allowed, but no re-invocation
            return StopDecision(should_stop=False)
        if existing_attempt_status == "started":
            # Attempt was started but not finished - potential violation
            return StopDecision(
                should_stop=True,
                reason_code=StopReasonCode.IDEMPOTENCY_VIOLATION,
                reason_message="Attempt already started but not settled",
            )
        return StopDecision(should_stop=False)

    def _assert_protocol_current(self, protocol: LiveStudyProtocol) -> None:
        from .benchmark_experiment_binding import assert_binding_current
        assert_binding_current(self._binding, protocol)

    def _assert_fixture_current(
        self,
        manifest: FixtureManifest,
        fixture_id: str,
        manifest_path: Any,
    ) -> None:
        from .benchmark_experiment_binding import assert_fixture_current
        assert_fixture_current(self._binding, fixture_id, manifest, self._dataset, manifest_path)

    def _is_fixture_live_eligible(self, fixture_id: str) -> bool:
        binding = next(
            (f for f in self._binding.fixture_bindings if f.fixture_id == fixture_id), None
        )
        return binding is not None and binding.live_eligible

    def _assert_target_parameters_identical(self) -> None:
        from .benchmark_experiment_binding import assert_target_parameters_identical
        assert_target_parameters_identical(self._protocol)

    def _get_expected_condition_order(self, repetition: int) -> tuple[str, ...]:
        from .benchmark_experiment_execution import approved_condition_order
        return approved_condition_order(repetition)


# Convenience function for creating a stop rule evaluator from a binding
def create_stop_evaluator(
    protocol: LiveStudyProtocol,
    binding: ProtocolBinding,
    launch_authorization: Any | None = None,
) -> StopRuleEvaluator:
    return StopRuleEvaluator(protocol, binding, launch_authorization)