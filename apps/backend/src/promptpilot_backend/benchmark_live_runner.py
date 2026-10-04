"""Guarded per-unit production treatment pipeline runner.

This module executes the frozen production pipeline for a single
task/repetition unit under the guarded experiment protocol. Every
provider-backed stage passes through :class:`ProviderCallExecutor`,
so no provider call can occur before a durable reservation exists
and no call can disappear from the ledger.

The runner never fabricates study data: clarification questions are
resolved only from reviewed fixture answers, unmatched gaps and
unanswered questions are skipped per the frozen policy, and any
fallback, drift, or budget violation fails the unit closed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer_v2 import analyze_hybrid
from .benchmark import BenchmarkDataset, BenchmarkTask, repository_sha
from .benchmark_call_ledger import (
    BenchmarkCallLedger,
    ProviderRole,
    TargetCondition,
)
from .benchmark_experiment_binding import ProtocolBinding
from .benchmark_experiment_execution import (
    ExecutionGateError,
    PartialExperimentUnit,
    ProviderCallExecutor,
    ReservedCall,
    approved_condition_order,
    assert_baseline_has_no_treatment_artifacts,
    assert_baseline_prompt,
    verify_fixture_before_target_execution,
)
from .benchmark_experiment_results import (
    EvaluationArtifact,
    ExperimentUnit,
    ProvenanceArtifacts,
    ProviderObservationArtifact,
    QuestionArtifact,
    StageArtifact,
    UnitDisposition,
)
from .benchmark_fixtures import (
    FixtureManifest,
    GapMatchKey,
    generation_inputs,
    manifest_sha256,
)
from .benchmark_provider_adapter import ProviderAdapterFactory
from .benchmark_stop_rules import StopRuleEvaluator
from .conversation_service import add_message, create_conversation
from .document_service import DocumentService
from .evaluation_service import ResponseEvaluationService
from .execution_service import LLMExecutionService
from .llm_provider import AIAnalysis, ProviderUnavailable
from .memory_service import ProjectMemoryService
from .models import (
    BenchmarkExperimentRun,
    Conversation,
    DocumentChunk,
    InformationGap,
    Message,
    ModelRun,
    Project,
    Question,
    QuestionSession,
    User,
)
from .production_benchmark_protocol import LiveStudyProtocol
from .project_policy import ProjectRole, require_project_access
from .project_service import create_project
from .prompt_generation import (
    PromptGenerationResult,
    PromptGenerator,
    build_generation_input,
    persist_generation,
)
from .question_generator import GeneratedQuestion
from .question_service import (
    answer_question,
    create_question_session,
    mark_question_skipped,
    next_question,
    reanalyze_after_answer,
    skip_and_next_question,
)
from .schemas import (
    ConversationCreateRequest,
    LLMJudgeOutput,
    MessageCreateRequest,
    ProjectCreateRequest,
)

ExecutionMode = Literal["offline_dry_run", "live"]


@dataclass(frozen=True)
class UnitExecutionContext:
    """Immutable identity of one task/repetition unit."""

    unit_id: str
    task_id: str
    task_category: str
    repetition: int
    fixture_id: str
    manifest: FixtureManifest
    manifest_path: Path
    condition_order: tuple[TargetCondition, TargetCondition]


@dataclass(frozen=True)
class _UnitApparatus:
    """Shared per-unit experimental apparatus."""

    owner: User
    project: Project
    conversation: Conversation
    message: Message
    task: BenchmarkTask
    original_task: str


@dataclass
class _UnitEvidence:
    """Mutable evidence collected while a unit executes."""

    stages: list[StageArtifact] = field(default_factory=list)
    questions: list[QuestionArtifact] = field(default_factory=list)
    fallback_seen: bool = False
    treatment: dict[str, Any] | None = None


@dataclass(frozen=True)
class _LedgerCallRecord:
    call: ReservedCall
    provider: str
    model: str


class UnitExecutionError(RuntimeError):
    """A unit failed a frozen protocol invariant."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _parse_structured[T: BaseModel](response: Any, model: type[T], role: str) -> T:
    """Parse an adapter response into its validated structured output."""

    content = response.get("content") if isinstance(response, dict) else None
    if not isinstance(content, str):
        raise ProviderUnavailable(f"{role} response carried no structured content")
    try:
        return model.model_validate(json.loads(content))
    except ValueError as error:
        raise ProviderUnavailable(
            f"{role} response was not valid structured output"
        ) from error


def _execution_response(response: Any) -> dict[str, Any]:
    """Convert an adapter target-execution response into an execution result."""

    metadata = response.get("response_metadata") or {}
    usage = {
        key: value
        for key, value in (
            ("prompt_tokens", response.get("input_tokens")),
            ("completion_tokens", response.get("output_tokens")),
            ("total_tokens", response.get("total_tokens")),
        )
        if value is not None
    }
    return {
        "response_text": response.get("content", ""),
        "finish_reason": metadata.get("finish_reason"),
        "usage": usage,
    }


class LedgerGate:
    """Unit-scoped gateway that routes every provider call through the ledger."""

    def __init__(
        self,
        *,
        executor: ProviderCallExecutor,
        unit_id: str,
        task_id: str,
        fixture_id: str,
        repetition: int,
    ) -> None:
        self._executor = executor
        self._unit_id = unit_id
        self._task_id = task_id
        self._fixture_id = fixture_id
        self._repetition = repetition
        self._records: list[_LedgerCallRecord] = []

    @property
    def unit_id(self) -> str:
        return self._unit_id

    def execute[T](
        self,
        *,
        provider: Any,
        role: ProviderRole,
        provider_name: str,
        model_name: str,
        request_payload: Any,
        invoke: Callable[[], T],
        stable_token: str,
        target_condition: TargetCondition | None = None,
    ) -> T:
        """Reserve, start, invoke, and settle one provider call."""

        captured: list[Any] = []

        def capturing_invoke() -> Any:
            result = invoke()
            captured.append(result)
            return result

        call = self._executor.execute(
            provider=provider,
            role=role,
            stable_unit_id=f"{self._unit_id}:{role}",
            task_id=self._task_id,
            fixture_id=self._fixture_id,
            repetition=self._repetition,
            provider_name=provider_name,
            model_name=model_name,
            request_payload=request_payload,
            invoke=capturing_invoke,
            target_condition=target_condition,
            stable_token=stable_token,
        )
        self._records.append(
            _LedgerCallRecord(call=call, provider=provider_name, model=model_name)
        )
        if call.status != "succeeded":
            raise ProviderUnavailable(f"Ledger-gated {role} provider call failed")
        if not captured:
            raise ProviderUnavailable(
                f"Ledger-gated {role} provider call was already settled; "
                "its output is not recoverable from the ledger"
            )
        return cast(T, captured[0])

    def provider_observations(self) -> list[ProviderObservationArtifact]:
        return [
            ProviderObservationArtifact(
                role=record.call.role,
                provider=record.provider,
                model=record.model,
                request_sha256=record.call.request_sha256,
                status=record.call.status,
                fallback_classification=(
                    "none" if record.call.status == "succeeded" else "provider_failed"
                ),
                safe_error_code=record.call.safe_error_code,
            )
            for record in self._records
        ]


class LedgerGatedAnalysisProvider:
    """AnalysisProvider whose every call is reserved and settled on the ledger."""

    def __init__(self, gate: LedgerGate, adapter: Any) -> None:
        self._gate = gate
        self._adapter = adapter
        self.name = cast(str, adapter.provider_name)
        self.model = cast(str, adapter.model_name)

    def analyze(self, prompt: str) -> AIAnalysis:
        return self._gate.execute(
            provider=self._adapter,
            role="analysis",
            provider_name=self._adapter.provider_name,
            model_name=self._adapter.model_name,
            request_payload={"prompt": prompt},
            invoke=lambda: _parse_structured(
                self._adapter.analyze(prompt), AIAnalysis, "analysis"
            ),
            stable_token=f"{self._gate.unit_id}:analysis",
        )


class LedgerGatedQuestionProvider:
    """QuestionProvider whose every call is reserved and settled on the ledger."""

    def __init__(self, gate: LedgerGate, adapter: Any) -> None:
        self._gate = gate
        self._adapter = adapter
        self._sequence = 0
        self.name = cast(str, adapter.provider_name)
        self.model = cast(str, adapter.model_name)

    def generate_question(self, payload: dict[str, object]) -> GeneratedQuestion:
        self._sequence += 1
        return self._gate.execute(
            provider=self._adapter,
            role="question_generation",
            provider_name=self._adapter.provider_name,
            model_name=self._adapter.model_name,
            request_payload=payload,
            invoke=lambda: _parse_structured(
                self._adapter.generate_question(payload),
                GeneratedQuestion,
                "question_generation",
            ),
            stable_token=f"{self._gate.unit_id}:question:{self._sequence}",
        )


class LedgerGatedPromptProvider:
    """PromptProvider whose every call is reserved and settled on the ledger."""

    def __init__(self, gate: LedgerGate, adapter: Any) -> None:
        self._gate = gate
        self._adapter = adapter
        self.name = cast(str, adapter.provider_name)
        self.model = cast(str, adapter.model_name)

    def generate_prompt(self, payload: dict[str, Any]) -> PromptGenerationResult:
        return self._gate.execute(
            provider=self._adapter,
            role="prompt_generation",
            provider_name=self._adapter.provider_name,
            model_name=self._adapter.model_name,
            request_payload=payload,
            invoke=lambda: _parse_structured(
                self._adapter.generate_prompt(payload),
                PromptGenerationResult,
                "prompt_generation",
            ),
            stable_token=f"{self._gate.unit_id}:prompt_generation",
        )


class LedgerGatedExecutionProvider:
    """ExecutionProvider whose every call is reserved and settled on the ledger."""

    def __init__(
        self, gate: LedgerGate, adapter: Any, condition: TargetCondition
    ) -> None:
        self._gate = gate
        self._adapter = adapter
        self._condition = condition
        self.name = cast(str, adapter.provider_name)
        self.model = cast(str, adapter.model_name)

    def generate_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = payload.get("prompt", "")
        parameters = payload.get("parameters") or {}
        return self._gate.execute(
            provider=self._adapter,
            role="target_execution",
            provider_name=self._adapter.provider_name,
            model_name=self._adapter.model_name,
            request_payload={"prompt": prompt, "parameters": parameters},
            invoke=lambda: _execution_response(
                self._adapter.generate(prompt, parameters)
            ),
            stable_token=f"{self._gate.unit_id}:{self._condition}:target",
            target_condition=self._condition,
        )


class LedgerGatedJudgeProvider:
    """JudgeProvider whose every call is reserved and settled on the ledger."""

    def __init__(self, gate: LedgerGate, adapter: Any) -> None:
        self._gate = gate
        self._adapter = adapter
        self.name = cast(str, adapter.provider_name)
        self.model = cast(str, adapter.model_name)

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any] | None = None,
    ) -> LLMJudgeOutput:
        payload = {
            "task": task,
            "response_a": response_a,
            "response_b": response_b,
            "evidence": evidence or {},
        }
        return self._gate.execute(
            provider=self._adapter,
            role="judge",
            provider_name=self._adapter.provider_name,
            model_name=self._adapter.model_name,
            request_payload=payload,
            invoke=lambda: _parse_structured(
                self._adapter.judge_response(task, response_a, response_b, evidence),
                LLMJudgeOutput,
                "judge",
            ),
            stable_token=f"{self._gate.unit_id}:judge",
        )


class LiveExperimentRunner:
    """Executes guarded production pipeline units against a staged run."""

    def __init__(
        self,
        *,
        db: Session,
        run_id: UUID,
        binding: ProtocolBinding,
        protocol: LiveStudyProtocol,
        dataset: BenchmarkDataset,
        fixture_manifests: list[tuple[FixtureManifest, Path]],
        adapter_factory: ProviderAdapterFactory,
        launch_gate_report: Any = None,
        execution_mode: ExecutionMode = "offline_dry_run",
    ) -> None:
        if execution_mode not in {"offline_dry_run", "live"}:
            raise ValueError(f"Unsupported execution mode: {execution_mode}")
        if execution_mode != "live":
            raise ExecutionGateError(
                "live_execution_required",
                "Per-unit execution cannot use synthetic offline provider outputs",
            )
        if adapter_factory.mode != execution_mode:
            raise ExecutionGateError(
                "adapter_mode_mismatch",
                "Provider adapter mode differs from the authorized execution mode",
            )
        if (
            protocol.evaluation.primary != "llm_judge"
            or binding.evaluation_primary != "llm_judge"
        ):
            raise ExecutionGateError(
                "llm_judge_required",
                "The frozen production benchmark requires llm_judge evaluation",
            )
        if protocol.providers.judge is None:
            raise ExecutionGateError(
                "judge_not_assigned",
                "LLM-judge evaluation requires a frozen judge provider assignment",
            )
        self._db = db
        self._run_id = run_id
        self._binding = binding
        self._protocol = protocol
        self._dataset = dataset
        self._fixture_manifests = fixture_manifests
        self._adapter_factory = adapter_factory
        self._execution_mode = execution_mode
        self._executor = ProviderCallExecutor(
            db=db,
            run_id=run_id,
            binding=binding,
            launch_gate_report=launch_gate_report,
            execution_mode=execution_mode,
        )
        self._stop_evaluator = StopRuleEvaluator(protocol, binding, launch_gate_report)

    def run_all_units(self) -> list[ExperimentUnit]:
        """Execute every admitted unit, stopping at the first incomplete unit."""

        units: list[ExperimentUnit] = []
        for manifest, manifest_path in self._fixture_manifests:
            for repetition in range(1, self._binding.repetitions + 1):
                unit = self.run_production_pipeline_unit(
                    fixture_id=manifest.fixture_id,
                    task_id=manifest.task_id,
                    repetition=repetition,
                    manifest=manifest,
                    manifest_path=manifest_path,
                )
                units.append(unit)
                if unit.disposition != "complete_pair":
                    return units
        return units

    def run_production_pipeline_unit(
        self,
        *,
        fixture_id: str,
        task_id: str,
        repetition: int,
        manifest: FixtureManifest,
        manifest_path: Path,
    ) -> ExperimentUnit:
        unit_id = f"{task_id}#r{repetition}"
        condition_order = approved_condition_order(repetition)
        context = UnitExecutionContext(
            unit_id=unit_id,
            task_id=task_id,
            task_category=self._dataset.task(task_id).category,
            repetition=repetition,
            fixture_id=fixture_id,
            manifest=manifest,
            manifest_path=manifest_path,
            condition_order=condition_order,
        )
        gate = LedgerGate(
            executor=self._executor,
            unit_id=unit_id,
            task_id=task_id,
            fixture_id=fixture_id,
            repetition=repetition,
        )
        evidence = _UnitEvidence()
        evidence.stages.append(
            StageArtifact(
                name="fixture_admission",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "fixture_id": fixture_id,
                    "manifest_sha256": manifest_sha256(manifest),
                },
            )
        )
        condition_results: dict[str, dict[str, Any]] = {}
        try:
            apparatus = self._prepare_unit_apparatus(context)
            for condition in condition_order:
                if condition == "baseline":
                    condition_results[condition] = self._run_baseline(
                        context, apparatus, gate, evidence
                    )
                else:
                    condition_results[condition] = self._run_promptpilot(
                        context, apparatus, gate, evidence
                    )
        except PartialExperimentUnit as error:
            return self._unit_record(
                context=context,
                gate=gate,
                evidence=evidence,
                disposition="partial_unit",
                condition_results=condition_results,
                failure_reason=str(error),
            )
        except Exception as error:
            self._db.rollback()
            return self._failed_unit(
                context=context,
                gate=gate,
                evidence=evidence,
                condition_results=condition_results,
                error=error,
            )
        try:
            evaluation = self._evaluate_pair(context, apparatus, gate, condition_results)
        except UnitExecutionError as error:
            return self._unit_record(
                context=context,
                gate=gate,
                evidence=evidence,
                disposition="invalid_pair",
                condition_results=condition_results,
                failure_reason=str(error),
            )
        except Exception as error:
            self._db.rollback()
            return self._failed_unit(
                context=context,
                gate=gate,
                evidence=evidence,
                condition_results=condition_results,
                error=error,
            )
        evidence.stages.append(
            StageArtifact(
                name="evaluation",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={"evaluation_id": evaluation.evaluation_id},
            )
        )
        return self._unit_record(
            context=context,
            gate=gate,
            evidence=evidence,
            disposition="complete_pair",
            condition_results=condition_results,
            evaluation=evaluation,
        )

    def _prepare_unit_apparatus(self, context: UnitExecutionContext) -> _UnitApparatus:
        run = self._db.get(BenchmarkExperimentRun, self._run_id)
        if run is None:
            raise UnitExecutionError("run_not_found", "Experiment run does not exist")
        if run.status != "running":
            raise UnitExecutionError("run_not_running", "Experiment run is not running")
        owner = self._db.get(User, run.owner_id)
        if owner is None or owner.status != "active":
            raise UnitExecutionError(
                "owner_not_active", "Experiment owner is not an active user"
            )
        task = self._dataset.task(context.task_id)
        original_task = task.task_text
        project = create_project(
            self._db,
            owner,
            ProjectCreateRequest(
                name=f"Live benchmark {context.task_id} r{context.repetition}"
            ),
        )
        require_project_access(self._db, project.id, owner.id, ProjectRole.OWNER)
        conversation = create_conversation(
            self._db, project, ConversationCreateRequest(title="Live benchmark")
        )
        message = add_message(
            self._db,
            conversation,
            MessageCreateRequest(role="user", content=original_task),
            idempotency_key=None,
        )
        return _UnitApparatus(
            owner=owner,
            project=project,
            conversation=conversation,
            message=message,
            task=task,
            original_task=original_task,
        )

    def _run_baseline(
        self,
        context: UnitExecutionContext,
        apparatus: _UnitApparatus,
        gate: LedgerGate,
        evidence: _UnitEvidence,
    ) -> dict[str, Any]:
        """Execute the baseline condition: the exact original task, nothing else."""

        verify_fixture_before_target_execution(
            binding=self._binding,
            fixture_id=context.fixture_id,
            manifest=context.manifest,
            dataset=self._dataset,
            manifest_path=context.manifest_path,
            execution_mode=self._execution_mode,
        )
        assert_baseline_prompt(apparatus.original_task, apparatus.original_task)
        target_adapter = self._adapter_factory.create_adapter(
            role="target_execution",
            provider=self._protocol.providers.baseline_target.provider,
            model=self._protocol.providers.baseline_target.model,
        )
        run, _result = LLMExecutionService(
            LedgerGatedExecutionProvider(gate, target_adapter, "baseline")
        ).execute(
            self._db,
            None,
            apparatus.message,
            None,
            self._target_parameters(),
            "baseline",
        )
        assert_baseline_prompt(apparatus.original_task, run.optimized_prompt)
        assert_baseline_has_no_treatment_artifacts(
            prompt_version_id=(
                str(run.prompt_version_id) if run.prompt_version_id is not None else None
            ),
            analysis_ids=[],
            answer_ids=[],
            memory_ids=[],
            document_ids=[],
            context_source_ids=[],
        )
        evidence.stages.append(
            StageArtifact(
                name="target_baseline",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "model_run_id": str(run.id),
                    "provider": run.provider,
                    "model": run.model,
                    "latency_ms": run.latency_ms,
                },
            )
        )
        return {
            "condition": "baseline",
            "status": "completed",
            "model_run_id": str(run.id),
            "executed_prompt": run.optimized_prompt,
            "response_text": run.response_text,
            "provider": run.provider,
            "model": run.model,
            "generation_parameters": run.generation_parameters_json,
        }

    def _run_promptpilot(
        self,
        context: UnitExecutionContext,
        apparatus: _UnitApparatus,
        gate: LedgerGate,
        evidence: _UnitEvidence,
    ) -> dict[str, Any]:
        """Execute the treatment pipeline for one unit."""

        project = apparatus.project
        conversation = apparatus.conversation
        message = apparatus.message

        verify_fixture_before_target_execution(
            binding=self._binding,
            fixture_id=context.fixture_id,
            manifest=context.manifest,
            dataset=self._dataset,
            manifest_path=context.manifest_path,
            execution_mode=self._execution_mode,
        )

        # Analysis.
        analysis_adapter = self._adapter_factory.create_adapter(
            role="analysis",
            provider=self._protocol.providers.analysis.provider,
            model=self._protocol.providers.analysis.model,
        )
        analysis = analyze_hybrid(
            self._db,
            project.id,
            conversation.id,
            message,
            mode="hybrid",
            provider=LedgerGatedAnalysisProvider(gate, analysis_adapter),
            observer=None,
        )
        evidence.stages.append(
            StageArtifact(
                name="analysis",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "analysis_id": str(analysis.id),
                    "analysis_mode": analysis.analysis_mode,
                    "ai_succeeded": analysis.ai_succeeded,
                },
            )
        )
        if analysis.fallback_used:
            evidence.fallback_seen = True
            decision = self._stop_evaluator.evaluate_fallback(
                fallback_classification="provider_failed",
                fallback_admission=self._binding.fallback_admission,
            )
            if decision.should_stop:
                raise PartialExperimentUnit("analysis_fallback_rejected")

        # Clarification.
        question_adapter = self._adapter_factory.create_adapter(
            role="question_generation",
            provider=self._protocol.providers.question_generation.provider,
            model=self._protocol.providers.question_generation.model,
        )
        question_provider = LedgerGatedQuestionProvider(gate, question_adapter)
        session = create_question_session(self._db, analysis)
        latest_analysis = analysis
        presented = 0
        missing_answer = False
        answer_ids: list[str] = []
        memory_records: list[dict[str, Any]] = []
        question = (
            next_question(self._db, session, provider=question_provider, observer=None)
            if self._binding.question_cap
            else None
        )
        while question is not None and presented < self._binding.question_cap:
            presented += 1
            if question.source == "fallback":
                evidence.fallback_seen = True
                if self._binding.fallback_admission == "reject":
                    raise PartialExperimentUnit("question_fallback_rejected")
            gap = self._db.get(InformationGap, question.gap_id)
            if gap is None:
                raise UnitExecutionError(
                    "question_gap_missing", "Presented question has no information gap"
                )
            answer_fixture = context.manifest.answer_for_gap(
                GapMatchKey(dimension=gap.dimension, question_target=gap.question_target)
            )
            if answer_fixture is None:
                missing_answer = True
                evidence.questions.append(
                    QuestionArtifact(
                        question_id=str(question.id),
                        gap_id=str(gap.id),
                        question_text=question.text,
                        resolution="skip",
                        reason="no_matching_fixture_answer",
                        answer_existed=False,
                    )
                )
                if self._protocol.comparison_policy.unmatched_gap == "stop":
                    break
                if presented == self._binding.question_cap:
                    mark_question_skipped(self._db, session, question)
                    break
                question = skip_and_next_question(
                    self._db, session, question, provider=question_provider, observer=None
                )
                continue
            answer = answer_question(self._db, question, answer_fixture.content)
            memory = ProjectMemoryService().add_user_answer(
                self._db, project.id, question.text, answer.content
            )
            latest_analysis = reanalyze_after_answer(self._db, session, answer)
            answer_ids.append(str(answer.id))
            memory_records.append(
                {
                    "fixture_id": context.fixture_id,
                    "memory_id": str(memory.id),
                    "source_type": "user_answer",
                    "provenance": {
                        "question_id": str(question.id),
                        "answer_id": str(answer.id),
                    },
                }
            )
            evidence.questions.append(
                QuestionArtifact(
                    question_id=str(question.id),
                    gap_id=str(gap.id),
                    question_text=question.text,
                    resolution="answered",
                    answer_existed=True,
                )
            )
            if presented == self._binding.question_cap:
                break
            question = next_question(
                self._db, session, provider=question_provider, observer=None
            )

        if missing_answer and (
            self._protocol.comparison_policy.unmatched_gap == "stop"
            or self._protocol.comparison_policy.unanswered_question == "stop"
        ):
            raise PartialExperimentUnit("unmatched_gap_no_fixture_answer")
        if self._remaining_gaps(session):
            raise PartialExperimentUnit("question_cap_reached")
        evidence.stages.append(
            StageArtifact(
                name="clarification",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "question_session_id": str(session.id),
                    "questions_presented": presented,
                },
            )
        )

        # Project memory and frozen document context are treatment-only.
        inputs = generation_inputs(context.manifest, self._dataset, context.manifest_path)
        for fact in inputs.project_facts:
            item = ProjectMemoryService().add_user_answer(
                self._db, project.id, fact.provenance.source_id, fact.content
            )
            memory_records.append(
                {
                    "fixture_id": fact.fixture_id,
                    "memory_id": str(item.id),
                    "source_type": fact.source_type,
                    "provenance": fact.provenance.model_dump(mode="json"),
                }
            )
        document_records: list[dict[str, Any]] = []
        chunk_ids: list[str] = []
        for frozen in inputs.frozen_documents:
            document = DocumentService().ingest_file(
                self._db,
                project.id,
                frozen.filename,
                frozen.media_type,
                frozen.content,
                provenance=f"fixture:{frozen.fixture_id}",
            )
            chunks = list(
                self._db.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_id == document.id)
                )
            )
            if document.status != "processed" or document.checksum != frozen.content_sha256:
                raise UnitExecutionError(
                    "frozen_document_processing_failed",
                    "Required frozen document processing failed",
                )
            document_records.append(
                {
                    "fixture_id": frozen.fixture_id,
                    "document_id": str(document.id),
                    "checksum": document.checksum,
                    "status": document.status,
                    "source_type": frozen.provenance.source_type,
                    "provenance": frozen.provenance.model_dump(mode="json"),
                }
            )
            chunk_ids.extend(str(chunk.id) for chunk in chunks)
        evidence.stages.append(
            StageArtifact(
                name="fixture_context",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "memory_facts": len(memory_records),
                    "frozen_documents": len(document_records),
                },
            )
        )

        # Context assembly.
        generation_input, package = build_generation_input(
            self._db,
            message,
            latest_analysis,
            self._protocol.generation_mode,
            instruction="",
        )
        evidence.stages.append(
            StageArtifact(
                name="context_assembly",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "selected_sources": len(package.sources),
                    "omitted_sources": len(package.omitted_items),
                    "used_budget": package.used_budget,
                },
            )
        )

        # Prompt generation.
        prompt_adapter = self._adapter_factory.create_adapter(
            role="prompt_generation",
            provider=self._protocol.providers.prompt_generation.provider,
            model=self._protocol.providers.prompt_generation.model,
        )
        outcome = PromptGenerator(
            LedgerGatedPromptProvider(gate, prompt_adapter)
        ).generate(generation_input)
        version = persist_generation(
            self._db,
            message,
            latest_analysis,
            outcome,
            message.content,
            self._protocol.generation_mode,
            package,
        )
        evidence.stages.append(
            StageArtifact(
                name="prompt_generation",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "prompt_version_id": str(version.id),
                    "generation_mode": version.generation_mode,
                    "provider": version.provider,
                    "model": version.model,
                },
            )
        )

        # Target execution with the optimized prompt.
        target_adapter = self._adapter_factory.create_adapter(
            role="target_execution",
            provider=self._protocol.providers.baseline_target.provider,
            model=self._protocol.providers.baseline_target.model,
        )
        run, _result = LLMExecutionService(
            LedgerGatedExecutionProvider(gate, target_adapter, "promptpilot")
        ).execute(
            self._db,
            version,
            message,
            None,
            self._target_parameters(),
            "promptpilot",
        )
        evidence.stages.append(
            StageArtifact(
                name="target_promptpilot",
                status="succeeded",
                timestamp=datetime.now(UTC),
                details={
                    "model_run_id": str(run.id),
                    "provider": run.provider,
                    "model": run.model,
                    "latency_ms": run.latency_ms,
                },
            )
        )
        treatment: dict[str, Any] = {
            "condition": "promptpilot",
            "status": "completed",
            "analysis_id": str(analysis.id),
            "analysis_mode": analysis.analysis_mode,
            "gap_ids": [str(gap.id) for gap in latest_analysis.gaps],
            "question_session_id": str(session.id),
            "answer_ids": answer_ids,
            "memory_records": memory_records,
            "document_records": document_records,
            "chunk_ids": chunk_ids,
            "latest_analysis_id": str(latest_analysis.id),
            "generation_input": generation_input.model_dump(mode="json"),
            "context_sources": package.sources,
            "context_omissions": package.omitted_items,
            "prompt_version_id": str(version.id),
            "optimized_prompt": version.optimized_prompt,
            "model_run_id": str(run.id),
            "response_text": run.response_text,
        }
        evidence.treatment = treatment
        return treatment

    def _evaluate_pair(
        self,
        context: UnitExecutionContext,
        apparatus: _UnitApparatus,
        gate: LedgerGate,
        condition_results: dict[str, dict[str, Any]],
    ) -> EvaluationArtifact:
        """Validate the paired runs and evaluate them under the frozen rubric."""

        baseline = condition_results["baseline"]
        promptpilot = condition_results["promptpilot"]
        baseline_run = self._db.get(ModelRun, UUID(str(baseline["model_run_id"])))
        promptpilot_run = self._db.get(
            ModelRun, UUID(str(promptpilot["model_run_id"]))
        )
        if baseline_run is None or promptpilot_run is None:
            raise UnitExecutionError("model_run_missing", "Condition model run is missing")
        if (baseline_run.provider, baseline_run.model) != (
            self._binding.target_provider,
            self._binding.target_model,
        ):
            raise UnitExecutionError(
                "target_provider_mismatch",
                "Baseline target provider or model differs from the frozen binding",
            )
        if (promptpilot_run.provider, promptpilot_run.model) != (
            self._binding.target_provider,
            self._binding.target_model,
        ):
            raise UnitExecutionError(
                "target_provider_mismatch",
                "PromptPilot target provider or model differs from the frozen binding",
            )
        if baseline_run.optimized_prompt != apparatus.message.content:
            raise UnitExecutionError(
                "baseline_prompt_contaminated",
                "Baseline did not execute the exact original task",
            )
        if (
            baseline_run.source_message_id != apparatus.message.id
            or promptpilot_run.source_message_id != apparatus.message.id
        ):
            raise UnitExecutionError(
                "source_message_mismatch",
                "Conditions did not execute the same source message",
            )
        expected_parameters = json.dumps(self._target_parameters(), sort_keys=True)
        if baseline_run.generation_parameters_json != expected_parameters:
            raise UnitExecutionError(
                "generation_parameter_mismatch",
                "Baseline generation parameters differ from the frozen parameters",
            )
        if promptpilot_run.generation_parameters_json != expected_parameters:
            raise UnitExecutionError(
                "generation_parameter_mismatch",
                "PromptPilot generation parameters differ from the frozen parameters",
            )
        if promptpilot_run.prompt_version_id is None:
            raise UnitExecutionError(
                "missing_optimized_prompt",
                "PromptPilot execution did not use an optimized prompt version",
            )

        judge_provider = None
        if self._binding.evaluation_primary == "llm_judge":
            judge_assignment = self._protocol.providers.judge
            if judge_assignment is None:
                raise UnitExecutionError(
                    "judge_not_assigned",
                    "LLM-judge evaluation requires a judge provider assignment",
                )
            judge_adapter = self._adapter_factory.create_adapter(
                role="judge",
                provider=judge_assignment.provider,
                model=judge_assignment.model,
            )
            judge_provider = LedgerGatedJudgeProvider(gate, judge_adapter)
        task = apparatus.task
        evaluation = ResponseEvaluationService(judge_provider=judge_provider).evaluate_pair(
            self._db,
            apparatus.conversation.id,
            baseline_run.id,
            promptpilot_run.id,
            task.task_text,
            self._binding.evaluation_primary,
            original_task=task.task_text,
            requirements=[
                *task.requirements,
                *(item.content for item in context.manifest.evaluation_only),
            ],
            constraints=list(task.constraints),
            context=[
                *task.available_context,
                *([task.reference] if task.reference else []),
            ],
        )
        dimension_scores: dict[str, dict[str, float | None]] = {}
        for label in ("baseline", "promptpilot"):
            dimension_scores[label] = {
                item.dimension: float(item.score)
                for item in evaluation.items
                if item.response_label == label
            }
        return EvaluationArtifact(
            evaluation_id=str(evaluation.id),
            method=evaluation.method,
            rubric_version=evaluation.rubric_version,
            baseline_score=evaluation.baseline_score,
            promptpilot_score=evaluation.promptpilot_score,
            overall_delta=evaluation.overall_delta,
            winner=evaluation.winner,
            dimension_scores=dimension_scores,
            neutral_labels=True,
        )

    def _remaining_gaps(self, session: QuestionSession) -> bool:
        resolved_gap_ids = select(Question.gap_id).where(
            Question.session_id == session.id,
            Question.status.in_(("answered", "skipped", "dismissed", "obsolete")),
        )
        return (
            self._db.scalar(
                select(InformationGap.id)
                .where(
                    InformationGap.analysis_id
                    == (session.latest_analysis_id or session.analysis_id),
                    InformationGap.status.in_(("unresolved", "partially_resolved")),
                    InformationGap.id.not_in(resolved_gap_ids),
                )
                .limit(1)
            )
            is not None
        )

    def _target_parameters(self) -> dict[str, Any]:
        parameters = self._binding.target_parameters
        return {
            "temperature": parameters.temperature,
            "max_tokens": parameters.max_tokens,
            "top_p": parameters.top_p,
            "seed": parameters.seed,
            "stop": list(parameters.stop),
            "presence_penalty": parameters.presence_penalty,
            "frequency_penalty": parameters.frequency_penalty,
        }

    def _budget_state(self) -> dict[str, Any]:
        run = self._db.get(BenchmarkExperimentRun, self._run_id)
        if run is None:
            return {"run_id": str(self._run_id), "status": "not_found"}
        return BenchmarkCallLedger.budget_snapshot(self._db, self._run_id).model_dump(
            mode="json"
        )

    def _failed_unit(
        self,
        *,
        context: UnitExecutionContext,
        gate: LedgerGate,
        evidence: _UnitEvidence,
        condition_results: dict[str, dict[str, Any]],
        error: BaseException,
    ) -> ExperimentUnit:
        reason = (
            str(error)
            if isinstance(error, (UnitExecutionError, PartialExperimentUnit))
            else type(error).__name__
        )
        return self._unit_record(
            context=context,
            gate=gate,
            evidence=evidence,
            disposition="failed_unit",
            condition_results=condition_results,
            failure_reason=reason,
        )

    def _unit_record(
        self,
        *,
        context: UnitExecutionContext,
        gate: LedgerGate,
        evidence: _UnitEvidence,
        disposition: UnitDisposition,
        condition_results: dict[str, dict[str, Any]],
        failure_reason: str | None = None,
        evaluation: EvaluationArtifact | None = None,
    ) -> ExperimentUnit:
        treatment = evidence.treatment
        provenance = ProvenanceArtifacts()
        if treatment is not None:
            model_run_ids: list[str] = []
            for condition in ("baseline", "promptpilot"):
                result = condition_results.get(condition)
                if result is not None:
                    model_run_ids.append(result["model_run_id"])
            provenance = ProvenanceArtifacts(
                analysis_ids=tuple([treatment["analysis_id"]]),
                gap_ids=tuple(treatment["gap_ids"]),
                question_ids=tuple(
                    question.question_id for question in evidence.questions
                ),
                answer_ids=tuple(treatment["answer_ids"]),
                memory_ids=tuple(
                    record["memory_id"] for record in treatment["memory_records"]
                ),
                document_ids=tuple(
                    record["document_id"] for record in treatment["document_records"]
                ),
                chunk_ids=tuple(treatment["chunk_ids"]),
                selected_context_ids=tuple(
                    source["identifier"] for source in treatment["context_sources"]
                ),
                omitted_context_ids=tuple(
                    item["identifier"] for item in treatment["context_omissions"]
                ),
                prompt_version_id=treatment["prompt_version_id"],
                model_run_ids=tuple(model_run_ids),
                evaluation_id=(
                    evaluation.evaluation_id if evaluation is not None else None
                ),
            )
        return ExperimentUnit(
            execution_mode=self._execution_mode,
            unit_id=context.unit_id,
            task_id=context.task_id,
            task_category=context.task_category,
            repetition=context.repetition,
            fixture_id=context.fixture_id,
            fixture_manifest_sha256=manifest_sha256(context.manifest),
            dataset_name=self._binding.dataset_name,
            dataset_sha256=self._binding.dataset_sha256,
            protocol_id=self._binding.protocol_id,
            protocol_sha256=self._binding.protocol_sha256,
            repository_sha=repository_sha(),
            disposition=disposition,
            condition_order=context.condition_order,
            fallback_state="fallback_seen" if evidence.fallback_seen else "none",
            failure_reason=failure_reason,
            budget_state=self._budget_state(),
            stages=tuple(evidence.stages),
            questions=tuple(evidence.questions),
            provenance=provenance,
            provider_observations=tuple(gate.provider_observations()),
            evaluation=evaluation,
            created_at=datetime.now(UTC),
        )


def run_production_pipeline_unit(
    *,
    db: Session,
    run_id: UUID,
    binding: ProtocolBinding,
    protocol: LiveStudyProtocol,
    dataset: BenchmarkDataset,
    fixture_manifests: list[tuple[FixtureManifest, Path]],
    adapter_factory: ProviderAdapterFactory,
    launch_gate_report: Any = None,
    execution_mode: ExecutionMode = "offline_dry_run",
    fixture_id: str,
    task_id: str,
    repetition: int,
    manifest: FixtureManifest,
    manifest_path: Path,
) -> ExperimentUnit:
    """Execute one guarded production pipeline unit against a staged run."""

    runner = LiveExperimentRunner(
        db=db,
        run_id=run_id,
        binding=binding,
        protocol=protocol,
        dataset=dataset,
        fixture_manifests=fixture_manifests,
        adapter_factory=adapter_factory,
        launch_gate_report=launch_gate_report,
        execution_mode=execution_mode,
    )
    return runner.run_production_pipeline_unit(
        fixture_id=fixture_id,
        task_id=task_id,
        repetition=repetition,
        manifest=manifest,
        manifest_path=manifest_path,
    )
