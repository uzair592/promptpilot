from uuid import UUID, uuid4

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.evaluation_service import EVALUATION_WEIGHTS, weighted_aggregate
from promptpilot_backend.models import Message, ModelRun
from promptpilot_backend.schemas import EVALUATION_DIMENSIONS, ResponseScore


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
