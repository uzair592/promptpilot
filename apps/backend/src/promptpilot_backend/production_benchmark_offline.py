"""Offline-only production-service benchmark orchestration and evidence export."""

from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer_v2 import AnalysisProvider, analyze_hybrid
from .benchmark import BenchmarkDataset, dataset_sha256, repository_sha
from .benchmark_fixtures import (
    FixtureManifest,
    GapMatchKey,
    generation_inputs,
    load_fixture_manifest,
    manifest_sha256,
)
from .config import get_settings
from .conversation_service import add_message, create_conversation
from .document_service import DocumentService
from .evaluation_service import JudgeProvider, ResponseEvaluationService, evaluation_metadata
from .execution_service import ExecutionProvider, LLMExecutionService
from .llm_provider import OpenAICompatibleProvider
from .memory_service import ProjectMemoryService
from .models import (
    DocumentChunk,
    InformationGap,
    ModelRun,
    PromptAnalysis,
    Question,
    QuestionSession,
    User,
)
from .project_policy import ProjectRole, require_project_access
from .project_service import create_project
from .prompt_generation import (
    PromptGenerator,
    PromptProvider,
    build_generation_input,
    persist_generation,
)
from .provider_observation import (
    ProviderCallObservation,
    ProviderObserver,
    Purpose,
    safe_provider_label,
    sanitized_request_hash,
)
from .question_generator import QuestionProvider
from .question_service import (
    answer_question,
    create_question_session,
    mark_question_skipped,
    next_question,
    reanalyze_after_answer,
    skip_and_next_question,
)
from .schemas import ConversationCreateRequest, MessageCreateRequest, ProjectCreateRequest

EXPERIMENT_SCOPE = "production_pipeline_paired_v1"
EXECUTION_MODE = "offline_fixture"
STAGES = (
    "fixture_admission",
    "project_state",
    "fixture_context",
    "analysis",
    "clarification",
    "context_assembly",
    "prompt_generation",
    "target_baseline",
    "target_promptpilot",
    "pair_validation",
    "evaluation",
)
T = TypeVar("T")


class OfflinePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_cap: int = Field(ge=0, le=50)
    unmatched_gap: Literal["stop", "skip"]
    unanswered_question: Literal["stop", "skip"] = "skip"
    fallback: Literal["reject", "allow"]
    generation_mode: Literal["structured", "minimal", "detailed"]
    evaluation_method: Literal["heuristic", "llm_judge"]
    model_parameters: dict[str, float | int | str | bool]

    @field_validator("model_parameters")
    @classmethod
    def reject_credentials(
        cls, value: dict[str, float | int | str | bool]
    ) -> dict[str, float | int | str | bool]:
        forbidden = {
            "authorization",
            "api_key",
            "secret",
            "password",
            "access_token",
            "refresh_token",
        }
        if any(key.casefold().replace("-", "_") in forbidden for key in value):
            raise ValueError("Model parameters cannot contain credential fields")
        return value


@dataclass(frozen=True)
class OfflineProviders:
    analysis: AnalysisProvider
    question: QuestionProvider
    prompt: PromptProvider
    target: ExecutionProvider
    judge: JudgeProvider | None = None

    def require_offline(self, method: str) -> None:
        required: list[object] = [self.analysis, self.question, self.prompt, self.target]
        if method == "llm_judge":
            if self.judge is None:
                raise ValueError("Offline LLM judging requires an injected judge provider")
            required.append(self.judge)
        for provider in required:
            if (
                isinstance(provider, OpenAICompatibleProvider)
                or getattr(provider, "offline_fixture", None) is not True
            ):
                raise ValueError("Every provider must be explicitly marked offline_fixture=True")


class StageRecord(BaseModel):
    name: str
    status: Literal["not_started", "attempted", "succeeded", "fallback", "skipped", "failed"]
    timestamp: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class UnitRecord(BaseModel):
    experiment_scope: Literal["production_pipeline_paired_v1"] = "production_pipeline_paired_v1"
    execution_mode: Literal["offline_fixture"] = "offline_fixture"
    task_id: str
    repetition: int
    fixture_id: str
    fixture_sha256: str
    dataset_name: str
    dataset_sha256: str
    repository_sha: str | None
    policy: dict[str, Any]
    status: Literal["partial", "failed", "complete"] = "partial"
    complete_pair: bool = False
    reason: str | None = None
    condition_order: list[str] = Field(default_factory=list)
    stage_ledger: list[StageRecord] = Field(default_factory=list)
    provider_observations: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class ObservationGap(RuntimeError):
    pass


class PartialUnit(RuntimeError):
    pass


def _safe_failure(error: BaseException) -> str:
    """Use exception type only; provider exceptions may contain credentials."""

    return type(error).__name__


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)authorization\s*[:=][^\r\n]*", "[REDACTED HEADER]", value)
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value


class CheckpointStore:
    """A new directory, exclusive files, and append-only per-unit snapshots."""

    def __init__(self, output_dir: Path, secrets: Sequence[str]) -> None:
        if not output_dir.parent.is_dir() or output_dir.exists():
            raise ValueError("Output directory must have an existing parent and not already exist")
        output_dir.mkdir()
        self.output_dir = output_dir
        self.secrets = secrets
        self.sequences: dict[tuple[str, int], int] = {}
        with (output_dir / ".write-probe").open("x", encoding="utf-8") as handle:
            handle.write("probe")
            handle.flush()
            os.fsync(handle.fileno())
        (output_dir / ".write-probe").unlink()

    def _write(self, path: Path, value: Any) -> None:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(_redact(value, self.secrets), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def checkpoint(self, record: UnitRecord) -> None:
        key = (record.task_id, record.repetition)
        sequence = self.sequences.get(key, 0) + 1
        self.sequences[key] = sequence
        filename = f"{record.task_id}-r{record.repetition}-{sequence:03d}.json"
        self._write(self.output_dir / filename, record.model_dump(mode="json"))

    def finalize(self, records: list[UnitRecord]) -> None:
        rows = [_redact(record.model_dump(mode="json"), self.secrets) for record in records]
        self._write(self.output_dir / "results.json", rows)
        with (self.output_dir / "results.csv").open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "experiment_scope",
                    "execution_mode",
                    "task_id",
                    "repetition",
                    "status",
                    "complete_pair",
                    "reason",
                    "fixture_id",
                    "fixture_sha256",
                    "dataset_name",
                    "dataset_sha256",
                    "repository_sha",
                    "condition_order",
                    "policy",
                    "stage_ledger",
                    "provider_observations",
                    "artifacts",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: json.dumps(row[key], sort_keys=True)
                        if isinstance(row[key], (dict, list))
                        else row.get(key)
                        for key in writer.fieldnames or []
                    }
                )
            handle.flush()
            os.fsync(handle.fileno())


class ObservationRecorder:
    def __init__(self, sink: ProviderObserver | None = None) -> None:
        self.events: list[ProviderCallObservation] = []
        self.sink = sink

    def observe(self, event: ProviderCallObservation) -> None:
        try:
            if self.sink is not None:
                self.sink(event)
            self.events.append(event)
        except Exception:
            # Services and wrappers remain functional; completeness checks reject the evidence.
            pass

    def require_one(self, previous_count: int, purpose: Purpose) -> None:
        if len(self.events) != previous_count + 1 or self.events[-1].purpose != purpose:
            raise ObservationGap(f"Missing {purpose} provider observation")

    def call(self, purpose: Purpose, provider: Any, material: Any, operation: Callable[[], T]) -> T:
        provider_name = safe_provider_label(provider.name)
        model_name = safe_provider_label(provider.model)
        request_hash = sanitized_request_hash(purpose, model_name, material)
        started_at = datetime.now(UTC)
        start = perf_counter()
        try:
            result = operation()
        except Exception as error:
            self.observe(
                ProviderCallObservation(
                    purpose=purpose,
                    provider=provider_name,
                    model=model_name,
                    request_hash=request_hash,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    latency_ms=round((perf_counter() - start) * 1000),
                    request_outcome="failed",
                    service_result="error",
                    error_type=type(error).__name__,
                )
            )
            raise
        self.observe(
            ProviderCallObservation(
                purpose=purpose,
                provider=provider_name,
                model=model_name,
                request_hash=request_hash,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                latency_ms=round((perf_counter() - start) * 1000),
                request_outcome="succeeded",
                service_result="succeeded",
            )
        )
        return result


class ObservedProvider:
    def __init__(self, delegate: Any, recorder: ObservationRecorder, purpose: Purpose) -> None:
        self.delegate = delegate
        self.recorder = recorder
        self.purpose = purpose
        self.name = delegate.name
        self.model = delegate.model

    def generate_prompt(self, payload: dict[str, Any]) -> Any:
        return self.recorder.call(
            self.purpose, self.delegate, payload, lambda: self.delegate.generate_prompt(payload)
        )

    def generate_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.recorder.call(
                self.purpose,
                self.delegate,
                payload,
                lambda: self.delegate.generate_response(payload),
            ),
        )

    def judge_response(
        self, task: str, response_a: str, response_b: str, evidence: dict[str, Any] | None = None
    ) -> Any:
        return self.recorder.call(
            self.purpose,
            self.delegate,
            {
                "task": task,
                "response_a": response_a,
                "response_b": response_b,
                "evidence": evidence,
            },
            lambda: self.delegate.judge_response(task, response_a, response_b, evidence=evidence),
        )


class OfflinePipelineBenchmark:
    def __init__(
        self, providers: OfflineProviders, observer_sink: ProviderObserver | None = None
    ) -> None:
        self.providers = providers
        self.observer_sink = observer_sink

    @staticmethod
    def _stage(record: UnitRecord, name: str) -> StageRecord:
        return next(stage for stage in record.stage_ledger if stage.name == name)

    def _mark(
        self,
        store: CheckpointStore,
        record: UnitRecord,
        name: str,
        status: Literal["attempted", "succeeded", "fallback", "skipped", "failed"],
        details: dict[str, Any] | None = None,
    ) -> None:
        stage = self._stage(record, name)
        stage.status = status
        stage.timestamp = datetime.now(UTC)
        if details is not None:
            stage.details = details
        store.checkpoint(record)

    @staticmethod
    def _remaining_gaps(db: Session, session: QuestionSession) -> bool:
        resolved = select(Question.gap_id).where(
            Question.session_id == session.id,
            Question.status.in_(("answered", "skipped", "dismissed", "obsolete")),
        )
        return (
            db.scalar(
                select(InformationGap.id)
                .where(
                    InformationGap.analysis_id
                    == (session.latest_analysis_id or session.analysis_id),
                    InformationGap.status.in_(("unresolved", "partially_resolved")),
                    InformationGap.id.not_in(resolved),
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _unresolved_gap_details(db: Session, session: QuestionSession) -> list[dict[str, Any]]:
        """Return explicit unresolved records for gaps left open at the question cap."""

        resolved = select(Question.gap_id).where(
            Question.session_id == session.id,
            Question.status.in_(("answered", "skipped", "dismissed", "obsolete")),
        )
        gaps = db.scalars(
            select(InformationGap)
            .where(
                InformationGap.analysis_id
                == (session.latest_analysis_id or session.analysis_id),
                InformationGap.status.in_(("unresolved", "partially_resolved")),
                InformationGap.id.not_in(resolved),
            )
            .order_by(InformationGap.importance, InformationGap.dimension, InformationGap.id)
        ).all()
        return [
            {
                "gap_id": str(gap.id),
                "dimension": gap.dimension,
                "question_target": gap.question_target,
                "gap_status": gap.status,
                "resolution": "unanswered",
            }
            for gap in gaps
        ]

    def _next(
        self,
        db: Session,
        session: QuestionSession,
        recorder: ObservationRecorder,
        record: UnitRecord,
        skip: Question | None = None,
    ) -> Question | None:
        before = len(recorder.events)
        if skip is None:
            item = next_question(
                db, session, provider=self.providers.question, observer=recorder.observe
            )
        else:
            item = skip_and_next_question(
                db, session, skip, provider=self.providers.question, observer=recorder.observe
            )
        record.provider_observations = [asdict(event) for event in recorder.events]
        if item is not None:
            record.artifacts.setdefault("questions", []).append(
                {
                    "question_id": str(item.id),
                    "gap_id": str(item.gap_id),
                    "text": item.text,
                    "source": item.source,
                    "status": item.status,
                }
            )
            recorder.require_one(before, "question")
        elif len(recorder.events) != before:
            raise ObservationGap("Unexpected question observation without a question")
        return item

    def run(
        self,
        db: Session,
        dataset: BenchmarkDataset,
        manifest_paths: Sequence[Path],
        owner_id: UUID,
        repetitions: int,
        policy: OfflinePolicy,
        output_dir: Path,
    ) -> list[UnitRecord]:
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        policy = OfflinePolicy.model_validate(policy.model_dump(mode="json"))
        self.providers.require_offline(policy.evaluation_method)
        owner = db.get(User, owner_id)
        if owner is None or owner.status != "active":
            raise ValueError("Offline owner must be an active user")
        fixtures: list[tuple[FixtureManifest, Path]] = []
        seen_tasks: set[str] = set()
        for path in manifest_paths:
            manifest = load_fixture_manifest(path, dataset)
            generation_inputs(manifest, dataset, path)
            if manifest.task_id in seen_tasks:
                raise ValueError("Only one manifest per task is allowed")
            seen_tasks.add(manifest.task_id)
            fixtures.append((manifest, path))
        if not fixtures:
            raise ValueError("At least one fixture is required")
        secrets = [get_settings().llm_api_key]
        secrets.extend(
            str(getattr(provider, "api_key", ""))
            for provider in (
                self.providers.analysis,
                self.providers.question,
                self.providers.prompt,
                self.providers.target,
                self.providers.judge,
            )
            if provider is not None
        )
        store = CheckpointStore(output_dir, secrets)
        records: list[UnitRecord] = []
        for manifest, path in fixtures:
            for repetition in range(1, repetitions + 1):
                record = UnitRecord(
                    task_id=manifest.task_id,
                    repetition=repetition,
                    fixture_id=manifest.fixture_id,
                    fixture_sha256=manifest_sha256(manifest),
                    dataset_name=dataset.name,
                    dataset_sha256=dataset_sha256(dataset),
                    repository_sha=repository_sha(),
                    policy=policy.model_dump(mode="json"),
                    stage_ledger=[StageRecord(name=name, status="not_started") for name in STAGES],
                )
                store.checkpoint(record)
                self._run_unit(db, dataset, manifest, path, owner, policy, store, record)
                store.checkpoint(record)
                records.append(record)
        store.finalize(records)
        return records

    def _run_unit(
        self,
        db: Session,
        dataset: BenchmarkDataset,
        manifest: FixtureManifest,
        manifest_path: Path,
        owner: User,
        policy: OfflinePolicy,
        store: CheckpointStore,
        record: UnitRecord,
    ) -> None:
        recorder = ObservationRecorder(self.observer_sink)
        current = "fixture_admission"
        try:
            self._mark(store, record, current, "attempted")
            inputs = generation_inputs(manifest, dataset, manifest_path)
            self._mark(
                store,
                record,
                current,
                "succeeded",
                {
                    "fixture_kind": manifest.fixture_kind,
                    "review_status": manifest.review.status,
                    "live_eligible_claim": manifest.live_eligible,
                    "admission": EXECUTION_MODE,
                },
            )

            current = "project_state"
            self._mark(store, record, current, "attempted")
            project = create_project(
                db,
                owner,
                ProjectCreateRequest(
                    name=f"Offline benchmark {record.task_id} r{record.repetition}"
                ),
            )
            require_project_access(db, project.id, owner.id, ProjectRole.OWNER)
            conversation = create_conversation(
                db, project, ConversationCreateRequest(title="Offline benchmark")
            )
            message = add_message(
                db,
                conversation,
                MessageCreateRequest(role="user", content=inputs.original_task.content),
                idempotency_key=None,
            )
            record.artifacts.update(
                {
                    "project_id": str(project.id),
                    "owner_id": str(owner.id),
                    "conversation_id": str(conversation.id),
                    "source_message_id": str(message.id),
                    "original_task": message.content,
                }
            )
            self._mark(store, record, current, "succeeded")

            current = "fixture_context"
            self._mark(store, record, current, "attempted")
            memory_ids = []
            for fact in inputs.project_facts:
                item = ProjectMemoryService().add_user_answer(
                    db, project.id, fact.provenance.source_id, fact.content
                )
                memory_ids.append(
                    {
                        "fixture_id": fact.fixture_id,
                        "memory_id": str(item.id),
                        "source_type": fact.source_type,
                        "provenance": fact.provenance.model_dump(mode="json"),
                    }
                )
            record.artifacts["memory"] = memory_ids
            documents = []
            for frozen in inputs.frozen_documents:
                document = DocumentService().ingest_file(
                    db,
                    project.id,
                    frozen.filename,
                    frozen.media_type,
                    frozen.content,
                    provenance=f"fixture:{frozen.fixture_id}",
                )
                chunks = db.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_id == document.id)
                ).all()
                documents.append(
                    {
                        "fixture_id": frozen.fixture_id,
                        "document_id": str(document.id),
                        "checksum": document.checksum,
                        "status": document.status,
                        "source_type": frozen.provenance.source_type,
                        "provenance": frozen.provenance.model_dump(mode="json"),
                        "chunk_ids": [str(chunk.id) for chunk in chunks],
                        "chunk_provenance": [chunk.provenance for chunk in chunks],
                    }
                )
                record.artifacts["documents"] = documents
                if document.status != "processed" or document.checksum != frozen.content_sha256:
                    raise ValueError("Required frozen document processing failed")
            record.artifacts["memory"] = memory_ids
            record.artifacts["documents"] = documents
            self._mark(store, record, current, "succeeded")

            current = "analysis"
            self._mark(store, record, current, "attempted")
            before = len(recorder.events)
            analysis = analyze_hybrid(
                db,
                project.id,
                conversation.id,
                message,
                mode="hybrid",
                provider=self.providers.analysis,
                observer=recorder.observe,
            )
            record.provider_observations = [asdict(event) for event in recorder.events]
            record.artifacts.update(
                {
                    "initial_analysis_id": str(analysis.id),
                    "initial_analysis_mode": analysis.analysis_mode,
                    "analysis_ai_succeeded": analysis.ai_succeeded,
                    "analysis_fallback_used": analysis.fallback_used,
                    "initial_gap_ids": [str(gap.id) for gap in analysis.gaps],
                }
            )
            recorder.require_one(before, "analysis")
            session = create_question_session(db, analysis)
            record.artifacts["question_session_id"] = str(session.id)
            self._mark(
                store, record, current, "fallback" if analysis.fallback_used else "succeeded"
            )
            if analysis.fallback_used and policy.fallback == "reject":
                raise PartialUnit("analysis_fallback_rejected")

            current = "clarification"
            self._mark(store, record, current, "attempted")
            latest: PromptAnalysis = analysis
            presented = 0
            missing_answer = False
            fallback_seen = False
            question = self._next(db, session, recorder, record) if policy.question_cap else None
            while question is not None and presented < policy.question_cap:
                presented += 1
                fallback_seen = fallback_seen or question.source == "fallback"
                if question.source == "fallback" and policy.fallback == "reject":
                    self._mark(
                        store,
                        record,
                        current,
                        "fallback",
                        {"reason": "question_fallback_rejected", "question_id": str(question.id)},
                    )
                    raise PartialUnit("question_fallback_rejected")
                gap = db.get(InformationGap, question.gap_id)
                if gap is None:
                    raise ValueError("Presented question has no information gap")
                answer_fixture = manifest.answer_for_gap(
                    GapMatchKey(dimension=gap.dimension, question_target=gap.question_target)
                )
                if answer_fixture is None:
                    missing_answer = True
                    record.artifacts.setdefault("unmatched_gaps", []).append(
                        {
                            "gap_id": str(gap.id),
                            "question_id": str(question.id),
                            "dimension": gap.dimension,
                            "question_target": gap.question_target,
                        }
                    )
                    record.artifacts.setdefault("unanswered_questions", []).append(
                        {
                            "question_id": str(question.id),
                            "gap_id": str(gap.id),
                            "question_text": question.text,
                            "dimension": gap.dimension,
                            "resolution": policy.unanswered_question,
                            "reason": "no_matching_fixture_answer",
                        }
                    )
                    if policy.unmatched_gap == "stop":
                        break
                    if presented == policy.question_cap:
                        mark_question_skipped(db, session, question)
                        break
                    question = self._next(db, session, recorder, record, skip=question)
                    continue
                answer = answer_question(db, question, answer_fixture.content)
                memory = ProjectMemoryService().add_user_answer(
                    db, project.id, question.text, answer.content
                )
                latest = reanalyze_after_answer(db, session, answer)
                record.artifacts.setdefault("answers", []).append(
                    {
                        "fixture_id": answer_fixture.fixture_id,
                        "question_id": str(question.id),
                        "gap_id": str(gap.id),
                        "answer_id": str(answer.id),
                        "memory_id": str(memory.id),
                        "reanalysis_id": str(latest.id),
                        "reanalysis_mode": latest.analysis_mode,
                        "reanalysis_provider_call": False,
                    }
                )
                if presented == policy.question_cap:
                    break
                question = self._next(db, session, recorder, record)
            remaining = self._remaining_gaps(db, session)
            if not remaining and not missing_answer:
                before = len(recorder.events)
                final_question = next_question(
                    db, session, provider=self.providers.question, observer=recorder.observe
                )
                if final_question is not None or len(recorder.events) != before:
                    raise ObservationGap("Unexpected question after all gaps were resolved")
            record.artifacts.update(
                {
                    "latest_analysis_id": str(latest.id),
                    "latest_analysis_mode": latest.analysis_mode,
                    "question_count": presented,
                    "question_session_status": session.status,
                    "question_stop_reason": session.stop_reason,
                }
            )
            stage_status: Literal["succeeded", "fallback", "skipped"] = (
                "skipped"
                if missing_answer or remaining
                else "fallback"
                if fallback_seen
                else "succeeded"
            )
            if missing_answer or remaining:
                record.artifacts["unresolved_gaps"] = self._unresolved_gap_details(db, session)
            self._mark(store, record, current, stage_status)
            if missing_answer:
                raise PartialUnit("unmatched_gap_no_fixture_answer")
            if remaining:
                raise PartialUnit("question_cap_reached")

            current = "context_assembly"
            self._mark(store, record, current, "attempted")
            generation_input, package = build_generation_input(
                db, message, latest, policy.generation_mode, instruction=""
            )
            record.artifacts.update(
                {
                    "generation_input": generation_input.model_dump(mode="json"),
                    "context_sources": package.sources,
                    "context_omissions": package.omitted_items,
                    "context_budget": package.budget,
                    "context_used_budget": package.used_budget,
                }
            )
            self._mark(store, record, current, "succeeded")

            current = "prompt_generation"
            self._mark(store, record, current, "attempted")
            before = len(recorder.events)
            outcome = PromptGenerator(
                ObservedProvider(self.providers.prompt, recorder, "prompt_generation")
            ).generate(generation_input)
            record.provider_observations = [asdict(event) for event in recorder.events]
            record.artifacts["generated_prompt_before_persistence"] = (
                outcome.result.optimized_prompt
            )
            recorder.require_one(before, "prompt_generation")
            version = persist_generation(
                db, message, latest, outcome, message.content, policy.generation_mode, package
            )
            record.artifacts.update(
                {
                    "prompt_version_id": str(version.id),
                    "optimized_prompt": version.optimized_prompt,
                    "generation_mode": version.generation_mode,
                    "generation_provider": safe_provider_label(version.provider),
                    "generation_model": safe_provider_label(version.model),
                    "generation_fallback_used": version.fallback_used,
                    "incorporated_context": outcome.result.incorporated_context,
                    "generation_assumptions": outcome.result.assumptions,
                    "generation_warnings": outcome.result.warnings,
                }
            )
            self._mark(store, record, current, "succeeded")

            order = (
                ["baseline", "promptpilot"]
                if record.repetition % 2
                else ["promptpilot", "baseline"]
            )
            record.condition_order = order
            runs: dict[str, ModelRun] = {}
            for condition in order:
                current = f"target_{condition}"
                self._mark(store, record, current, "attempted")
                before = len(recorder.events)
                try:
                    run, _ = LLMExecutionService(
                        ObservedProvider(self.providers.target, recorder, cast(Purpose, current))
                    ).execute(
                        db,
                        version if condition == "promptpilot" else None,
                        message,
                        None,
                        dict(policy.model_parameters),
                        condition,
                    )
                except Exception:
                    failed_run = db.scalar(
                        select(ModelRun)
                        .where(
                            ModelRun.source_message_id == message.id,
                            ModelRun.execution_strategy == condition,
                        )
                        .order_by(ModelRun.created_at.desc())
                    )
                    if failed_run is not None:
                        record.artifacts[f"{condition}_run"] = {
                            "model_run_id": str(failed_run.id),
                            "status": failed_run.status,
                            "executed_prompt": failed_run.optimized_prompt,
                            "provider": safe_provider_label(failed_run.provider),
                            "model": safe_provider_label(failed_run.model),
                            "parameters": policy.model_parameters,
                        }
                    raise
                record.provider_observations = [asdict(event) for event in recorder.events]
                record.artifacts[f"{condition}_run"] = {
                    "model_run_id": str(run.id),
                    "status": run.status,
                    "source_message_id": str(run.source_message_id),
                    "prompt_version_id": str(run.prompt_version_id)
                    if run.prompt_version_id
                    else None,
                    "executed_prompt": run.optimized_prompt,
                    "raw_response": run.response_text,
                    "provider": safe_provider_label(run.provider),
                    "model": safe_provider_label(run.model),
                    "parameters": json.loads(run.generation_parameters_json),
                    "usage": json.loads(run.usage_json) if run.usage_json else {},
                    "finish_reason": run.finish_reason,
                    "latency_ms": run.latency_ms,
                    "created_at": run.created_at.isoformat(),
                }
                recorder.require_one(before, cast(Purpose, current))
                runs[condition] = run
                self._mark(store, record, current, "succeeded")
            current = "pair_validation"
            self._mark(store, record, current, "attempted")
            if (runs["baseline"].provider, runs["baseline"].model) != (
                runs["promptpilot"].provider,
                runs["promptpilot"].model,
            ) or (runs["baseline"].provider, runs["baseline"].model) != (
                self.providers.target.name,
                self.providers.target.model,
            ):
                raise ValueError("Target provider/model mismatch")
            if runs["baseline"].optimized_prompt != message.content:
                raise ValueError("Baseline did not execute the original source message")
            if runs["baseline"].source_message_id != runs["promptpilot"].source_message_id:
                raise ValueError("Target runs have different source messages")
            expected_parameters = json.dumps(policy.model_parameters, sort_keys=True)
            if any(run.generation_parameters_json != expected_parameters for run in runs.values()):
                raise ValueError("Target runs used different generation parameters")
            self._mark(store, record, current, "succeeded")

            current = "evaluation"
            self._mark(store, record, current, "attempted")
            before = len(recorder.events)
            judge_provider: Any = (
                ObservedProvider(self.providers.judge, recorder, "judge")
                if policy.evaluation_method == "llm_judge"
                else self.providers.target
            )
            task = dataset.task(record.task_id)
            evaluation = ResponseEvaluationService(judge_provider=judge_provider).evaluate_pair(
                db,
                conversation.id,
                runs["baseline"].id,
                runs["promptpilot"].id,
                task.task_text,
                policy.evaluation_method,
                original_task=task.task_text,
                requirements=[
                    *task.requirements,
                    *(item.content for item in manifest.evaluation_only),
                ],
                constraints=cast(list[dict[str, object] | str], list(task.constraints)),
                context=[*task.available_context, *([task.reference] if task.reference else [])],
            )
            record.provider_observations = [asdict(event) for event in recorder.events]
            record.artifacts["evaluation"] = {
                "evaluation_id": str(evaluation.id),
                "method": evaluation.method,
                "rubric_version": evaluation.rubric_version,
                "baseline_score": evaluation.baseline_score,
                "promptpilot_score": evaluation.promptpilot_score,
                "overall_delta": evaluation.overall_delta,
                "winner": evaluation.winner,
                "items": [
                    {
                        "id": str(item.id),
                        "response_label": item.response_label,
                        "dimension": item.dimension,
                        "score": item.score,
                        "explanation": item.explanation,
                    }
                    for item in evaluation.items
                ],
                "metadata": evaluation_metadata(evaluation),
            }
            if policy.evaluation_method == "llm_judge":
                recorder.require_one(before, "judge")
            elif len(recorder.events) != before:
                raise ObservationGap("Unexpected provider observation in heuristic evaluation")
            self._mark(store, record, current, "succeeded")
            record.status = "complete"
            record.complete_pair = True
        except PartialUnit as error:
            record.status = "partial"
            record.reason = str(error)
        except Exception as error:
            record.status = "failed"
            record.reason = _safe_failure(error)
            if self._stage(record, current).status == "attempted":
                self._mark(store, record, current, "failed", {"error_type": _safe_failure(error)})
            db.rollback()
        finally:
            record.provider_observations = [asdict(event) for event in recorder.events]
