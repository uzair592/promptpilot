"""Ledger-gated provider-call execution for benchmark experiment runs.

Every provider-backed stage in a future live run must pass through
:class:`ProviderCallExecutor`. The authoritative sequence is::

    reserve_call
        -> mark_started
        -> provider invocation
        -> mark_succeeded OR mark_failed

The provider is never invoked until a reservation has been committed *and* the
attempt has been transitioned to ``started``. Budget cannot be exceeded and no
call can disappear from the ledger, because the role counter is consumed at
reservation time and the outcome is always settled explicitly.

This milestone exposes exactly one execution mode, ``offline_dry_run``, which
admits only providers explicitly marked ``offline_fixture = True``. There is no
``live`` mode member, so live execution is unrepresentable rather than merely
guarded. The real provider adapter stays an unimplemented factory boundary in
the future live-runner milestone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from .benchmark_call_ledger import (
    AttemptFailure,
    AttemptSuccess,
    BenchmarkCallLedger,
    ProviderRole,
    ReservationDeclaration,
    TargetCondition,
    canonical_artifact_sha256,
)
from .benchmark_experiment_binding import ProtocolBinding
from .llm_provider import OpenAICompatibleProvider

# Offline-only. A "live" member is intentionally absent so that no caller can
# request live execution from this engine.
ExecutionMode = Literal["offline_dry_run"]
EXECUTION_MODES: tuple[ExecutionMode, ...] = ("offline_dry_run",)


class ExecutionGateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PartialExperimentUnit(RuntimeError):
    """A unit that cannot continue but is retained as evidence, not deleted."""


def require_offline_provider(provider: Any, role: str) -> None:
    """Reject anything that is not an explicitly offline fixture provider."""

    if isinstance(provider, OpenAICompatibleProvider):
        raise ExecutionGateError(
            "real_provider_rejected",
            f"Real OpenAI-compatible providers cannot execute in offline dry-run mode ({role})",
        )
    if getattr(provider, "offline_fixture", None) is not True:
        raise ExecutionGateError(
            "provider_not_offline",
            f"Provider for {role} must be explicitly marked offline_fixture=True",
        )


def require_offline_providers(providers: dict[str, Any], role: str) -> None:
    for name, provider in providers.items():
        require_offline_provider(provider, f"{role}:{name}")


@dataclass(frozen=True)
class ReservedCall:
    """The outcome of one fully accounted provider call."""

    role: ProviderRole
    target_condition: TargetCondition | None
    attempt_id: Any
    status: Literal["succeeded", "failed"]
    idempotency_key: str
    request_sha256: str
    safe_error_code: str | None = None


class ProviderCallExecutor:
    """Reserve, invoke, and settle one provider call against the durable ledger."""

    def __init__(
        self,
        db: Session,
        run_id: Any,
        binding: ProtocolBinding,
        *,
        execution_mode: ExecutionMode = "offline_dry_run",
    ) -> None:
        if execution_mode not in EXECUTION_MODES:
            raise ExecutionGateError(
                "unsupported_execution_mode",
                "Only offline dry-run execution is implemented in this milestone",
            )
        self._db = db
        self._run_id = run_id
        self._binding = ProtocolBinding.model_validate(binding.model_dump(mode="python"))
        self._mode = execution_mode

    @property
    def binding(self) -> ProtocolBinding:
        return self._binding

    def execute(
        self,
        *,
        provider: Any,
        role: ProviderRole,
        stable_unit_id: str,
        task_id: str,
        fixture_id: str,
        repetition: int,
        provider_name: str,
        model_name: str,
        request_payload: Any,
        invoke: Callable[[], Any],
        target_condition: TargetCondition | None = None,
        stable_token: str,
    ) -> ReservedCall:
        """Run one provider-backed stage through the full ledger lifecycle."""

        require_offline_provider(provider, role)
        request_sha256 = canonical_artifact_sha256(request_payload)
        parameter_sha256 = (
            self._binding.target_parameters.generation_parameter_sha256
            if role == "target_execution"
            else canonical_artifact_sha256({})
        )
        declaration = ReservationDeclaration(
            stable_unit_id=stable_unit_id,
            fixture_id=fixture_id,
            task_id=task_id,
            repetition=repetition,
            provider_role=role,
            target_condition=target_condition,
            idempotency_key=stable_token,
            configured_provider=provider_name,
            configured_model=model_name,
            generation_parameter_sha256=parameter_sha256,
            request_artifact_sha256=request_sha256,
            protocol_sha256=self._binding.protocol_sha256,
            dataset_sha256=self._binding.dataset_sha256,
        )
        attempt = BenchmarkCallLedger.reserve_call(self._db, self._run_id, declaration)
        if attempt.status != "reserved":
            # An identical replay of an already-settled call. The ledger binds an
            # idempotency key to one immutable attempt, so the provider must not
            # be invoked again and the recorded outcome is returned as-is.
            return ReservedCall(
                role=role,
                target_condition=target_condition,
                attempt_id=attempt.id,
                status=(
                    "succeeded" if attempt.status == "succeeded" else "failed"
                ),
                idempotency_key=stable_token,
                request_sha256=request_sha256,
                safe_error_code=attempt.safe_error_code,
            )
        BenchmarkCallLedger.mark_started(self._db, attempt.id)
        try:
            result = invoke()
        except Exception as error:
            BenchmarkCallLedger.mark_failed(
                self._db,
                attempt.id,
                AttemptFailure(
                    safe_error_type=type(error).__name__,
                    safe_error_code="provider_call_failed",
                    fallback_classification="provider_failed",
                ),
            )
            return ReservedCall(
                role=role,
                target_condition=target_condition,
                attempt_id=attempt.id,
                status="failed",
                idempotency_key=stable_token,
                request_sha256=request_sha256,
                safe_error_code="provider_call_failed",
            )
        BenchmarkCallLedger.mark_succeeded(
            self._db,
            attempt.id,
            AttemptSuccess(
                fallback_classification="none",
                response_artifact_sha256=canonical_artifact_sha256(result),
            ),
        )
        return ReservedCall(
            role=role,
            target_condition=target_condition,
            attempt_id=attempt.id,
            status="succeeded",
            idempotency_key=stable_token,
            request_sha256=request_sha256,
        )


class ConditionPair:
    """Validated record of one baseline/PromptPilot pair and its execution order."""

    def __init__(
        self,
        *,
        repetition: int,
        condition_order: tuple[TargetCondition, TargetCondition],
        baseline_run_id: str,
        promptpilot_run_id: str,
        source_message_id: str,
        target_provider: str,
        target_model: str,
        parameter_sha256: str,
    ) -> None:
        self.repetition = repetition
        self.condition_order = condition_order
        self.baseline_run_id = baseline_run_id
        self.promptpilot_run_id = promptpilot_run_id
        self.source_message_id = source_message_id
        self.target_provider = target_provider
        self.target_model = target_model
        self.parameter_sha256 = parameter_sha256


def approved_condition_order(repetition: int) -> tuple[TargetCondition, TargetCondition]:
    """The frozen alternating order: rep1 B->P, rep2 P->B, rep3 B->P, then alternating."""

    if repetition < 1:
        raise ExecutionGateError(
            "invalid_repetition", "Repetition must be a positive integer"
        )
    return (
        ("baseline", "promptpilot")
        if repetition % 2
        else ("promptpilot", "baseline")
    )


def assert_approved_order(
    repetition: int, condition_order: tuple[str, ...]
) -> None:
    if tuple(condition_order) != approved_condition_order(repetition):
        raise ExecutionGateError(
            "condition_order_mismatch",
            f"Repetition {repetition} must execute in the approved alternating order",
        )


class BaselineProtectionError(ExecutionGateError):
    pass


def assert_baseline_prompt(original_task: str, executed_prompt: str) -> None:
    """The baseline may execute the original task and nothing else."""

    if executed_prompt != original_task:
        raise BaselineProtectionError(
            "baseline_prompt_contaminated",
            "Baseline executed something other than the exact original task",
        )


def assert_baseline_has_no_treatment_artifacts(
    *,
    prompt_version_id: str | None,
    analysis_ids: list[str],
    answer_ids: list[str],
    memory_ids: list[str],
    document_ids: list[str],
    context_source_ids: list[str],
) -> None:
    if prompt_version_id is not None:
        raise BaselineProtectionError(
            "baseline_received_optimized_prompt",
            "Baseline must not reference an optimized PromptPilot prompt",
        )
    for label, values in (
        ("analysis", analysis_ids),
        ("answer", answer_ids),
        ("memory", memory_ids),
        ("document", document_ids),
        ("context", context_source_ids),
    ):
        if values:
            raise BaselineProtectionError(
                "baseline_received_treatment_artifacts",
                f"Baseline must not receive treatment {label} artifacts",
            )