import json

from promptpilot_backend.benchmark import (
    BenchmarkDataset,
    BenchmarkRunner,
    dataset_sha256,
    export_records_csv,
    export_records_json,
    load_dataset,
    request_hash,
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
    runner = BenchmarkRunner(
        execution_service=LLMExecutionService(provider),
        condition_order=lambda repetition: (
            ("promptpilot", "baseline") if repetition == 1 else ("baseline", "promptpilot")
        ),
        repository_revision="test-revision",
    )

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
    assert records[0].condition_order == ["promptpilot", "baseline"]
    assert records[1].condition_order == ["baseline", "promptpilot"]
    assert records[0].dataset_sha256 == dataset_sha256(dataset())
    assert records[0].repository_sha == "test-revision"
    assert len(records[0].attempts) == 2
    assert records[0].attempts[0].condition == "promptpilot"
    assert records[0].attempts[0].execution_order == 1
    assert records[0].attempts[0].generation_parameters == {"temperature": 0}
    assert provider.calls[0]["parameters"] == {"temperature": 0}
    export_records_json(records, tmp_path / "results.json")
    export_records_csv(records, tmp_path / "results.csv")
    assert len(json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))) == 2
    exported_json = (tmp_path / "results.json").read_text(encoding="utf-8")
    exported_csv = (tmp_path / "results.csv").read_text(encoding="utf-8")
    assert "benchmark_task_id" in exported_csv
    assert "test-secret" not in exported_json + exported_csv


def test_request_hash_is_canonical_and_secret_free():
    first = request_hash(
        dataset().tasks[0],
        "baseline",
        "fixture-provider",
        "fixture-model",
        {"temperature": 0},
        None,
        ["Fixture context"],
    )
    second = request_hash(
        dataset().tasks[0],
        "baseline",
        "fixture-provider",
        "fixture-model",
        {"temperature": 0},
        None,
        ["Fixture context"],
    )
    assert first == second
    assert len(first) == 64
    assert "test-secret" not in first


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
    assert len(records[0].attempts) == 2
    assert {attempt.status for attempt in records[0].attempts} == {"succeeded", "failed"}
