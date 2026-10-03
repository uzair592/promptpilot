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

This milestone exposes two execution modes:
- ``offline_dry_run``: Admits only providers explicitly marked ``offline_fixture = True``.
- ``live``: Requires ALL launch gate conditions to pass (protocol locked, fixtures
  live-eligible, launch authorization supplied, provider/spending authorized, etc.).
  The live mode is unrepresentable without a valid launch gate - it is
  fail-closed by design.
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
from .benchmark_experiment_binding import (
    ProtocolBinding,
    assert_fixture_current,
)
from .benchmark_fixtures import FixtureManifest
from .llm_provider import OpenAICompatibleProvider

# Execution modes. "live" is only usable when the launch gate passes.
ExecutionMode = Literal["offline_dry_run", "live"]
EXECUTION_MODES: tuple[ExecutionMode, ...] = ("offline_dry_run", "live")


class ExecutionGateError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PartialExperimentUnit(RuntimeError):
    """A unit that cannot continue but is retained as evidence, not deleted."""


def require_offline_provider(
    provider: Any,
    role: str,
    execution_mode: Literal["offline_dry_run", "live"] = "offline_dry_run",
) -> None:
    """Reject anything that is not an explicitly offline fixture provider in offline mode.

    In live mode, real providers are allowed (they must pass the launch gate).
    """

    if execution_mode == "live":
        # In live mode, real providers are allowed (launch gate already verified)
        return

    if isinstance(provider, OpenAICompatibleProvider):
        raise ExecutionGateError(
            "real_provider_rejected",
            (
                "Real OpenAI-compatible providers cannot execute "
                f"in offline dry-run mode ({role})"
            ),
        )
    if getattr(provider, "offline_fixture", None) is not True:
        raise ExecutionGateError(
            "provider_not_offline",
            f"Provider for {role} must be explicitly marked offline_fixture=True",
        )


def require_offline_providers(
    providers: dict[str, Any],
    role: str,
    execution_mode: Literal["offline_dry_run", "live"] = "offline_dry_run",
) -> None:
    for name, provider in providers.items():
        require_offline_provider(provider, f"{role}:{name}", execution_mode)


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
        launch_gate_report: Any | None = None,
    ) -> None:
        if execution_mode not in EXECUTION_MODES:
            raise ExecutionGateError(
                "unsupported_execution_mode",
                f"Execution mode {execution_mode} is not supported",
            )
        if execution_mode == "live":
            if launch_gate_report is None:
                raise ExecutionGateError(
                    "launch_gate_required",
                    "Live execution mode requires a launch gate report",
                )
            if not launch_gate_report.ready:
                raise ExecutionGateError(
                    "launch_gate_not_passed",
                    f"Launch gate not passed: {[b.code for b in launch_gate_report.blockers]}",
                )
        self._db = db
        self._run_id = run_id
        self._binding = ProtocolBinding.model_validate(binding.model_dump(mode="python"))
        self._mode = execution_mode
        self._launch_gate_report = launch_gate_report

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

        require_offline_provider(provider, role, self._mode)
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


def verify_fixture_before_target_execution(
    binding: ProtocolBinding,
    fixture_id: str,
    manifest: FixtureManifest,
    dataset: Any,
    manifest_path: Any,
) -> None:
    """Re-verify fixture against its frozen binding immediately before target execution.

    This enforces Requirement #4: fixture re-verification immediately before
    each target condition executes. The fixture must match its frozen binding
    exactly, including all document hashes, clarification answer hashes, and
    review status. Any drift causes an immediate stop.

    Args:
        binding: The frozen protocol binding containing the fixture bindings.
        fixture_id: The ID of the fixture to verify.
        manifest: The current fixture manifest to verify.
        dataset: The benchmark dataset for identity verification.
        manifest_path: Path to the manifest file.

    Raises:
        ExecutionGateError: If the fixture has drifted or is not live-eligible.
    """

    # This will raise BindingError if the fixture has drifted
    # which we convert to ExecutionGateError for consistent error handling
    from .benchmark_experiment_binding import BindingError
    try:
        assert_fixture_current(binding, fixture_id, manifest, dataset, manifest_path)
    except BindingError as e:
        raise ExecutionGateError(e.code, e.args[0] if e.args else str(e)) from e

    # Additional check: fixture must be live-eligible
    frozen = next(
        (f for f in binding.fixture_bindings if f.fixture_id == fixture_id), None
    )
    if frozen is None or not frozen.live_eligible:
        raise ExecutionGateError(
            "fixture_not_live_eligible",
            f"Fixture {fixture_id} is not live-eligible for target execution",
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