import json
from uuid import UUID

from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import PromptAnalysis, PromptVersion


def create_workflow(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "workflow@example.com",
            "display_name": "Workflow",
            "password": "correct horse battery",
        },
    )
    project = client.post("/api/v1/projects", json={"name": "Workflow project"}).json()
    conversation = client.post(
        f"/api/v1/projects/{project['id']}/conversations",
        json={"title": "Saved request"},
    ).json()
    message = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"role": "user", "content": "Write a launch plan."},
        headers={"Idempotency-Key": "workflow-request-1"},
    ).json()
    return project, conversation, message


def test_latest_analysis_and_question_session_recover_after_refresh(client):
    _, conversation, message = create_workflow(client)
    created = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/{message['id']}/analysis"
    )
    assert created.status_code == 201, created.text

    recovered = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages/{message['id']}/analysis"
    )
    assert recovered.status_code == 200
    assert recovered.json()["id"] == created.json()["id"]
    assert recovered.json()["message_id"] == message["id"]

    questions = client.get(f"/api/v1/conversations/{conversation['id']}/questions/next")
    assert questions.status_code == 200
    assert questions.json()["next_question"] is not None


def test_prompt_versions_recover_with_source_and_generation_metadata(client):
    _, conversation, message = create_workflow(client)
    with SessionLocal() as db:
        version = PromptVersion(
            project_id=UUID(conversation["project_id"]),
            conversation_id=UUID(conversation["id"]),
            source_message_id=UUID(message["id"]),
            version_number=1,
            original_prompt=message["content"],
            optimized_prompt="Create a staged launch plan.",
            generation_mode="structured",
            provider="offline-test",
            model="deterministic",
            fallback_used=False,
            metadata_json=json.dumps(
                {
                    "task_summary": "Create a launch plan",
                    "warnings": [],
                    "incorporated_context": [],
                }
            ),
        )
        db.add(version)
        db.commit()

    recovered = client.get(f"/api/v1/conversations/{conversation['id']}/prompts")
    assert recovered.status_code == 200
    payload = recovered.json()[0]
    assert payload["source_message_id"] == message["id"]
    assert payload["version_number"] == 1
    assert payload["generation_metadata"]["provider"] == "offline-test"
    assert payload["created_at"]


def test_recovery_contracts_preserve_project_authorization(client):
    _, conversation, message = create_workflow(client)
    with SessionLocal() as db:
        analysis = PromptAnalysis(
            project_id=UUID(conversation["project_id"]),
            conversation_id=UUID(conversation["id"]),
            message_id=UUID(message["id"]),
            task_category="planning",
            overall_score=50,
            status="Needs improvement",
            analysis_version="test",
            analysis_mode="baseline",
            fallback_used=True,
        )
        db.add(analysis)
        db.commit()
        assert db.scalar(select(PromptAnalysis).where(PromptAnalysis.id == analysis.id))

    client.post("/api/v1/auth/logout")
    assert (
        client.get(
            f"/api/v1/conversations/{conversation['id']}/messages/{message['id']}/analysis"
        ).status_code
        == 401
    )
    assert client.get(f"/api/v1/conversations/{conversation['id']}/prompts").status_code == 401
