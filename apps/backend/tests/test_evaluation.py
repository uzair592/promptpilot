import json
from uuid import UUID, uuid4

import pytest

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.evaluation_service import (
    EVALUATION_WEIGHTS,
    ResponseEvaluationService,
    heuristic_score,
    weighted_aggregate,
)
from promptpilot_backend.llm_provider import OpenAICompatibleProvider, ProviderUnavailable
from promptpilot_backend.models import Evaluation, Message, ModelRun
from promptpilot_backend.schemas import EVALUATION_DIMENSIONS, LLMJudgeOutput, ResponseScore


def register_and_conversation(client):
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "evaluation@example.com",
                "display_name": "Evaluation User",
                "password": "correct horse battery",
            },
        ).status_code
        == 201
    )
    project = client.post("/api/v1/projects", json={"name": "Evaluation Project"}).json()
    conversation = client.post(
        f"/api/v1/projects/{project['id']}/conversations",
        json={"title": "Aluminium foil in Pakistan"},
    ).json()
    return project["id"], conversation["id"]


def create_runs(project_id, conversation_id):
    with SessionLocal() as db:
        message = Message(
            conversation_id=UUID(conversation_id),
            role="user",
            content="Explain how aluminium foil is used in Pakistan.",
            sequence=1,
        )
        db.add(message)
        db.flush()
        baseline = ModelRun(
            project_id=UUID(project_id),
            conversation_id=UUID(conversation_id),
            source_message_id=message.id,
            execution_strategy="baseline",
            optimized_prompt=message.content,
            response_text="Aluminium foil is used in Pakistan for food packaging and cooking.",
            provider="deterministic",
            model="fixture",
            status="succeeded",
        )
        promptpilot = ModelRun(
            project_id=UUID(project_id),
            conversation_id=UUID(conversation_id),
            source_message_id=message.id,
            execution_strategy="promptpilot",
            optimized_prompt=message.content
            + " Include practical Pakistani household and packaging examples.",
            response_text=(
                "In Pakistan, aluminium foil is used for household cooking, food storage, "
                "bakery packaging, and protecting food from moisture."
            ),
            provider="deterministic",
            model="fixture",
            status="succeeded",
        )
        db.add_all([baseline, promptpilot])
        db.commit()
        return str(baseline.id), str(promptpilot.id)


def test_rubric_dimensions_and_weights():
    assert EVALUATION_DIMENSIONS == (
        "relevance",
        "completeness",
        "instruction_following",
        "contextual_grounding",
        "clarity",
    )
    assert EVALUATION_WEIGHTS == {
        "relevance": 25,
        "completeness": 20,
        "instruction_following": 20,
        "contextual_grounding": 20,
        "clarity": 15,
    }
    score = ResponseScore(
        relevance=100,
        completeness=80,
        instruction_following=60,
        contextual_grounding=40,
        clarity=20,
    )
    assert weighted_aggregate(score) == 64


def test_heuristic_dimensions_are_independent_and_explainable():
    result = heuristic_score(
        "Explain the capital",
        "The capital is Paris. It is a clear answer.",
        requirements=["include the country"],
        constraints=["one sentence"],
        context=["The capital is Paris"],
    )
    assert result.score.relevance > 0
    assert result.score.completeness < 100
    assert result.score.instruction_following < 100
    assert result.score.contextual_grounding == 100
    assert result.score.clarity == 100
    assert set(result.score.explanations) == set(EVALUATION_DIMENSIONS)

    ignored = heuristic_score(
        "Explain the capital",
        "No relevant answer.",
        context=["The capital is Paris"],
    )
    contradicted = heuristic_score(
        "Explain the capital",
        "The capital is not Paris.",
        context=["The capital is Paris"],
    )
    no_context = heuristic_score("Explain the capital", "A relevant answer.", context=[])
    assert ignored.score.contextual_grounding == 0
    assert contradicted.score.contextual_grounding == 0
    assert no_context.score.contextual_grounding == 100


def test_comparison_persists_ten_dimension_items_and_evidence(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/evaluations/compare",
        json={
            "baseline_run_id": baseline_id,
            "promptpilot_run_id": promptpilot_id,
            "requirements": ["household examples"],
            "constraints": ["be concise"],
            "context": ["Pakistan"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "heuristic"
    assert len(body["items"]) == 10
    assert {item["dimension"] for item in body["items"]} == set(EVALUATION_DIMENSIONS)
    assert body["metadata"]["original_task"].startswith("Explain")
    assert body["overall_delta"] == body["promptpilot_score"] - body["baseline_score"]


def test_single_run_and_history_are_authenticated_and_persisted(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, _ = create_runs(project_id, conversation_id)
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/runs/{baseline_id}/evaluate",
        json={"original_task": "Explain aluminium foil use in Pakistan."},
    )
    assert response.status_code == 200
    assert response.json()["baseline_model_run_id"] == baseline_id
    assert len(response.json()["items"]) == 5
    history = client.get(f"/api/v1/conversations/{conversation_id}/evaluations")
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == response.json()["id"]


def test_comparison_rejects_missing_or_mismatched_runs(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/evaluations/compare",
        json={"baseline_run_id": baseline_id, "promptpilot_run_id": str(uuid4())},
    )
    assert response.status_code == 422
    with SessionLocal() as db:
        promptpilot = db.get(ModelRun, UUID(promptpilot_id))
        assert promptpilot is not None
        promptpilot.provider = "different-target"
        db.commit()
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/evaluations/compare",
        json={"baseline_run_id": baseline_id, "promptpilot_run_id": promptpilot_id},
    )
    assert response.status_code == 422
    unauthenticated = client.get(
        f"/api/v1/conversations/{conversation_id}/evaluations",
        cookies={"promptpilot_test_session": ""},
    )
    assert unauthenticated.status_code == 401


def test_comparison_rejects_mismatched_source_message_without_persisting(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)
    with SessionLocal() as db:
        other_message = Message(
            conversation_id=UUID(conversation_id),
            role="user",
            content="A different source task.",
            sequence=2,
        )
        db.add(other_message)
        db.flush()
        db.get(ModelRun, UUID(promptpilot_id)).source_message_id = other_message.id
        db.commit()

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/evaluations/compare",
        json={"baseline_run_id": baseline_id, "promptpilot_run_id": promptpilot_id},
    )
    assert response.status_code == 422
    assert client.get(f"/api/v1/conversations/{conversation_id}/evaluations").json()["items"] == []


class CapturingJudge:
    name = "judge-provider"
    model = "judge-model"

    def __init__(self):
        self.calls = []

    def judge_response(self, task, response_a, response_b, evidence=None):
        self.calls.append((task, response_a, response_b, evidence))
        return LLMJudgeOutput(
            response_a=ResponseScore(
                relevance=10,
                completeness=10,
                instruction_following=10,
                contextual_grounding=10,
                clarity=10,
            ),
            response_b=ResponseScore(
                relevance=90,
                completeness=90,
                instruction_following=90,
                contextual_grounding=90,
                clarity=90,
            ),
        )


def test_llm_judge_payload_is_blind_and_audit_evidence_is_preserved(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)
    judge = CapturingJudge()
    with SessionLocal() as db:
        evaluation = ResponseEvaluationService(
            judge_provider=judge, assignment=lambda: False
        ).evaluate_pair(
            db,
            UUID(conversation_id),
            UUID(baseline_id),
            UUID(promptpilot_id),
            "A different task is not used.",
            "llm_judge",
            "Original research task.",
            ["include sources"],
            ["be concise"],
            ["Pakistan"],
        )
        assert len(evaluation.items) == 10

    task, response_a, response_b, evidence = judge.calls[0]
    assert task == "Original research task."
    assert response_a.startswith("In Pakistan")
    assert response_b.startswith("Aluminium foil")
    assert evidence == {
        "task": "Original research task.",
        "requirements": ["include sources"],
        "constraints": ["be concise"],
        "context": ["Pakistan"],
        "response_a": response_a,
        "response_b": response_b,
    }
    assert "baseline_executed_prompt" not in evidence
    assert "optimized_prompt" not in evidence
    assert evaluation.rubric_version == "v1"
    assert evaluation.baseline_score == 90
    assert evaluation.promptpilot_score == 10
    audit_evidence = json.loads(evaluation.metadata_json)
    assert audit_evidence["baseline_executed_prompt"] == (
        "Explain how aluminium foil is used in Pakistan."
    )
    assert audit_evidence["optimized_prompt"].startswith(
        "Explain how aluminium foil is used in Pakistan."
    )


def test_llm_judge_assignment_directions_map_scores_back_to_strategies(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)

    for assignment, expected_first, expected_second, expected_baseline, expected_promptpilot in (
        (lambda: True, "Aluminium foil", "In Pakistan", 10, 90),
        (lambda: False, "In Pakistan", "Aluminium foil", 90, 10),
    ):
        judge = CapturingJudge()
        with SessionLocal() as db:
            evaluation = ResponseEvaluationService(
                judge_provider=judge, assignment=assignment
            ).evaluate_pair(
                db,
                UUID(conversation_id),
                UUID(baseline_id),
                UUID(promptpilot_id),
                None,
                "llm_judge",
            )
        assert evaluation.baseline_score == expected_baseline
        assert evaluation.promptpilot_score == expected_promptpilot
        _, response_a, response_b, evidence = judge.calls[0]
        assert response_a.startswith(expected_first)
        assert response_b.startswith(expected_second)
        assert set(evidence) == {
            "task",
            "requirements",
            "constraints",
            "context",
            "response_a",
            "response_b",
        }


class InvalidJudge:
    name = "judge-provider"
    model = "judge-model"

    def __init__(self, result):
        self.result = result

    def judge_response(self, task, response_a, response_b, evidence=None):
        return self.result


@pytest.mark.parametrize(
    "result",
    [
        {"response_a": {}, "response_b": {}},
        {"response_a": {"relevance": 101}, "response_b": {}},
    ],
)
def test_invalid_llm_judge_output_does_not_persist(client, result):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)
    with SessionLocal() as db:
        service = ResponseEvaluationService(
            judge_provider=InvalidJudge(result), assignment=lambda: True
        )
        with pytest.raises(ValueError):
            service.evaluate_pair(
                db,
                UUID(conversation_id),
                UUID(baseline_id),
                UUID(promptpilot_id),
                None,
                "llm_judge",
            )
        assert db.query(Evaluation).count() == 0


def test_provider_failure_does_not_persist_evaluation(client):
    project_id, conversation_id = register_and_conversation(client)
    baseline_id, promptpilot_id = create_runs(project_id, conversation_id)

    class UnavailableJudge:
        name = "judge-provider"
        model = "judge-model"

        def judge_response(self, task, response_a, response_b, evidence=None):
            raise ProviderUnavailable("judge unavailable")

    with SessionLocal() as db:
        service = ResponseEvaluationService(
            judge_provider=UnavailableJudge(), assignment=lambda: True
        )
        with pytest.raises(ProviderUnavailable):
            service.evaluate_pair(
                db,
                UUID(conversation_id),
                UUID(baseline_id),
                UUID(promptpilot_id),
                None,
                "llm_judge",
            )
        assert db.query(Evaluation).count() == 0


def test_provider_payload_contains_neutral_responses_and_structured_evidence(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "response_a": {
                                            "relevance": 80,
                                            "completeness": 80,
                                            "instruction_following": 80,
                                            "contextual_grounding": 80,
                                            "clarity": 80,
                                        },
                                        "response_b": {
                                            "relevance": 70,
                                            "completeness": 70,
                                            "instruction_following": 70,
                                            "contextual_grounding": 70,
                                            "clarity": 70,
                                        },
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("promptpilot_backend.llm_provider.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.base_url = "https://judge.example"
    provider.model = "judge-model"
    provider.api_key = "test-key"
    provider.timeout = 3
    evidence = {
        "requirements": ["requirement"],
        "constraints": ["constraint"],
        "context": ["known fact"],
    }

    provider.judge_response("Original task", "Response A", "Response B", evidence)

    messages = captured["body"]["messages"]
    user_payload = json.loads(messages[1]["content"])
    assert set(user_payload) == {
        "task",
        "requirements",
        "constraints",
        "context",
        "response_a",
        "response_b",
    }
    assert user_payload == {
        "task": "Original task",
        "requirements": ["requirement"],
        "constraints": ["constraint"],
        "context": ["known fact"],
        "response_a": "Response A",
        "response_b": "Response B",
    }
    serialized_user_payload = messages[1]["content"]
    for forbidden in (
        "baseline_executed_prompt",
        "optimized_prompt",
        "baseline_response",
        "promptpilot_response",
        "baseline_model_run_id",
        "promptpilot_model_run_id",
        "execution_strategy",
        "provider",
        "evidence",
        "baseline",
        "promptpilot",
    ):
        assert forbidden not in serialized_user_payload.lower()
    system_prompt = messages[0]["content"].lower()
    assert "response a" in system_prompt and "response b" in system_prompt
    for forbidden in (
        "baseline",
        "promptpilot",
        "improved",
        "optimized",
        "system produced",
    ):
        assert forbidden not in system_prompt
