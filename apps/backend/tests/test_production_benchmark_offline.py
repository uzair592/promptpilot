"""Offline production-service orchestration with synthetic fixtures only."""

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.db import SessionLocal
from promptpilot_backend.llm_provider import AIAnalysis, ProviderUnavailable
from promptpilot_backend.models import (
    Document,
    ModelRun,
    ProjectMemoryItem,
    PromptVersion,
    Question,
    User,
)
from promptpilot_backend.production_benchmark_offline import (
    OfflinePipelineBenchmark,
    OfflinePolicy,
    OfflineProviders,
)
from promptpilot_backend.prompt_generation import PromptGenerationResult
from promptpilot_backend.question_generator import GeneratedQuestion
from promptpilot_backend.schemas import LLMJudgeOutput, ResponseScore

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmark_dataset.json"
EXAMPLE = ROOT / "tests/fixtures/production_pipeline/synthetic_manifest.json"
DOCUMENT = ROOT / "tests/fixtures/production_pipeline/synthetic_workshop.txt"


def owner_id(client) -> UUID:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "offline-pipeline@example.com",
            "display_name": "Offline Owner",
            "password": "correct horse battery",
        },
    )
    assert response.status_code == 201
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.normalized_email == "offline-pipeline@example.com")
        )
        assert user is not None
        return user.id


def synthetic_manifest(tmp_path: Path, *, include_answers: bool = True) -> Path:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["fixture_id"] = "synthetic-offline-orchestrator-test"
    if include_answers:
        data["clarification_answers"] = []
        for index, (dimension, target, answer_text) in enumerate(
            [
                (
                    "output",
                    "What should the completed result look like?",
                    "Return a practical step-by-step workshop plan.",
                ),
                (
                    "constraints",
                    "Are there important constraints, limits, or preferences?",
                    "Use a budget of 100 fictional credits.",
                ),
            ],
            start=1,
        ):
            source_id = f"synthetic-orchestrator-answer-{index}"
            data["clarification_answers"].append(
                {
                    "fixture_id": source_id,
                    "task_id": data["task_id"],
                    "source_type": "synthetic_test",
                    "content": answer_text,
                    "content_sha256": hashlib.sha256(answer_text.encode()).hexdigest(),
                    "provenance": {
                        "source_type": "synthetic_test",
                        "source_id": source_id,
                        "description": "Invented solely for offline orchestrator tests",
                    },
                    "gap_key": {"dimension": dimension, "question_target": target},
                }
            )
    (tmp_path / "synthetic_workshop.txt").write_bytes(DOCUMENT.read_bytes())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def policy(**updates):
    values = {
        "question_cap": 2,
        "unmatched_gap": "stop",
        "fallback": "reject",
        "generation_mode": "structured",
        "evaluation_method": "heuristic",
        "model_parameters": {"temperature": 0, "max_tokens": 300},
    }
    values.update(updates)
    return OfflinePolicy(**values)


class FakeAnalysis:
    offline_fixture = True
    name = "offline-analysis"
    model = "analysis-test-model"
    calls = 0
    fail = False

    def analyze(self, prompt):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("synthetic analysis failure")
        return AIAnalysis(task_category="planning", dimensions={}, information_gaps=[])


class FakeQuestion:
    offline_fixture = True
    name = "offline-question"
    model = "question-test-model"
    calls = 0
    fail = False

    def generate_question(self, payload):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("synthetic question failure")
        return GeneratedQuestion(
            question_text=payload["gap_target"],
            related_gap=payload["gap_id"],
            priority=200,
            rationale="Synthetic offline question",
        )


class FakePrompt:
    offline_fixture = True
    name = "offline-prompt"
    model = "prompt-test-model"
    calls = 0
    seen = None
    fail = False

    def generate_prompt(self, payload):
        self.calls += 1
        self.seen = payload
        if self.fail:
            raise ProviderUnavailable("synthetic prompt failure")
        return PromptGenerationResult(
            optimized_prompt="Create a workshop plan using the supplied context.",
            task_summary="Plan a workshop",
            assumptions=[],
            incorporated_context=payload["input"]["context_package"]["allowed_source_ids"],
            incorporated_requirements=[],
            output_format="Plan",
            quality_notes=[],
            warnings=[],
            generation_metadata={},
        )


class FakeTarget:
    offline_fixture = True
    name = "offline-target"
    model = "target-test-model"
    calls = None
    fail_on = None

    def __init__(self):
        self.calls = []

    def generate_response(self, payload):
        self.calls.append(payload)
        if self.fail_on == len(self.calls):
            raise ProviderUnavailable("synthetic target failure")
        return {
            "response_text": "A practical workshop plan with preparation, delivery and follow-up.",
            "finish_reason": "stop",
            "usage": {"total_tokens": 12},
        }


def providers():
    return OfflineProviders(FakeAnalysis(), FakeQuestion(), FakePrompt(), FakeTarget())


def configure_storage(monkeypatch, tmp_path):
    import promptpilot_backend.document_service as service

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            storage_path=str(tmp_path / "storage"), max_upload_bytes=10_000_000
        ),
    )


def run_one(
    client,
    monkeypatch,
    tmp_path,
    *,
    fixture_answers=True,
    providers_value=None,
    policy_value=None,
    repetitions=1,
    observer_sink=None,
):
    configure_storage(monkeypatch, tmp_path)
    fixture = synthetic_manifest(tmp_path, include_answers=fixture_answers)
    selected_providers = providers_value or providers()
    with SessionLocal() as db:
        records = OfflinePipelineBenchmark(selected_providers, observer_sink).run(
            db,
            load_dataset(DATASET),
            [fixture],
            owner_id(client),
            repetitions,
            policy_value or policy(),
            tmp_path / "results",
        )
    return records, selected_providers


def test_full_production_path_is_isolated_and_exports_raw_lineage(client, monkeypatch, tmp_path):
    records, fake = run_one(client, monkeypatch, tmp_path, repetitions=2)
    assert len(records) == 2
    assert all(item.complete_pair and item.status == "complete" for item in records)
    assert [item.condition_order for item in records] == [
        ["baseline", "promptpilot"],
        ["promptpilot", "baseline"],
    ]
    assert len({item.artifacts["project_id"] for item in records}) == 2
    assert len({item.artifacts["conversation_id"] for item in records}) == 2
    assert len({item.artifacts["source_message_id"] for item in records}) == 2
    assert fake.analysis.calls == 2 and fake.question.calls == 4
    assert fake.prompt.calls == 2 and len(fake.target.calls) == 4
    assert "SYNTHETIC_EVAL_ONLY_MARKER" not in json.dumps(fake.prompt.seen)
    for record in records:
        assert (
            record.artifacts["baseline_run"]["executed_prompt"] == record.artifacts["original_task"]
        )
        assert (
            record.artifacts["baseline_run"]["parameters"]
            == record.artifacts["promptpilot_run"]["parameters"]
        )
        assert (
            record.artifacts["baseline_run"]["model"]
            == record.artifacts["promptpilot_run"]["model"]
        )
        assert record.artifacts["prompt_version_id"]
        assert record.artifacts["documents"][0]["chunk_ids"]
        assert record.artifacts["context_sources"]
        assert len(record.artifacts["answers"]) == 2
        assert all(
            answer["reanalysis_mode"] == "baseline" for answer in record.artifacts["answers"]
        )
        assert record.artifacts["evaluation"]["rubric_version"] == "v1"
        assert len(record.artifacts["evaluation"]["items"]) == 10
        assert len(record.provider_observations) == 6
        assert all(stage.status in {"succeeded", "fallback"} for stage in record.stage_ledger)
    with SessionLocal() as db:
        assert len(db.scalars(select(ProjectMemoryItem)).all()) >= 6
        assert len(db.scalars(select(Document)).all()) == 2
        assert len(db.scalars(select(Question)).all()) == 4
        assert len(db.scalars(select(PromptVersion)).all()) == 2
        assert len(db.scalars(select(ModelRun)).all()) == 4
    output = tmp_path / "results"
    exported = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(exported) == 2
    assert exported[0]["execution_mode"] == "offline_fixture"
    assert exported[0]["experiment_scope"] == "production_pipeline_paired_v1"
    assert exported[0]["artifacts"]["baseline_run"]["raw_response"]
    assert "SYNTHETIC_EVAL_ONLY_MARKER" not in json.dumps(
        exported[0]["artifacts"]["generation_input"]
    )
    with (output / "results.csv").open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 2
    assert all(row["execution_mode"] == "offline_fixture" for row in csv_rows)
    assert len(list(output.glob("planning-launch-001-r1-*.json"))) > 5


def test_real_production_service_functions_execute(client, monkeypatch, tmp_path):
    import promptpilot_backend.context_engine as context_module
    import promptpilot_backend.production_benchmark_offline as runner_module

    calls = {}

    def track(owner, name, label):
        original = getattr(owner, name)

        def observed(*args, **kwargs):
            calls[label] = calls.get(label, 0) + 1
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, observed)

    for name in (
        "create_project",
        "create_conversation",
        "add_message",
        "analyze_hybrid",
        "create_question_session",
        "next_question",
        "answer_question",
        "reanalyze_after_answer",
        "build_generation_input",
        "persist_generation",
    ):
        track(runner_module, name, name)
    track(runner_module.ProjectMemoryService, "add_user_answer", "memory")
    track(runner_module.DocumentService, "ingest_file", "document")
    track(context_module.ContextAssembler, "assemble", "context")
    track(runner_module.PromptGenerator, "generate", "prompt")
    track(runner_module.LLMExecutionService, "execute", "target")
    track(runner_module.ResponseEvaluationService, "evaluate_pair", "evaluation")
    records, _ = run_one(client, monkeypatch, tmp_path)
    assert records[0].complete_pair
    assert all(
        calls.get(name, 0) >= 1
        for name in (
            "create_project",
            "create_conversation",
            "add_message",
            "analyze_hybrid",
            "create_question_session",
            "next_question",
            "answer_question",
            "reanalyze_after_answer",
            "build_generation_input",
            "persist_generation",
            "memory",
            "document",
            "context",
            "prompt",
            "target",
            "evaluation",
        )
    )
    assert calls["target"] == 2


def test_missing_answer_remains_partial_without_target_calls(client, monkeypatch, tmp_path):
    records, fake = run_one(client, monkeypatch, tmp_path, fixture_answers=False)
    record = records[0]
    assert record.status == "partial" and not record.complete_pair
    assert record.reason == "unmatched_gap_no_fixture_answer"
    assert record.artifacts["unmatched_gaps"]
    assert fake.analysis.calls == 1 and fake.question.calls == 1
    assert fake.prompt.calls == 0 and fake.target.calls == []
    exported = json.loads((tmp_path / "results/results.json").read_text(encoding="utf-8"))
    assert exported[0]["status"] == "partial"


def test_rejected_analysis_fallback_and_observer_gap_cannot_complete(client, monkeypatch, tmp_path):
    fake = providers()
    fake.analysis.fail = True
    records, fake = run_one(client, monkeypatch, tmp_path, providers_value=fake)
    assert records[0].status == "partial"
    assert records[0].reason == "analysis_fallback_rejected"
    assert records[0].provider_observations[0]["request_outcome"] == "failed"
    assert fake.prompt.calls == 0


def test_rejected_question_fallback_cannot_reach_target(client, monkeypatch, tmp_path):
    fake = providers()
    fake.question.fail = True
    records, fake = run_one(client, monkeypatch, tmp_path, providers_value=fake)
    record = records[0]
    assert record.status == "partial" and not record.complete_pair
    assert record.reason == "question_fallback_rejected"
    assert record.provider_observations[-1]["purpose"] == "question"
    assert record.provider_observations[-1]["request_outcome"] == "failed"
    assert record.provider_observations[-1]["fallback_reason"] == "provider_failed"
    assert fake.prompt.calls == 0 and fake.target.calls == []


def test_observer_failure_is_visible_evidence_failure(client, monkeypatch, tmp_path):
    records, fake = run_one(
        client,
        monkeypatch,
        tmp_path,
        observer_sink=lambda _: (_ for _ in ()).throw(RuntimeError("observer failed")),
    )
    assert records[0].status == "failed" and not records[0].complete_pair
    assert records[0].reason == "ObservationGap"
    assert fake.analysis.calls == 1 and fake.prompt.calls == 0
    assert any(
        stage.name == "analysis" and stage.status == "failed" for stage in records[0].stage_ledger
    )


def test_target_failure_retains_first_raw_run_and_failed_run(client, monkeypatch, tmp_path):
    fake = providers()
    fake.target.fail_on = 2
    records, fake = run_one(client, monkeypatch, tmp_path, providers_value=fake)
    record = records[0]
    assert record.status == "failed" and not record.complete_pair
    assert record.artifacts["baseline_run"]["raw_response"]
    assert record.artifacts["promptpilot_run"]["status"] == "failed"
    assert "evaluation" not in record.artifacts
    assert len(record.provider_observations) == 6


def test_prompt_failure_keeps_stage_evidence(client, monkeypatch, tmp_path):
    fake = providers()
    fake.prompt.fail = True
    records, fake = run_one(client, monkeypatch, tmp_path, providers_value=fake)
    record = records[0]
    assert record.status == "failed" and record.reason == "ProviderUnavailable"
    assert record.artifacts["generation_input"]
    assert record.provider_observations[-1]["purpose"] == "prompt_generation"
    assert record.provider_observations[-1]["request_outcome"] == "failed"
    assert fake.target.calls == []


def test_document_processing_failure_keeps_document_lineage(client, monkeypatch, tmp_path):
    import promptpilot_backend.document_service as service

    class BrokenParser:
        def parse(self, name, media_type, content):
            raise ValueError("synthetic parse failure")

    monkeypatch.setattr(service, "BasicDocumentParser", BrokenParser)
    records, fake = run_one(client, monkeypatch, tmp_path)
    record = records[0]
    assert record.status == "failed" and not record.complete_pair
    assert record.artifacts["documents"][0]["status"] == "failed"
    assert record.artifacts["documents"][0]["document_id"]
    assert fake.analysis.calls == 0 and fake.target.calls == []


def test_unmatched_skip_and_question_cap_never_create_complete_pair(client, monkeypatch, tmp_path):
    records, fake = run_one(
        client,
        monkeypatch,
        tmp_path,
        fixture_answers=False,
        policy_value=policy(question_cap=1, unmatched_gap="skip"),
    )
    record = records[0]
    assert record.status == "partial" and not record.complete_pair
    assert record.artifacts["question_count"] == 1
    assert fake.question.calls == 1 and fake.target.calls == []
    with SessionLocal() as db:
        questions = db.scalars(select(Question)).all()
        assert len(questions) == 1 and questions[0].status == "skipped"


def test_allow_fallback_policy_is_recorded_as_offline_only(client, monkeypatch, tmp_path):
    fake = providers()
    fake.analysis.fail = True
    records, _ = run_one(
        client,
        monkeypatch,
        tmp_path,
        providers_value=fake,
        policy_value=policy(fallback="allow"),
    )
    record = records[0]
    assert record.complete_pair and record.status == "complete"
    assert record.policy["fallback"] == "allow"
    assert record.execution_mode == "offline_fixture"
    assert (
        next(stage for stage in record.stage_ledger if stage.name == "analysis").status
        == "fallback"
    )
    assert record.provider_observations[0]["request_outcome"] == "failed"


def test_offline_provider_and_output_preflight_precede_provider_calls(
    client, monkeypatch, tmp_path
):
    configure_storage(monkeypatch, tmp_path)
    fixture = synthetic_manifest(tmp_path)
    fake = providers()
    fake.analysis.offline_fixture = False
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="offline_fixture=True"):
            OfflinePipelineBenchmark(fake).run(
                db,
                load_dataset(DATASET),
                [fixture],
                owner_id(client),
                1,
                policy(),
                tmp_path / "results",
            )
    assert fake.analysis.calls == 0 and fake.target.calls == []
    fake.analysis.offline_fixture = True
    (tmp_path / "results").mkdir()
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="Output directory"):
            OfflinePipelineBenchmark(fake).run(
                db,
                load_dataset(DATASET),
                [fixture],
                owner_id_from_db(db),
                1,
                policy(),
                tmp_path / "results",
            )
    assert fake.analysis.calls == 0 and fake.target.calls == []


def owner_id_from_db(db):
    user = db.scalar(select(User).where(User.normalized_email == "offline-pipeline@example.com"))
    assert user is not None
    return user.id


def test_llm_judge_uses_injected_offline_provider_and_neutral_mapping(
    client, monkeypatch, tmp_path
):
    class FakeJudge:
        offline_fixture = True
        name = "offline-judge"
        model = "judge-test-model"
        calls = 0

        def judge_response(self, task, response_a, response_b, evidence=None):
            self.calls += 1
            score = ResponseScore(
                relevance=60,
                completeness=60,
                instruction_following=60,
                contextual_grounding=60,
                clarity=60,
            )
            return LLMJudgeOutput(response_a=score, response_b=score)

    fake = providers()
    judge = FakeJudge()
    fake = OfflineProviders(fake.analysis, fake.question, fake.prompt, fake.target, judge)
    records, _ = run_one(
        client,
        monkeypatch,
        tmp_path,
        providers_value=fake,
        policy_value=policy(evaluation_method="llm_judge"),
    )
    record = records[0]
    assert record.complete_pair and judge.calls == 1
    assert record.provider_observations[-1]["purpose"] == "judge"
    assignment = record.artifacts["evaluation"]["metadata"]["judge_assignment"]
    assert set(assignment.values()) == {"baseline", "promptpilot"}


def test_exports_redact_known_credentials_and_authorization_headers(client, monkeypatch, tmp_path):
    class SecretTarget(FakeTarget):
        api_key = "offline-secret-123"

        def generate_response(self, payload):
            self.calls.append(payload)
            return {
                "response_text": "Workshop plan\nAuthorization: Bearer offline-secret-123",
                "finish_reason": "stop",
                "usage": {"total_tokens": 2},
            }

    fake = providers()
    fake = OfflineProviders(fake.analysis, fake.question, fake.prompt, SecretTarget())
    records, _ = run_one(client, monkeypatch, tmp_path, providers_value=fake)
    assert records[0].complete_pair
    for path in (tmp_path / "results").iterdir():
        content = path.read_text(encoding="utf-8")
        assert "offline-secret-123" not in content
        assert "Authorization:" not in content
