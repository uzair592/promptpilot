"""Dataset loading and paired benchmark execution for research experiments."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .evaluation_service import RUBRIC_VERSION, ResponseEvaluationService
from .execution_service import LLMExecutionService
from .llm_provider import ProviderUnavailable
from .models import Conversation, Message, ModelRun, Project, PromptVersion

BENCHMARK_SCHEMA_VERSION = "v1"


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
    schema_version: str = BENCHMARK_SCHEMA_VERSION
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


class BenchmarkRunRecord(BaseModel):
    schema_version: str = BENCHMARK_SCHEMA_VERSION
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
    provider: str | None = None
    model: str | None = None
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    evaluation_method: str | None = None
    rubric_version: str = RUBRIC_VERSION
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def load_dataset(path: str | Path) -> BenchmarkDataset:
    """Load and validate a JSON dataset before any model calls are made."""

    dataset_path = Path(path)
    with dataset_path.open(encoding="utf-8") as handle:
        return BenchmarkDataset.model_validate(json.load(handle))


def export_records_json(records: Iterable[BenchmarkRunRecord], path: str | Path) -> None:
    output = [record.model_dump(mode="json") for record in records]
    Path(path).write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def export_records_csv(records: Iterable[BenchmarkRunRecord], path: str | Path) -> None:
    rows = [record.model_dump(mode="json") for record in records]
    fieldnames = [
        "schema_version",
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
        "provider",
        "model",
        "model_parameters",
        "evaluation_method",
        "rubric_version",
        "error",
        "created_at",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row["assembled_context"] = json.dumps(row["assembled_context"])
            row["model_parameters"] = json.dumps(row["model_parameters"], sort_keys=True)
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
    ) -> None:
        self.execution_service = execution_service
        self.evaluation_service = evaluation_service or ResponseEvaluationService()
        self.prompt_builder = prompt_builder

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
        records: list[BenchmarkRunRecord] = []
        run_order = 0
        for task in dataset.tasks:
            for repetition in range(1, repetitions + 1):
                run_order += 1
                records.append(
                    self._run_task(
                        db,
                        task,
                        owner_id,
                        repetition,
                        run_order,
                        parameters or {},
                        evaluation_method,
                    )
                )
        return records

    def _run_task(
        self,
        db: Session,
        task: BenchmarkTask,
        owner_id: UUID,
        repetition: int,
        run_order: int,
        parameters: dict[str, Any],
        evaluation_method: str,
    ) -> BenchmarkRunRecord:
        project = Project(owner_id=owner_id, name=f"Benchmark {task.task_id} r{repetition}")
        db.add(project)
        db.flush()
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
                }
            ),
        )
        db.add(version)
        db.commit()
        db.refresh(message)
        db.refresh(version)

        baseline_id: UUID | None = None
        promptpilot_id: UUID | None = None
        error: str | None = None
        try:
            baseline, _ = self.execution_service.execute(
                db, None, message, None, parameters, "baseline"
            )
            baseline_id = baseline.id
            promptpilot, _ = self.execution_service.execute(
                db, version, message, None, parameters, "promptpilot"
            )
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
                provider=baseline.provider,
                model=baseline.model,
                model_parameters=parameters,
                evaluation_method=evaluation_method,
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
            return BenchmarkRunRecord(
                benchmark_task_id=task.task_id,
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
                provider=self.execution_service.provider.name,
                model=self.execution_service.provider.model,
                model_parameters=parameters,
                evaluation_method=evaluation_method,
                error=error,
            )
