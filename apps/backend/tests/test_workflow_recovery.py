import json
from dataclasses import replace
from io import BytesIO
from urllib.error import URLError
from uuid import UUID

import pytest
from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import Answer, PromptAnalysis, PromptVersion, Question


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

    question = questions.json()["next_question"]
    answered = client.post(
        f"/api/v1/conversations/{conversation['id']}/questions/{question['id']}/answers",
        json={"content": "A complete implementation using current technology"},
    )
    assert answered.status_code == 201, answered.text
    saved_answer = answered.json()["answered_questions"][-1]
    assert saved_answer["question_id"] == question["id"]
    assert saved_answer["question"] == question["text"]
    assert saved_answer["content"] == "A complete implementation using current technology"

    restored_questions = client.get(f"/api/v1/conversations/{conversation['id']}/questions/next")
    assert restored_questions.status_code == 200
    assert restored_questions.json()["answered_questions"][-1]["content"] == (
        "A complete implementation using current technology"
    )


def test_refresh_restores_the_same_pending_question(client):
    _, conversation, message = create_workflow(client)
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/{message['id']}/analysis?mode=baseline"
    )
    path = f"/api/v1/conversations/{conversation['id']}/questions/next"
    first = client.get(path).json()
    second = client.get(path).json()
    assert second["next_question"]["id"] == first["next_question"]["id"]
    with SessionLocal() as db:
        questions = list(db.scalars(select(Question)))
        assert len(questions) == 1


def test_short_answers_complete_without_repeating_answered_gaps(client):
    _, conversation, message = create_workflow(client)
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/{message['id']}/analysis?mode=baseline"
    )
    root = f"/api/v1/conversations/{conversation['id']}"
    session = client.get(f"{root}/questions/next").json()
    seen_questions = set()
    for content in ("Three bullet points", "Keep it informal and short", "No other preferences"):
        question = session["next_question"]
        if question is None:
            break
        assert question["text"] not in seen_questions
        seen_questions.add(question["text"])
        response = client.post(
            f"{root}/questions/{question['id']}/answers", json={"content": content}
        )
        assert response.status_code == 201, response.text
        session = response.json()
        assert session["answered_questions"][-1]["content"] == content
    assert session["status"] == "completed"
    assert session["next_question"] is None
    assert client.get(f"{root}/questions/next").json()["next_question"] is None


def test_retry_of_acknowledged_answer_is_safe(client):
    _, conversation, message = create_workflow(client)
    client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/{message['id']}/analysis?mode=baseline"
    )
    root = f"/api/v1/conversations/{conversation['id']}"
    question = client.get(f"{root}/questions/next").json()["next_question"]
    path = f"{root}/questions/{question['id']}/answers"
    first = client.post(path, json={"content": "Three bullet points"})
    retry = client.post(path, json={"content": "Three bullet points"})
    assert first.status_code == retry.status_code == 201
    assert first.json()["answered_questions"] == retry.json()["answered_questions"]
    assert first.json()["next_question"] == retry.json()["next_question"]
    with SessionLocal() as db:
        assert len(list(db.scalars(select(Answer)))) == 1
    assert client.post(path, json={"content": "A different reply"}).status_code == 409


@pytest.mark.parametrize("reply", ["Yes, please", "x" * 9000])
def test_saved_replies_reach_the_actual_model_request_after_generation_failure(
    client, monkeypatch, reply
):
    _, conversation, message = create_workflow(client)
    root = f"/api/v1/conversations/{conversation['id']}"
    client.post(f"{root}/messages/{message['id']}/analysis?mode=baseline")
    session = client.get(f"{root}/questions/next").json()
    replies = []
    for _ in range(3):
        question = session["next_question"]
        if question is None:
            break
        # The same short reply to different questions must preserve both Q/A pairs.
        content = reply
        replies.append((question["text"], content))
        result = client.post(
            f"{root}/questions/{question['id']}/answers", json={"content": content}
        )
        assert result.status_code == 201
        session = result.json()
    assert session["status"] == "completed"
    assert len(replies) == 2

    import promptpilot_backend.llm_provider as provider_module

    settings = replace(
        provider_module.get_settings(),
        llm_provider="offline-test",
        llm_base_url="https://provider.example.invalid/v1",
        llm_model="test-model",
        llm_api_key="synthetic-test-key",
    )
    monkeypatch.setattr(provider_module, "get_settings", lambda: settings)
    requests = []

    def fake_urlopen(request, *, timeout):
        body = json.loads(request.data)
        payload = json.loads(body["messages"][-1]["content"])
        requests.append(payload)
        if len(requests) == 1:
            raise URLError("Simulated offline failure")
        result = {
            "optimized_prompt": "Write a launch plan using the saved clarification replies.",
            "task_summary": "Launch plan",
            "assumptions": [],
            "incorporated_context": [],
            "incorporated_requirements": [],
            "output_format": "Plan",
            "quality_notes": [],
            "warnings": [],
            "generation_metadata": {},
        }
        return BytesIO(
            json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode()
        )

    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)
    path = f"{root}/prompts/generate"
    assert client.post(path, json={"message_id": message["id"]}).status_code == 503
    restored = client.get(f"{root}/questions/next").json()
    assert len(restored["answered_questions"]) == 2
    generated = client.post(path, json={"message_id": message["id"]})
    assert generated.status_code == 200, generated.text
    for payload in requests:
        sent = payload["input"]["relevant_answers"]
        assert {(item["question"], item["content"]) for item in sent} == set(replies)
        assert payload["input"]["original_prompt"] == message["content"]
        assert payload["input"]["analysis_gaps"] == []


def test_new_prompt_does_not_recover_previous_prompt_questions(client):
    _, conversation, message = create_workflow(client)
    root = f"/api/v1/conversations/{conversation['id']}"
    client.post(f"{root}/messages/{message['id']}/analysis?mode=baseline")
    first = client.get(f"{root}/questions/next").json()
    client.post(f"{root}/messages", json={"role": "user", "content": "A different task"})
    assert client.get(f"{root}/questions/next").status_code == 404
    assert (
        client.get(f"{root}/questions/next?message_id={message['id']}").json()["id"] == first["id"]
    )


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
