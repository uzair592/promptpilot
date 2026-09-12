import json

from promptpilot_backend.benchmark import (
    BenchmarkDataset,
    BenchmarkRunner,
    export_records_csv,
    export_records_json,
    load_dataset,
)
from promptpilot_backend.execution_service import LLMExecutionService
from promptpilot_backend.llm_provider import ProviderUnavailable
from promptpilot_backend.models import User


class FixtureProvider:
    name = "fixture-provider"
    model = "fixture-model"

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_on_call = fail_on_call

    def generate_response(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        if self.fail_on_call == len(self.calls):
            raise ProviderUnavailable("fixture failure")
        return {
            "response_text": f"Fixture response for {payload['prompt']}",
            "finish_reason": "stop",
            "usage": {"total_tokens": 10},
        }


def dataset() -> BenchmarkDataset:
    return BenchmarkDataset.model_validate(
        {
            "name": "test-dataset",
            "tasks": [
                {
                    "task_id": "task-one",
                    "task_text": "Explain a test task.",
                    "objective": "Produce an explanation.",
                    "requirements": ["Mention the test"],
                    "constraints": ["Be concise"],
                    "expected_output_characteristics": ["Clear"],
                    "available_context": ["Fixture context"],
                    "category": "question_answering",
                    "difficulty": "easy",
                }
            ],
        }
    )


def test_dataset_loader_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(
            {
                "name": "invalid",
                "tasks": [
                    {
                        "task_id": "duplicate",
                        "task_text": "One",
                        "objective": "One",
                        "category": "writing",
                        "difficulty": "easy",
                    },
                    {
                        "task_id": "duplicate",
                        "task_text": "Two",
                        "objective": "Two",
                        "category": "writing",
                        "difficulty": "easy",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        load_dataset(path)
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate task IDs should fail validation")


def test_runner_pairs_runs_preserves_lineage_and_exports(db_session, tmp_path):
    user = User(
        email="benchmark@example.com",
        normalized_email="benchmark@example.com",
        display_name="Benchmark",
        password_hash="hash",
    )
    db_session.add(user)
    db_session.commit()
    provider = FixtureProvider()
    runner = BenchmarkRunner(execution_service=LLMExecutionService(provider))

    records = runner.run(
        db_session,
        dataset(),
        user.id,
        repetitions=2,
        parameters={"temperature": 0},
    )

    assert len(records) == 2
    assert {record.status for record in records} == {"succeeded"}
    assert records[0].project_id != records[1].project_id
    assert records[0].conversation_id != records[1].conversation_id
    assert records[0].baseline_model_run_id
    assert records[0].promptpilot_model_run_id
    assert records[0].evaluation_id
    assert provider.calls[0]["parameters"] == {"temperature": 0}
    export_records_json(records, tmp_path / "results.json")
    export_records_csv(records, tmp_path / "results.csv")
    assert len(json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))) == 2
    assert "benchmark_task_id" in (tmp_path / "results.csv").read_text(encoding="utf-8")


def test_runner_records_failed_condition_without_evaluation(db_session):
    user = User(
        email="benchmark-failure@example.com",
        normalized_email="benchmark-failure@example.com",
        display_name="Benchmark",
        password_hash="hash",
    )
    db_session.add(user)
    db_session.commit()
    records = BenchmarkRunner(LLMExecutionService(FixtureProvider(fail_on_call=2))).run(
        db_session, dataset(), user.id
    )

    assert records[0].status == "failed"
    assert records[0].baseline_model_run_id
    assert records[0].promptpilot_model_run_id
    assert records[0].evaluation_id is None
    assert records[0].error == "fixture failure"
