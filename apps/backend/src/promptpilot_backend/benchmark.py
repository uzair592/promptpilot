"""Dataset loading and paired benchmark execution for research experiments."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .evaluation_service import RUBRIC_VERSION, ResponseEvaluationService
from .execution_service import LLMExecutionService
from .llm_provider import ProviderUnavailable
from .models import Conversation, Message, ModelRun, PromptVersion, User
from .project_service import create_project
from .schemas import ProjectCreateRequest

BENCHMARK_SCHEMA_VERSION: Literal["v1"] = "v1"
BENCHMARK_EXPERIMENT_SCOPE = "benchmark_infrastructure_smoke_test"


class BenchmarkTask(BaseModel):
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    task_text: str = Field(min_length=1, max_length=100000)
    objective: str = Field(min_length=1, max_length=10000)
    requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_output_characteristics: list[str] = Field(default_factory=list)
    available_context: list[str] = Field(default_factory=list)
    category: str = Field(min_length=1, max_length=80)
    difficulty: str = Field(min_length=1, max_length=30)
    reference: str | None = Field(default=None, max_length=30000)

    @field_validator("task_id")
    @classmethod
    def normalize_task_id(cls, value: str) -> str:
        return value.strip()


class BenchmarkDataset(BaseModel):
    schema_version: Literal["v1"] = BENCHMARK_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=160)
    tasks: list[BenchmarkTask] = Field(min_length=1)

    @field_validator("tasks")
    @classmethod
    def require_unique_task_ids(cls, value: list[BenchmarkTask]) -> list[BenchmarkTask]:
        ids = [task.task_id for task in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Benchmark task IDs must be unique")
        return value

    def task(self, task_id: str) -> BenchmarkTask:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise KeyError(f"Unknown benchmark task: {task_id}")


class BenchmarkAttemptRecord(BaseModel):
    experiment_scope: str = BENCHMARK_EXPERIMENT_SCOPE
    benchmark_task_id: str
    repetition: int
    condition: str
    project_id: UUID
    conversation_id: UUID
    source_message_id: UUID
    provider: str
    model: str
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    prompt_version_id: UUID | None = None
    model_run_id: UUID | None = None
    evaluation_id: UUID | None = None
    dataset_version: str
    dataset_sha256: str
    repository_sha: str | None
    code_revision: str
    request_hash: str
    execution_order: int
    status: str
    executed_prompt: str | None = None
    response_text: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    model_run_created_at: datetime | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BenchmarkRunRecord(BaseModel):
    schema_version: str = BENCHMARK_SCHEMA_VERSION
    experiment_scope: str = BENCHMARK_EXPERIMENT_SCOPE
    benchmark_task_id: str
    repetition: int = Field(ge=1)
    run_order: int = Field(ge=1)
    status: str
    project_id: UUID
    conversation_id: UUID
    source_message_id: UUID
    baseline_model_run_id: UUID | None = None
    promptpilot_model_run_id: UUID | None = None
    evaluation_id: UUID | None = None
    source_message: str
    original_task: str
    optimized_prompt: str | None = None
    assembled_context: list[str] = Field(default_factory=list)
    context_provenance: list[dict[str, Any]] = Field(default_factory=list)
    task_facts: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    dataset_version: str = BENCHMARK_SCHEMA_VERSION
    dataset_sha256: str
    repository_sha: str | None
    code_revision: str
    request_hash: str
    condition_order: list[str]
    attempts: list[BenchmarkAttemptRecord] = Field(default_factory=list)
    evaluation_method: str | None = None
    evaluation: dict[str, Any] | None = None
    rubric_version: str = RUBRIC_VERSION
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def load_dataset(path: str | Path) -> BenchmarkDataset:
    """Load and validate a JSON dataset before any model calls are made."""

    dataset_path = Path(path)
    with dataset_path.open(encoding="utf-8") as handle:
        return BenchmarkDataset.model_validate(json.load(handle))


def dataset_sha256(dataset: BenchmarkDataset) -> str:
    canonical = json.dumps(
        dataset.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def repository_sha() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
            )
            .strip()
            or None
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def request_hash(
    task: BenchmarkTask,
    condition: str,
    provider: str,
    model: str,
    parameters: dict[str, Any],
    optimized_prompt: str | None,
    context: list[str],
) -> str:
    material = {
        "task": task.model_dump(mode="json"),
        "condition": condition,
        "provider": provider,
        "model": model,
        "parameters": parameters,
        "optimized_prompt": optimized_prompt,
        "context": context,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def export_records_json(records: Iterable[BenchmarkRunRecord], path: str | Path) -> None:
    output = [record.model_dump(mode="json") for record in records]
    Path(path).write_text(_safe_export_json(output, indent=2) + "\n", encoding="utf-8")


def _safe_export_json(value: Any, **kwargs: Any) -> str:
    """Keep the configured credential out of provider-returned text and errors."""
    serialized = json.dumps(value, **kwargs)
    key = get_settings().llm_api_key
    if key:
        serialized = serialized.replace(key, "[REDACTED]")
        serialized = serialized.replace(json.dumps(key)[1:-1], "[REDACTED]")
    return serialized


def export_records_csv(records: Iterable[BenchmarkRunRecord], path: str | Path) -> None:
    rows = [record.model_dump(mode="json") for record in records]
    fieldnames = [
        "schema_version",
        "experiment_scope",
        "benchmark_task_id",
        "repetition",
        "run_order",
        "status",
        "project_id",
        "conversation_id",
        "source_message_id",
        "baseline_model_run_id",
        "promptpilot_model_run_id",
        "evaluation_id",
        "source_message",
        "original_task",
        "optimized_prompt",
        "assembled_context",
        "context_provenance",
        "task_facts",
        "provider",
        "model",
        "model_parameters",
        "dataset_version",
        "dataset_sha256",
        "repository_sha",
        "code_revision",
        "request_hash",
        "condition_order",
        "attempts",
        "evaluation_method",
        "evaluation",
        "rubric_version",
        "error",
        "created_at",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row["assembled_context"] = json.dumps(row["assembled_context"])
            row["context_provenance"] = json.dumps(row["context_provenance"])
            row["task_facts"] = json.dumps(row["task_facts"])
            row["model_parameters"] = json.dumps(row["model_parameters"], sort_keys=True)
            row["condition_order"] = json.dumps(row["condition_order"])
            row["attempts"] = json.dumps(row["attempts"], sort_keys=True)
            row["evaluation"] = json.dumps(row["evaluation"], sort_keys=True)
            key = get_settings().llm_api_key
            if key:
                escaped_key = json.dumps(key)[1:-1]
                row = {
                    field: value.replace(key, "[REDACTED]").replace(
                        escaped_key, "[REDACTED]"
                    )
                    if isinstance(value, str) else value
                    for field, value in row.items()
                }
            writer.writerow(row)


PromptBuilder = Callable[[BenchmarkTask], tuple[str, list[str]]]


def default_prompt_builder(task: BenchmarkTask) -> tuple[str, list[str]]:
    """Create a transparent optimized prompt from dataset facts only."""

    context = list(task.available_context)
    sections = [
        f"Objective: {task.objective}",
        f"Task: {task.task_text}",
        "Requirements:\n" + "\n".join(f"- {item}" for item in task.requirements),
        "Constraints:\n" + "\n".join(f"- {item}" for item in task.constraints),
        "Expected output:\n" + "\n".join(
            f"- {item}" for item in task.expected_output_characteristics
        ),
    ]
    if context:
        sections.append("Available context:\n" + "\n".join(f"- {item}" for item in context))
    return "\n\n".join(sections), context


class BenchmarkRunner:
    """Execute paired conditions with one isolated project/conversation per repetition."""

    def __init__(
        self,
        execution_service: LLMExecutionService,
        evaluation_service: ResponseEvaluationService | None = None,
        prompt_builder: PromptBuilder = default_prompt_builder,
        condition_order: Callable[[int], tuple[str, str]] | None = None,
        repository_revision: str | None = None,
    ) -> None:
        self.execution_service = execution_service
        self.evaluation_service = evaluation_service or ResponseEvaluationService()
        self.prompt_builder = prompt_builder
        self.condition_order = condition_order or (
            lambda repetition: ("promptpilot", "baseline")
            if (repetition + 1) % 2
            else ("baseline", "promptpilot")
        )
        self.repository_revision = (
            repository_revision if repository_revision is not None else repository_sha()
        )
        self.experiment_scope = (
            BENCHMARK_EXPERIMENT_SCOPE
            if prompt_builder is default_prompt_builder
            else "custom_prompt_builder"
        )

    @staticmethod
    def _context_provenance(task: BenchmarkTask) -> list[dict[str, Any]]:
        return [
            {"source": "dataset.available_context", "index": index, "text": text}
            for index, text in enumerate(task.available_context)
        ]

    @staticmethod
    def _evaluation_export(evaluation: Any) -> dict[str, Any]:
        return {
            "id": str(evaluation.id),
            "method": evaluation.method,
            "evaluator_provider": evaluation.evaluator_provider,
            "evaluator_model": evaluation.evaluator_model,
            "rubric_version": evaluation.rubric_version,
            "baseline_score": evaluation.baseline_score,
            "promptpilot_score": evaluation.promptpilot_score,
            "overall_delta": evaluation.overall_delta,
            "winner": evaluation.winner,
            "items": [
                {
                    "response_label": item.response_label,
                    "dimension": item.dimension,
                    "score": item.score,
                    "explanation": item.explanation,
                }
                for item in evaluation.items
            ],
            "metadata": json.loads(evaluation.metadata_json),
            "created_at": evaluation.created_at.isoformat(),
        }

    def run(
        self,
        db: Session,
        dataset: BenchmarkDataset,
        owner_id: UUID,
        *,
        repetitions: int = 1,
        parameters: dict[str, Any] | None = None,
        evaluation_method: str = "heuristic",
    ) -> list[BenchmarkRunRecord]:
        if repetitions < 1:
            raise ValueError("repetitions must be at least 1")
        owner = db.get(User, owner_id)
        if owner is None:
            raise ValueError("Benchmark owner does not exist")
        records: list[BenchmarkRunRecord] = []
        run_order = 0
        dataset_hash = dataset_sha256(dataset)
        for task in dataset.tasks:
            for repetition in range(1, repetitions + 1):
                run_order += 1
                records.append(
                    self._run_task(
                        db,
                        task,
                        owner,
                        repetition,
                        run_order,
                        parameters or {},
                        evaluation_method,
                        dataset.schema_version,
                        dataset_hash,
                    )
                )
        return records

    def _run_task(
        self,
        db: Session,
        task: BenchmarkTask,
        owner: User,
        repetition: int,
        run_order: int,
        parameters: dict[str, Any],
        evaluation_method: str,
        dataset_version: str,
        dataset_hash: str,
    ) -> BenchmarkRunRecord:
        project = create_project(
            db, owner, ProjectCreateRequest(name=f"Benchmark {task.task_id} r{repetition}")
        )
        conversation = Conversation(project_id=project.id, title=task.task_id)
        db.add(conversation)
        db.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content=task.task_text,
            sequence=1,
        )
        db.add(message)
        db.flush()
        optimized_prompt, context = self.prompt_builder(task)
        version = PromptVersion(
            project_id=project.id,
            conversation_id=conversation.id,
            source_message_id=message.id,
            version_number=1,
            original_prompt=task.task_text,
            optimized_prompt=optimized_prompt,
            generation_mode="benchmark",
            provider=self.execution_service.provider.name,
            model=self.execution_service.provider.model,
            metadata_json=json.dumps(
                {
                    "benchmark_task_id": task.task_id,
                    "context": context,
                    "schema_version": BENCHMARK_SCHEMA_VERSION,
                    "experiment_scope": self.experiment_scope,
                }
            ),
        )
        db.add(version)
        db.commit()
        db.refresh(message)
        db.refresh(version)

        baseline_id: UUID | None = None
        promptpilot_id: UUID | None = None
        condition_order = list(self.condition_order(repetition))
        if sorted(condition_order) != ["baseline", "promptpilot"]:
            raise ValueError("condition_order must contain baseline and promptpilot exactly once")
        attempts: list[BenchmarkAttemptRecord] = []
        error: str | None = None
        try:
            runs: dict[str, ModelRun] = {}
            for execution_order, condition in enumerate(condition_order, 1):
                run, _ = self.execution_service.execute(
                    db,
                    version if condition == "promptpilot" else None,
                    message,
                    None,
                    parameters,
                    condition,
                )
                runs[condition] = run
                attempts.append(
                    BenchmarkAttemptRecord(
                        benchmark_task_id=task.task_id,
                        experiment_scope=self.experiment_scope,
                        repetition=repetition,
                        condition=condition,
                        project_id=project.id,
                        conversation_id=conversation.id,
                        source_message_id=message.id,
                        provider=run.provider,
                        model=run.model,
                        generation_parameters=parameters,
                        prompt_version_id=version.id if condition == "promptpilot" else None,
                        model_run_id=run.id,
                        dataset_version=dataset_version,
                        dataset_sha256=dataset_hash,
                        repository_sha=self.repository_revision,
                        code_revision=self.repository_revision or "git-unavailable",
                        request_hash=request_hash(
                            task,
                            condition,
                            run.provider,
                            run.model,
                            parameters,
                            optimized_prompt if condition == "promptpilot" else None,
                            context if condition == "promptpilot" else [],
                        ),
                        execution_order=execution_order,
                        status=run.status,
                        executed_prompt=run.optimized_prompt,
                        response_text=run.response_text,
                        finish_reason=run.finish_reason,
                        usage=json.loads(run.usage_json),
                        latency_ms=run.latency_ms,
                        model_run_created_at=run.created_at,
                    )
                )
            baseline = runs["baseline"]
            promptpilot = runs["promptpilot"]
            baseline_id = baseline.id
            promptpilot_id = promptpilot.id
            evaluation = self.evaluation_service.evaluate_pair(
                db,
                conversation.id,
                baseline.id,
                promptpilot.id,
                task.task_text,
                evaluation_method,
                original_task=task.task_text,
                requirements=list(task.requirements),
                constraints=list(task.constraints),
                context=list(task.available_context),
            )
            return BenchmarkRunRecord(
                benchmark_task_id=task.task_id,
                experiment_scope=self.experiment_scope,
                repetition=repetition,
                run_order=run_order,
                status="succeeded",
                project_id=project.id,
                conversation_id=conversation.id,
                source_message_id=message.id,
                baseline_model_run_id=baseline.id,
                promptpilot_model_run_id=promptpilot.id,
                evaluation_id=evaluation.id,
                source_message=task.task_text,
                original_task=task.task_text,
                optimized_prompt=optimized_prompt,
                assembled_context=context,
                context_provenance=self._context_provenance(task),
                task_facts=task.model_dump(mode="json"),
                provider=baseline.provider,
                model=baseline.model,
                model_parameters=parameters,
                dataset_version=dataset_version,
                dataset_sha256=dataset_hash,
                repository_sha=self.repository_revision,
                code_revision=self.repository_revision or "git-unavailable",
                request_hash=request_hash(
                    task,
                    "pair",
                    baseline.provider,
                    baseline.model,
                    parameters,
                    optimized_prompt,
                    context,
                ),
                condition_order=condition_order,
                attempts=attempts,
                evaluation_method=evaluation_method,
                evaluation=self._evaluation_export(evaluation),
            )
        except (ProviderUnavailable, ValueError) as exc:
            error = str(exc)
            db.rollback()
            if baseline_id is None:
                baseline_run = db.scalars(
                    select(ModelRun)
                    .where(
                        ModelRun.source_message_id == message.id,
                        ModelRun.execution_strategy == "baseline",
                    )
                    .order_by(ModelRun.created_at.desc())
                ).first()
                baseline_id = baseline_run.id if baseline_run else None
            if promptpilot_id is None:
                promptpilot_run = db.scalars(
                    select(ModelRun)
                    .where(
                        ModelRun.source_message_id == message.id,
                        ModelRun.execution_strategy == "promptpilot",
                    )
                    .order_by(ModelRun.created_at.desc())
                ).first()
                promptpilot_id = promptpilot_run.id if promptpilot_run else None
            existing_runs = {
                "baseline": db.get(ModelRun, baseline_id) if baseline_id else None,
                "promptpilot": db.get(ModelRun, promptpilot_id) if promptpilot_id else None,
            }
            attempts = []
            for execution_order, condition in enumerate(condition_order, 1):
                existing_run = existing_runs[condition]
                if existing_run is None:
                    continue
                attempts.append(
                    BenchmarkAttemptRecord(
                        benchmark_task_id=task.task_id,
                        experiment_scope=self.experiment_scope,
                        repetition=repetition,
                        condition=condition,
                        project_id=project.id,
                        conversation_id=conversation.id,
                        source_message_id=message.id,
                        provider=existing_run.provider,
                        model=existing_run.model,
                        generation_parameters=parameters,
                        prompt_version_id=version.id if condition == "promptpilot" else None,
                        model_run_id=existing_run.id,
                        dataset_version=dataset_version,
                        dataset_sha256=dataset_hash,
                        repository_sha=self.repository_revision,
                        code_revision=self.repository_revision or "git-unavailable",
                        request_hash=request_hash(
                            task,
                            condition,
                            existing_run.provider,
                            existing_run.model,
                            parameters,
                            optimized_prompt if condition == "promptpilot" else None,
                            context if condition == "promptpilot" else [],
                        ),
                        execution_order=execution_order,
                        status=existing_run.status,
                        executed_prompt=existing_run.optimized_prompt,
                        response_text=existing_run.response_text,
                        finish_reason=existing_run.finish_reason,
                        usage=json.loads(existing_run.usage_json),
                        latency_ms=existing_run.latency_ms,
                        model_run_created_at=existing_run.created_at,
                        error=existing_run.error_message,
                    )
                )
            return BenchmarkRunRecord(
                benchmark_task_id=task.task_id,
                experiment_scope=self.experiment_scope,
                repetition=repetition,
                run_order=run_order,
                status="failed",
                project_id=project.id,
                conversation_id=conversation.id,
                source_message_id=message.id,
                baseline_model_run_id=baseline_id,
                promptpilot_model_run_id=promptpilot_id,
                source_message=task.task_text,
                original_task=task.task_text,
                optimized_prompt=optimized_prompt,
                assembled_context=context,
                context_provenance=self._context_provenance(task),
                task_facts=task.model_dump(mode="json"),
                provider=self.execution_service.provider.name,
                model=self.execution_service.provider.model,
                model_parameters=parameters,
                dataset_version=dataset_version,
                dataset_sha256=dataset_hash,
                repository_sha=self.repository_revision,
                code_revision=self.repository_revision or "git-unavailable",
                request_hash=request_hash(
                    task,
                    "pair",
                    self.execution_service.provider.name,
                    self.execution_service.provider.model,
                    parameters,
                    optimized_prompt,
                    context,
                ),
                condition_order=condition_order,
                attempts=attempts,
                evaluation_method=evaluation_method,
                error=error,
            )
