"""Durable, credential-free provider-call reservations for benchmark research.

This module stages and accounts for calls. It never constructs or invokes a provider.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import BenchmarkExperimentRun, BenchmarkProviderCallAttempt, User
from .production_benchmark_protocol import (
    AdmissionReport,
    LiveStudyProtocol,
    NonBlankStr,
    RoleCallBudget,
    Sha256,
    StrictFiniteFloat,
    StrictInteger,
    calculate_call_ceiling,
    protocol_sha256,
)

ProviderRole = Literal[
    "analysis", "question_generation", "prompt_generation", "target_execution", "judge"
]
TargetCondition = Literal["baseline", "promptpilot"]
AttemptStatus = Literal["reserved", "started", "succeeded", "failed", "cancelled"]
FallbackClassification = Literal[
    "none",
    "not_configured",
    "provider_failed",
    "invalid_output",
    "duplicate_question",
    "admitted_fallback",
]
ObservationOutcome = Literal["not_recorded", "not_attempted", "succeeded", "failed"]
SafeCode = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$"),
]

_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:authorization\s*[:=]|bearer\s+[a-z0-9._~+/=-]+|"
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|cookie)\s*[:=]|"
    r"sk-[a-z0-9_-]{8,}|https?://[^/\s]*@|[?&](?:token|api_key|key|password)=)"
)
_ROLE_COUNTERS = {
    "analysis": "analysis_consumed_count",
    "question_generation": "question_generation_consumed_count",
    "prompt_generation": "prompt_generation_consumed_count",
    "target_execution": "target_execution_consumed_count",
    "judge": "judge_consumed_count",
}
_ROLE_CEILINGS = {
    "analysis": "analysis_call_ceiling",
    "question_generation": "question_generation_call_ceiling",
    "prompt_generation": "prompt_generation_call_ceiling",
    "target_execution": "target_execution_call_ceiling",
    "judge": "judge_call_ceiling",
}
_SAFE_CODE_ADAPTER = TypeAdapter(SafeCode)


def _now() -> datetime:
    return datetime.now(UTC)


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_sensitive(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_sensitive(item)
    elif isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        raise ValueError("Credential-like values are forbidden in benchmark ledger data")


def _safe_code(value: str) -> str:
    return _SAFE_CODE_ADAPTER.validate_python(value)


def canonical_artifact_sha256(value: Any) -> str:
    """Hash a JSON artifact without retaining its raw content or allowing non-finite data."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generation_parameters_sha256(
    protocol_or_params: LiveStudyProtocol | Any,
) -> str:
    """Compute SHA-256 of generation parameters.

    Accepts either a LiveStudyProtocol (uses baseline_target_parameters) or
    TargetGenerationParameters directly.
    """
    # Check if it's a protocol or parameters directly
    if hasattr(protocol_or_params, "baseline_target_parameters"):
        # It's a protocol
        params = protocol_or_params.baseline_target_parameters
    else:
        # Assume it's TargetGenerationParameters
        params = protocol_or_params

    return canonical_artifact_sha256(params.model_dump(mode="json"))


class LedgerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictLedgerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class ReservationDeclaration(StrictLedgerModel):
    stable_unit_id: NonBlankStr
    fixture_id: NonBlankStr
    task_id: NonBlankStr
    repetition: StrictInteger = Field(ge=1)
    provider_role: ProviderRole
    target_condition: TargetCondition | None
    idempotency_key: NonBlankStr = Field(max_length=160)
    configured_provider: NonBlankStr = Field(max_length=120)
    configured_model: NonBlankStr = Field(max_length=240)
    generation_parameter_sha256: Sha256
    request_artifact_sha256: Sha256
    protocol_sha256: Sha256
    dataset_sha256: Sha256
    estimated_cost: StrictFiniteFloat | None = Field(default=None, ge=0)
    currency: Annotated[
        str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")
    ] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_credentials(cls, value: Any) -> Any:
        _reject_sensitive(value)
        return value

    @model_validator(mode="after")
    def cost_and_currency_consistent(self) -> ReservationDeclaration:
        if (self.estimated_cost is None) != (self.currency is None):
            raise ValueError("Estimated cost and currency must be supplied together")
        return self

    @model_validator(mode="after")
    def condition_matches_role(self) -> ReservationDeclaration:
        if self.provider_role == "target_execution" and self.target_condition is None:
            raise ValueError("Target reservations require baseline or promptpilot condition")
        if self.provider_role != "target_execution" and self.target_condition is not None:
            raise ValueError("Only target reservations may declare a target condition")
        return self


class AttemptSuccess(StrictLedgerModel):
    input_tokens: StrictInteger | None = Field(default=None, ge=0)
    output_tokens: StrictInteger | None = Field(default=None, ge=0)
    total_tokens: StrictInteger | None = Field(default=None, ge=0)
    cost_estimate: StrictFiniteFloat | None = Field(default=None, ge=0)
    currency: Annotated[
        str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")
    ] | None = None
    fallback_classification: FallbackClassification = "none"
    observation_outcome: Literal["succeeded"] = "succeeded"
    response_artifact_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> AttemptSuccess:
        if (self.cost_estimate is None) != (self.currency is None):
            raise ValueError("Cost estimate and currency must be supplied together")
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens < self.input_tokens + self.output_tokens
        ):
            raise ValueError("Total tokens cannot be below input plus output tokens")
        return self


class AttemptFailure(StrictLedgerModel):
    safe_error_type: SafeCode
    safe_error_code: SafeCode
    fallback_classification: FallbackClassification
    observation_outcome: Literal["failed"] = "failed"


class RoleBinding(StrictLedgerModel):
    provider: NonBlankStr
    model: NonBlankStr
    generation_parameter_sha256: Sha256


class BudgetSnapshot(StrictLedgerModel):
    run_id: UUID
    status: Literal["staged", "running", "completed", "failed", "aborted"]
    ceilings: RoleCallBudget
    total_ceiling: StrictInteger
    consumed_by_role: RoleCallBudget
    reserved: StrictInteger
    succeeded: StrictInteger
    failed: StrictInteger
    cancelled: StrictInteger
    remaining_by_role: RoleCallBudget
    remaining_total: StrictInteger
    max_spend: float | None = None
    spent_amount: float = 0.0
    spent_currency: str | None = None
    budget_currency: str | None = None
    remaining_spend: float | None = None


def _role_bindings(protocol: LiveStudyProtocol) -> dict[str, RoleBinding]:
    empty_hash = canonical_artifact_sha256({})
    target_hash = generation_parameters_sha256(protocol)
    providers = protocol.providers
    bindings = {
        "analysis": RoleBinding(
            provider=providers.analysis.provider,
            model=providers.analysis.model,
            generation_parameter_sha256=empty_hash,
        ),
        "question_generation": RoleBinding(
            provider=providers.question_generation.provider,
            model=providers.question_generation.model,
            generation_parameter_sha256=empty_hash,
        ),
        "prompt_generation": RoleBinding(
            provider=providers.prompt_generation.provider,
            model=providers.prompt_generation.model,
            generation_parameter_sha256=empty_hash,
        ),
        "target_execution": RoleBinding(
            provider=providers.baseline_target.provider,
            model=providers.baseline_target.model,
            generation_parameter_sha256=target_hash,
        ),
    }
    if providers.judge is not None:
        bindings["judge"] = RoleBinding(
            provider=providers.judge.provider,
            model=providers.judge.model,
            generation_parameter_sha256=empty_hash,
        )
    _reject_sensitive({key: value.model_dump(mode="json") for key, value in bindings.items()})
    return bindings


def _binding_data(run: BenchmarkExperimentRun) -> dict[str, RoleBinding]:
    raw = json.loads(run.frozen_role_bindings_json)
    if not isinstance(raw, dict):
        raise LedgerError("invalid_role_bindings", "Stored role bindings are invalid")
    try:
        return {key: RoleBinding.model_validate(value) for key, value in raw.items()}
    except ValueError as exc:
        raise LedgerError("invalid_role_bindings", "Stored role bindings are invalid") from exc


def _role_counts(run: BenchmarkExperimentRun) -> RoleCallBudget:
    return RoleCallBudget(
        analysis=run.analysis_consumed_count,
        question_generation=run.question_generation_consumed_count,
        prompt_generation=run.prompt_generation_consumed_count,
        target_execution=run.target_execution_consumed_count,
        judge=run.judge_consumed_count,
    )


def _role_ceilings(run: BenchmarkExperimentRun) -> RoleCallBudget:
    return RoleCallBudget(
        analysis=run.analysis_call_ceiling,
        question_generation=run.question_generation_call_ceiling,
        prompt_generation=run.prompt_generation_call_ceiling,
        target_execution=run.target_execution_call_ceiling,
        judge=run.judge_call_ceiling,
    )


def _same_declaration(
    attempt: BenchmarkProviderCallAttempt, declaration: ReservationDeclaration
) -> bool:
    return (
        attempt.stable_unit_id == declaration.stable_unit_id
        and attempt.fixture_id == declaration.fixture_id
        and attempt.task_id == declaration.task_id
        and attempt.repetition == declaration.repetition
        and attempt.provider_role == declaration.provider_role
        and attempt.target_condition == declaration.target_condition
        and attempt.configured_provider == declaration.configured_provider
        and attempt.configured_model == declaration.configured_model
        and attempt.generation_parameter_sha256
        == declaration.generation_parameter_sha256
        and attempt.request_artifact_sha256 == declaration.request_artifact_sha256
    )


class BenchmarkCallLedger:
    """Transaction-owning durable ledger; callers never pass providers or credentials."""

    @staticmethod
    def stage_run(
        db: Session,
        owner_id: UUID,
        protocol: LiveStudyProtocol,
        admission: AdmissionReport,
        *,
        repository_commit_sha: str | None = None,
    ) -> BenchmarkExperimentRun:
        checked_protocol = LiveStudyProtocol.model_validate(
            protocol.model_dump(mode="python", warnings=False)
        )
        checked_admission = AdmissionReport.model_validate(
            admission.model_dump(mode="python", warnings=False)
        )
        if db.get(User, owner_id) is None:
            raise LedgerError("owner_not_found", "Experiment owner does not exist")
        expected_protocol_hash = protocol_sha256(checked_protocol)
        expected_ceiling = calculate_call_ceiling(checked_protocol)
        declared_roles = checked_protocol.call_budgets.by_role
        required_roles = expected_ceiling.by_role
        if any(
            getattr(declared_roles, role) != getattr(required_roles, role)
            for role in _ROLE_COUNTERS
        ) or checked_protocol.call_budgets.total != expected_ceiling.total:
            raise LedgerError(
                "protocol_budget_mismatch",
                "Protocol call budgets differ from the calculated ceiling",
            )
        if (
            not checked_admission.technical_ready
            or not checked_admission.ready
            or checked_admission.blockers
        ):
            raise LedgerError("protocol_not_ready", "Technical admission is not ready")
        if checked_admission.protocol_sha256 != expected_protocol_hash:
            raise LedgerError("protocol_hash_mismatch", "Admission protocol hash differs")
        if checked_admission.dataset_sha256 != checked_protocol.dataset_sha256:
            raise LedgerError("dataset_hash_mismatch", "Admission dataset hash differs")
        if checked_admission.call_ceiling != expected_ceiling:
            raise LedgerError("call_ceiling_mismatch", "Admission call ceiling differs")
        selected_ids = tuple(item.fixture_id for item in checked_protocol.selected_fixtures)
        if checked_admission.admitted_fixture_ids != selected_ids:
            raise LedgerError("fixture_admission_mismatch", "Admitted fixture set differs")
        if checked_admission.human_approval.externally_verified:
            raise LedgerError("external_approval_claim", "External approval cannot be asserted")
        if repository_commit_sha is not None and not re.fullmatch(
            r"[0-9a-f]{40,64}", repository_commit_sha
        ):
            raise LedgerError("invalid_repository_sha", "Repository SHA is invalid")

        bindings = _role_bindings(checked_protocol)
        ceilings = expected_ceiling.by_role
        run = BenchmarkExperimentRun(
            owner_id=owner_id,
            experiment_scope="production_pipeline_paired_v1",
            execution_mode="technical_ledger_only",
            protocol_id=checked_protocol.protocol_id,
            protocol_sha256=expected_protocol_hash,
            dataset_sha256=checked_protocol.dataset_sha256,
            status="staged",
            frozen_role_bindings_json=json.dumps(
                {key: value.model_dump(mode="json") for key, value in bindings.items()},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            analysis_call_ceiling=ceilings.analysis,
            question_generation_call_ceiling=ceilings.question_generation,
            prompt_generation_call_ceiling=ceilings.prompt_generation,
            target_execution_call_ceiling=ceilings.target_execution,
            judge_call_ceiling=ceilings.judge,
            total_call_ceiling=expected_ceiling.total,
            budget_currency=(
                checked_protocol.monetary_budget.currency
                if checked_protocol.monetary_budget is not None
                else None
            ),
            max_spend=(
                checked_protocol.monetary_budget.maximum_cost
                if checked_protocol.monetary_budget is not None
                else None
            ),
            spent_amount=0.0,
            spent_currency=(
                checked_protocol.monetary_budget.currency
                if checked_protocol.monetary_budget is not None
                else None
            ),
            external_human_approval_verified=False,
            repository_commit_sha=repository_commit_sha,
        )
        try:
            db.add(run)
            db.commit()
            db.refresh(run)
            return run
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def start_run(db: Session, run_id: UUID) -> BenchmarkExperimentRun:
        now = _now()
        result = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkExperimentRun)
                .where(
                    BenchmarkExperimentRun.id == run_id,
                    BenchmarkExperimentRun.status == "staged",
                )
                .values(status="running", started_at=now)
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise LedgerError("invalid_run_transition", "Run cannot transition to running")
        db.commit()
        return BenchmarkCallLedger._require_run(db, run_id)

    @staticmethod
    def reserve_call(
        db: Session, run_id: UUID, declaration: ReservationDeclaration
    ) -> BenchmarkProviderCallAttempt:
        checked = ReservationDeclaration.model_validate(
            declaration.model_dump(mode="python", warnings=False)
        )
        try:
            existing = db.scalar(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run_id,
                    BenchmarkProviderCallAttempt.idempotency_key == checked.idempotency_key,
                )
            )
            if existing is not None:
                if not _same_declaration(existing, checked):
                    raise LedgerError(
                        "idempotency_conflict",
                        "Idempotency key is bound to a different immutable call",
                    )
                db.commit()
                return existing

            run = db.get(BenchmarkExperimentRun, run_id)
            if run is None:
                raise LedgerError("run_not_found", "Experiment run does not exist")
            BenchmarkCallLedger._validate_reservation(run, checked)

            # Enforce monetary budget if estimated cost is provided
            if checked.estimated_cost is not None:
                if run.max_spend is None:
                    raise LedgerError(
                        "monetary_budget_not_configured",
                        "Monetary budget not configured for this experiment run",
                    )
                projected = run.spent_amount + run.reserved_spend + checked.estimated_cost
                if projected > run.max_spend:
                    raise LedgerError(
                        "monetary_budget_exhausted",
                        "Estimated cost would exceed authorized monetary budget",
                    )
                if checked.currency != run.budget_currency:
                    raise LedgerError(
                        "currency_mismatch",
                        "Estimated cost currency differs from run budget currency",
                    )

                # Atomically reserve monetary budget against the authoritative run state.
                updated = cast(
                    CursorResult[Any],
                    db.execute(
                        update(BenchmarkExperimentRun)
                        .where(
                            BenchmarkExperimentRun.id == run_id,
                            BenchmarkExperimentRun.spent_amount
                            + BenchmarkExperimentRun.reserved_spend
                            + checked.estimated_cost
                            <= run.max_spend,
                        )
                        .values(
                            reserved_spend=BenchmarkExperimentRun.reserved_spend
                            + checked.estimated_cost,
                        )
                    )
                )
                if updated.rowcount != 1:
                    raise LedgerError(
                        "monetary_budget_exhausted",
                        "Estimated cost would exceed authorized monetary budget",
                    )
            ceiling_name = _ROLE_CEILINGS[checked.provider_role]
            counter_name = _ROLE_COUNTERS[checked.provider_role]
            counter = getattr(BenchmarkExperimentRun, counter_name)
            ceiling = getattr(BenchmarkExperimentRun, ceiling_name)
            total_consumed = (
                BenchmarkExperimentRun.reserved_count
                + BenchmarkExperimentRun.succeeded_count
                + BenchmarkExperimentRun.failed_count
            )
            sequence_value = cast(
                int | None,
                db.scalar(
                    update(BenchmarkExperimentRun)
                    .where(
                        BenchmarkExperimentRun.id == run_id,
                        BenchmarkExperimentRun.status == "running",
                        counter < ceiling,
                        total_consumed < BenchmarkExperimentRun.total_call_ceiling,
                    )
                    .values(
                        {
                            counter_name: counter + 1,
                            "reserved_count": BenchmarkExperimentRun.reserved_count + 1,
                            "next_attempt_sequence": (
                                BenchmarkExperimentRun.next_attempt_sequence + 1
                            ),
                        }
                    )
                    .returning(BenchmarkExperimentRun.next_attempt_sequence)
                )
            )
            if sequence_value is None:
                db.rollback()
                BenchmarkCallLedger._raise_reservation_rejection(db, run_id, checked)
            sequence = sequence_value
            attempt = BenchmarkProviderCallAttempt(
                experiment_run_id=run_id,
                stable_unit_id=checked.stable_unit_id,
                fixture_id=checked.fixture_id,
                task_id=checked.task_id,
                repetition=checked.repetition,
                provider_role=checked.provider_role,
                target_condition=checked.target_condition,
                sequence_number=sequence,
                idempotency_key=checked.idempotency_key,
                configured_provider=checked.configured_provider,
                configured_model=checked.configured_model,
                generation_parameter_sha256=checked.generation_parameter_sha256,
                request_artifact_sha256=checked.request_artifact_sha256,
                status="reserved",
                reserved_at=_now(),
                cost_estimate=checked.estimated_cost,
                currency=checked.currency,
                observation_outcome="not_recorded",
            )
            db.add(attempt)
            db.commit()
            db.refresh(attempt)
            return attempt
        except IntegrityError as exc:
            db.rollback()
            existing = db.scalar(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run_id,
                    BenchmarkProviderCallAttempt.idempotency_key == checked.idempotency_key,
                )
            )
            if existing is not None and _same_declaration(existing, checked):
                db.commit()
                return existing
            raise LedgerError(
                "idempotency_conflict",
                "Idempotency key is bound to a different immutable call",
            ) from exc
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def mark_started(db: Session, attempt_id: UUID) -> BenchmarkProviderCallAttempt:
        attempt = BenchmarkCallLedger._require_attempt(db, attempt_id)
        BenchmarkCallLedger._require_running_run(db, attempt.experiment_run_id)
        result = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkProviderCallAttempt)
                .where(
                    BenchmarkProviderCallAttempt.id == attempt_id,
                    BenchmarkProviderCallAttempt.status == "reserved",
                )
                .values(status="started", started_at=_now())
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise LedgerError("invalid_attempt_transition", "Attempt cannot transition to started")
        db.commit()
        return BenchmarkCallLedger._require_attempt(db, attempt_id)

    @staticmethod
    def mark_succeeded(
        db: Session, attempt_id: UUID, result_data: AttemptSuccess
    ) -> BenchmarkProviderCallAttempt:
        checked = AttemptSuccess.model_validate(
            result_data.model_dump(mode="python", warnings=False)
        )
        attempt = BenchmarkCallLedger._require_attempt(db, attempt_id)
        run = BenchmarkCallLedger._require_running_run(db, attempt.experiment_run_id)
        if checked.cost_estimate is not None and checked.currency != run.budget_currency:
            db.rollback()
            raise LedgerError("currency_mismatch", "Attempt currency differs from run budget")
        settled_cost, settled_currency = BenchmarkCallLedger._settle_reserved_cost(
            db,
            attempt,
            run,
            checked.cost_estimate,
            checked.currency,
        )
        changed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkProviderCallAttempt)
                .where(
                    BenchmarkProviderCallAttempt.id == attempt_id,
                    BenchmarkProviderCallAttempt.status == "started",
                )
                .values(
                    status="succeeded",
                    finished_at=_now(),
                    input_tokens=checked.input_tokens,
                    output_tokens=checked.output_tokens,
                    total_tokens=checked.total_tokens,
                    cost_estimate=settled_cost,
                    currency=settled_currency,
                    fallback_classification=checked.fallback_classification,
                    observation_outcome=checked.observation_outcome,
                    response_artifact_sha256=checked.response_artifact_sha256,
                )
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise LedgerError("invalid_attempt_transition", "Attempt cannot succeed")
        db.execute(
            update(BenchmarkExperimentRun)
            .where(BenchmarkExperimentRun.id == run.id)
            .values(
                reserved_count=BenchmarkExperimentRun.reserved_count - 1,
                succeeded_count=BenchmarkExperimentRun.succeeded_count + 1,
            )
        )
        db.commit()
        return BenchmarkCallLedger._require_attempt(db, attempt_id)

    @staticmethod
    def mark_failed(
        db: Session, attempt_id: UUID, failure: AttemptFailure
    ) -> BenchmarkProviderCallAttempt:
        checked = AttemptFailure.model_validate(
            failure.model_dump(mode="python", warnings=False)
        )
        attempt = BenchmarkCallLedger._require_attempt(db, attempt_id)
        run = BenchmarkCallLedger._require_running_run(db, attempt.experiment_run_id)
        changed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkProviderCallAttempt)
                .where(
                    BenchmarkProviderCallAttempt.id == attempt_id,
                    BenchmarkProviderCallAttempt.status == "started",
                )
                .values(
                    status="failed",
                    finished_at=_now(),
                    safe_error_type=checked.safe_error_type,
                    safe_error_code=checked.safe_error_code,
                    fallback_classification=checked.fallback_classification,
                    observation_outcome=checked.observation_outcome,
                )
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise LedgerError("invalid_attempt_transition", "Attempt cannot fail")
        BenchmarkCallLedger._settle_reserved_cost(db, attempt, run, None, None)
        db.execute(
            update(BenchmarkExperimentRun)
            .where(BenchmarkExperimentRun.id == run.id)
            .values(
                reserved_count=BenchmarkExperimentRun.reserved_count - 1,
                failed_count=BenchmarkExperimentRun.failed_count + 1,
            )
        )
        db.commit()
        return BenchmarkCallLedger._require_attempt(db, attempt_id)

    @staticmethod
    def mark_failed_from_exception(
        db: Session,
        attempt_id: UUID,
        error: BaseException,
        *,
        safe_error_code: SafeCode,
        fallback_classification: FallbackClassification = "provider_failed",
    ) -> BenchmarkProviderCallAttempt:
        return BenchmarkCallLedger.mark_failed(
            db,
            attempt_id,
            AttemptFailure(
                safe_error_type=type(error).__name__,
                safe_error_code=safe_error_code,
                fallback_classification=fallback_classification,
                observation_outcome="failed",
            ),
        )

    @staticmethod
    def cancel_reservation(db: Session, attempt_id: UUID) -> BenchmarkProviderCallAttempt:
        attempt = BenchmarkCallLedger._require_attempt(db, attempt_id)
        run = BenchmarkCallLedger._require_running_run(db, attempt.experiment_run_id)
        counter_name = _ROLE_COUNTERS[attempt.provider_role]
        counter = getattr(BenchmarkExperimentRun, counter_name)
        changed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkProviderCallAttempt)
                .where(
                    BenchmarkProviderCallAttempt.id == attempt_id,
                    BenchmarkProviderCallAttempt.status == "reserved",
                )
                .values(status="cancelled", finished_at=_now())
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise LedgerError("invalid_attempt_transition", "Only a reservation may cancel")
        BenchmarkCallLedger._release_reserved_cost(db, run.id, attempt.cost_estimate)
        db.execute(
            update(BenchmarkExperimentRun)
            .where(BenchmarkExperimentRun.id == run.id)
            .values(
                {
                    counter_name: counter - 1,
                    "reserved_count": BenchmarkExperimentRun.reserved_count - 1,
                    "cancelled_count": BenchmarkExperimentRun.cancelled_count + 1,
                }
            )
        )
        db.commit()
        return BenchmarkCallLedger._require_attempt(db, attempt_id)

    @staticmethod
    def budget_snapshot(db: Session, run_id: UUID) -> BudgetSnapshot:
        run = BenchmarkCallLedger._require_run(db, run_id)
        ceilings = _role_ceilings(run)
        consumed = _role_counts(run)
        remaining = RoleCallBudget(
            **{
                role: max(0, getattr(ceilings, role) - getattr(consumed, role))
                for role in _ROLE_COUNTERS
            }
        )
        total_used = run.reserved_count + run.succeeded_count + run.failed_count
        remaining_spend = None
        if run.max_spend is not None:
            remaining_spend = max(
                0.0, run.max_spend - run.spent_amount - run.reserved_spend
            )
        return BudgetSnapshot(
            run_id=run.id,
            status=cast(
                Literal["staged", "running", "completed", "failed", "aborted"],
                run.status,
            ),
            ceilings=ceilings,
            total_ceiling=run.total_call_ceiling,
            consumed_by_role=consumed,
            reserved=run.reserved_count,
            succeeded=run.succeeded_count,
            failed=run.failed_count,
            cancelled=run.cancelled_count,
            remaining_by_role=remaining,
            remaining_total=max(0, run.total_call_ceiling - total_used),
            max_spend=run.max_spend,
            spent_amount=run.spent_amount,
            spent_currency=run.spent_currency,
            budget_currency=run.budget_currency,
            remaining_spend=remaining_spend,
        )

    @staticmethod
    def abort_run(db: Session, run_id: UUID, reason_code: SafeCode) -> BenchmarkExperimentRun:
        return BenchmarkCallLedger._terminate_run(db, run_id, "aborted", _safe_code(reason_code))

    @staticmethod
    def fail_run(db: Session, run_id: UUID, reason_code: SafeCode) -> BenchmarkExperimentRun:
        return BenchmarkCallLedger._terminate_run(db, run_id, "failed", _safe_code(reason_code))

    @staticmethod
    def finalize_run(db: Session, run_id: UUID) -> BenchmarkExperimentRun:
        run = BenchmarkCallLedger._require_run(db, run_id)
        if run.status != "running":
            db.rollback()
            raise LedgerError("invalid_run_transition", "Only a running run may finalize")
        counts: dict[str, int] = {}
        for status, count in (
            db.execute(
                select(
                    BenchmarkProviderCallAttempt.status,
                    func.count(BenchmarkProviderCallAttempt.id),
                )
                .where(BenchmarkProviderCallAttempt.experiment_run_id == run_id)
                .group_by(BenchmarkProviderCallAttempt.status)
            ).all()
        ):
            counts[status] = count
        if counts.get("reserved", 0) or counts.get("started", 0) or counts.get("failed", 0):
            db.rollback()
            raise LedgerError("inconsistent_ledger", "Ledger contains unfinished or failed calls")
        if (
            run.reserved_count != 0
            or run.succeeded_count != counts.get("succeeded", 0)
            or run.failed_count != 0
            or run.cancelled_count != counts.get("cancelled", 0)
        ):
            db.rollback()
            raise LedgerError("inconsistent_ledger", "Run counters differ from attempt records")
        changed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkExperimentRun)
                .where(
                    BenchmarkExperimentRun.id == run_id,
                    BenchmarkExperimentRun.status == "running",
                    BenchmarkExperimentRun.reserved_count == 0,
                    BenchmarkExperimentRun.failed_count == 0,
                )
                .values(status="completed", finished_at=_now())
            ),
        )
        if changed.rowcount != 1:
            db.rollback()
            raise LedgerError("inconsistent_ledger", "Run changed while finalizing")
        db.commit()
        return BenchmarkCallLedger._require_run(db, run_id)

    @staticmethod
    def _validate_reservation(
        run: BenchmarkExperimentRun, declaration: ReservationDeclaration
    ) -> None:
        if run.status != "running":
            raise LedgerError("run_not_running", "Experiment run is not running")
        if declaration.protocol_sha256 != run.protocol_sha256:
            raise LedgerError("protocol_hash_mismatch", "Reservation protocol hash differs")
        if declaration.dataset_sha256 != run.dataset_sha256:
            raise LedgerError("dataset_hash_mismatch", "Reservation dataset hash differs")
        bindings = _binding_data(run)
        binding = bindings.get(declaration.provider_role)
        if binding is None:
            raise LedgerError("unknown_or_disabled_role", "Provider role is not configured")
        if (
            declaration.configured_provider != binding.provider
            or declaration.configured_model != binding.model
        ):
            raise LedgerError("provider_assignment_mismatch", "Provider assignment differs")
        if declaration.generation_parameter_sha256 != binding.generation_parameter_sha256:
            raise LedgerError(
                "generation_parameter_mismatch", "Generation parameter hash differs"
            )

    @staticmethod
    def _raise_reservation_rejection(
        db: Session, run_id: UUID, declaration: ReservationDeclaration
    ) -> None:
        run = BenchmarkCallLedger._require_run(db, run_id)
        BenchmarkCallLedger._validate_reservation(run, declaration)
        counter = getattr(run, _ROLE_COUNTERS[declaration.provider_role])
        ceiling = getattr(run, _ROLE_CEILINGS[declaration.provider_role])
        if counter >= ceiling:
            raise LedgerError("role_budget_exhausted", "Provider-role budget is exhausted")
        total = run.reserved_count + run.succeeded_count + run.failed_count
        if total >= run.total_call_ceiling:
            raise LedgerError("total_budget_exhausted", "Total provider-call budget is exhausted")
        raise LedgerError("reservation_conflict", "Reservation could not be committed")

    @staticmethod
    def _terminate_run(
        db: Session,
        run_id: UUID,
        terminal_status: Literal["failed", "aborted"],
        reason_code: SafeCode,
    ) -> BenchmarkExperimentRun:
        now = _now()
        terminal_values: dict[str, Any] = {
            "status": terminal_status,
            "finished_at": now,
        }
        if terminal_status == "aborted":
            terminal_values.update(aborted_at=now, abort_reason_code=reason_code)
        else:
            terminal_values["failure_reason_code"] = reason_code
        claimed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkExperimentRun)
                .where(
                    BenchmarkExperimentRun.id == run_id,
                    BenchmarkExperimentRun.status.in_(("staged", "running")),
                )
                .values(**terminal_values)
            ),
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise LedgerError("invalid_run_transition", "Run is already terminal")
        run = BenchmarkCallLedger._require_run(db, run_id)
        attempts = list(
            db.scalars(
                select(BenchmarkProviderCallAttempt).where(
                    BenchmarkProviderCallAttempt.experiment_run_id == run_id,
                    BenchmarkProviderCallAttempt.status.in_(("reserved", "started")),
                )
            )
        )
        cancelled = 0
        failed = 0
        for attempt in attempts:
            if attempt.status == "reserved":
                BenchmarkCallLedger._release_reserved_cost(
                    db, run_id, attempt.cost_estimate
                )
                attempt.status = "cancelled"
                cancelled += 1
                counter_name = _ROLE_COUNTERS[attempt.provider_role]
                setattr(run, counter_name, getattr(run, counter_name) - 1)
            else:
                BenchmarkCallLedger._settle_reserved_cost(
                    db, attempt, run, None, None
                )
                attempt.status = "failed"
                attempt.safe_error_type = "RunTerminated"
                attempt.safe_error_code = reason_code
                attempt.fallback_classification = "none"
                attempt.observation_outcome = "failed"
                failed += 1
            attempt.finished_at = _now()
        run.reserved_count = 0
        run.cancelled_count += cancelled
        run.failed_count += failed
        db.commit()
        db.refresh(run)
        return run

    @staticmethod
    def _release_reserved_cost(
        db: Session, run_id: UUID, reserved_cost: float | None
    ) -> None:
        if reserved_cost is None:
            return
        changed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkExperimentRun)
                .where(
                    BenchmarkExperimentRun.id == run_id,
                    BenchmarkExperimentRun.reserved_spend >= reserved_cost,
                )
                .values(
                    reserved_spend=BenchmarkExperimentRun.reserved_spend
                    - reserved_cost
                )
            ),
        )
        if changed.rowcount != 1:
            db.rollback()
            raise LedgerError(
                "inconsistent_monetary_reservation",
                "Reserved monetary amount is inconsistent with the experiment run",
            )

    @staticmethod
    def _settle_reserved_cost(
        db: Session,
        attempt: BenchmarkProviderCallAttempt,
        run: BenchmarkExperimentRun,
        actual_cost: float | None,
        actual_currency: str | None,
    ) -> tuple[float | None, str | None]:
        reserved_cost = attempt.cost_estimate
        if actual_cost is None and reserved_cost is None:
            return None, None
        settled_cost = reserved_cost if actual_cost is None else actual_cost
        settled_currency = (
            actual_currency
            if actual_cost is not None
            else attempt.currency
        )
        if settled_currency != run.budget_currency:
            db.rollback()
            raise LedgerError("currency_mismatch", "Attempt currency differs from run budget")
        if reserved_cost is not None and settled_cost is not None:
            if settled_cost > reserved_cost:
                db.rollback()
                raise LedgerError(
                    "actual_cost_exceeds_reservation",
                    "Settled cost exceeds its pre-call monetary reservation",
                )
        if run.max_spend is None:
            db.rollback()
            raise LedgerError(
                "monetary_budget_not_configured",
                "Monetary budget not configured for this experiment run",
            )
        release_cost = reserved_cost or 0.0
        charge_cost = settled_cost or 0.0
        changed = cast(
            CursorResult[Any],
            db.execute(
                update(BenchmarkExperimentRun)
                .where(
                    BenchmarkExperimentRun.id == run.id,
                    BenchmarkExperimentRun.reserved_spend >= release_cost,
                    or_(
                        BenchmarkExperimentRun.max_spend.is_(None),
                        BenchmarkExperimentRun.spent_amount
                        + BenchmarkExperimentRun.reserved_spend
                        - release_cost
                        + charge_cost
                        <= BenchmarkExperimentRun.max_spend,
                    ),
                )
                .values(
                    reserved_spend=(
                        BenchmarkExperimentRun.reserved_spend - release_cost
                    ),
                    spent_amount=BenchmarkExperimentRun.spent_amount + charge_cost,
                    spent_currency=settled_currency,
                )
            ),
        )
        if changed.rowcount != 1:
            db.rollback()
            raise LedgerError(
                "monetary_budget_exhausted",
                "Settled cost exceeds the authorized monetary budget",
            )
        return settled_cost, settled_currency

    @staticmethod
    def _require_run(db: Session, run_id: UUID) -> BenchmarkExperimentRun:
        run = db.get(BenchmarkExperimentRun, run_id)
        if run is None:
            raise LedgerError("run_not_found", "Experiment run does not exist")
        return run

    @staticmethod
    def _require_running_run(db: Session, run_id: UUID) -> BenchmarkExperimentRun:
        run = BenchmarkCallLedger._require_run(db, run_id)
        if run.status != "running":
            db.rollback()
            raise LedgerError("run_not_running", "Experiment run is not running")
        return run

    @staticmethod
    def _require_attempt(db: Session, attempt_id: UUID) -> BenchmarkProviderCallAttempt:
        attempt = db.get(BenchmarkProviderCallAttempt, attempt_id)
        if attempt is None:
            raise LedgerError("attempt_not_found", "Provider-call attempt does not exist")
        return attempt


def finite_cost(value: float) -> float:
    """Small public guard useful to adapters before constructing completion metadata."""

    if not math.isfinite(value) or value < 0:
        raise ValueError("Cost estimate must be finite and nonnegative")
    return value
