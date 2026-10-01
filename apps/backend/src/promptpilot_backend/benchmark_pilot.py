"""Fixed, preflighted eight-category benchmark pilot entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import UUID

from .benchmark import (
    BenchmarkDataset,
    BenchmarkRunner,
    export_records_csv,
    export_records_json,
    load_dataset,
)
from .config import get_settings
from .evaluation_service import ResponseEvaluationService
from .execution_service import LLMExecutionService
from .llm_provider import OpenAICompatibleProvider

PILOT_TASKS = (
    ("writing-email-001", "writing"),
    ("summarization-policy-001", "summarization"),
    ("qa-geography-001", "question_answering"),
    ("extraction-invoice-001", "extraction"),
    ("planning-launch-001", "planning"),
    ("technical-api-001", "technical_software"),
    ("business-analysis-001", "business_professional"),
    ("research-information-001", "research_information"),
)
PILOT_TASK_IDS = tuple(task_id for task_id, _ in PILOT_TASKS)


def select_pilot_tasks(dataset: BenchmarkDataset) -> BenchmarkDataset:
    tasks = []
    for task_id, category in PILOT_TASKS:
        task = dataset.task(task_id)
        if task.category != category:
            raise ValueError(f"Pilot task {task_id} has unexpected category")
        tasks.append(task)
    return dataset.model_copy(update={"tasks": tasks})


def require_live_config() -> UUID:
    settings = get_settings()
    if settings.llm_provider != "openrouter":
        raise ValueError("LLM_PROVIDER must be openrouter")
    if settings.llm_base_url.rstrip("/") != "https://openrouter.ai/api/v1":
        raise ValueError("LLM_BASE_URL must be https://openrouter.ai/api/v1")
    if not settings.llm_model or not settings.llm_api_key:
        raise ValueError("LLM_MODEL and LLM_API_KEY are required")
    if settings.llm_timeout <= 0:
        raise ValueError("LLM_TIMEOUT must be positive")
    if not os.getenv("DATABASE_URL"):
        raise ValueError("DATABASE_URL is required")
    owner_id = os.getenv("PILOT_OWNER_ID")
    if not owner_id:
        raise ValueError("PILOT_OWNER_ID is required")
    return UUID(owner_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", default="benchmark_dataset.json", help="Path to the source dataset"
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-prefix", default="pilot-results")
    parser.add_argument(
        "--evaluation-method", choices=("heuristic", "llm_judge"), default="heuristic"
    )
    args = parser.parse_args()

    selected = select_pilot_tasks(load_dataset(args.dataset))
    if args.validate_only:
        print(
            "Validated 8 fixed tasks across 8 categories; "
            "2 repetitions = 16 pairs, 32 target calls"
        )
        return 0

    owner_id = require_live_config()
    json_path = Path(f"{args.output_prefix}.json")
    csv_path = Path(f"{args.output_prefix}.csv")
    if json_path.exists() or csv_path.exists():
        raise ValueError("Output path already exists")

    from .db import SessionLocal
    from .models import User

    provider = OpenAICompatibleProvider()
    with SessionLocal() as db:
        if db.get(User, owner_id) is None:
            raise ValueError("PILOT_OWNER_ID does not identify an existing user")
        records = BenchmarkRunner(
            LLMExecutionService(provider),
            ResponseEvaluationService(judge_provider=provider),
        ).run(
            db,
            selected,
            owner_id,
            repetitions=2,
            parameters={"temperature": 0},
            evaluation_method=args.evaluation_method,
        )
    export_records_json(records, json_path)
    export_records_csv(records, csv_path)
    completed = sum(record.status == "succeeded" for record in records)
    print(f"Completed pairs: {completed}/16; exports: {json_path}, {csv_path}")
    return 0 if completed == 16 else 1


if __name__ == "__main__":
    raise SystemExit(main())
