import json
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.llm_provider import ProviderUnavailable
from promptpilot_backend.models import ProviderConnection
from promptpilot_backend.prompt_generation import PromptGenerationResult
from promptpilot_backend.provider_gateway import ProviderGateway
from promptpilot_backend.workflow_service import PlannedWorkflow


def workspace(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "visual@example.com",
            "display_name": "Visual",
            "password": "correct horse battery",
        },
    )
    project = client.post("/api/v1/projects", json={"name": "Restaurant POS"}).json()
    chat = client.post(
        f"/api/v1/projects/{project['id']}/conversations", json={"title": "Untitled chat"}
    ).json()
    return project["id"], chat["id"]


def connection(client, provider="gemini"):
    result = client.post(
        "/api/v1/provider-connections",
        json={
            "provider": provider,
            "label": f"My {provider}",
            "api_key": "example-not-live-key",
            "default_model": "example-model",
        },
    )
    assert result.status_code == 201, result.text
    with SessionLocal() as db:
        saved = db.get(ProviderConnection, UUID(result.json()["id"]))
        saved.status = "active"
        saved.models_json = json.dumps(["example-model", "second-model"])
        db.commit()
    return result.json()["id"]


@pytest.mark.parametrize("prompt", ["hi", "amazing", "hello", "thanks"])
def test_reactions_score_zero_and_do_not_call_provider(client, monkeypatch, prompt):
    _, chat_id = workspace(client)
    connection(client)
    monkeypatch.setattr(ProviderGateway, "analyze", lambda *_: pytest.fail("No model needed"))
    message = client.post(
        f"/api/v1/conversations/{chat_id}/messages", json={"role": "user", "content": prompt}
    ).json()
    response = client.post(f"/api/v1/conversations/{chat_id}/messages/{message['id']}/analysis")
    assert response.status_code == 201
    assert response.json()["overall_score"] == 0
    assert response.json()["ai_succeeded"] is False


def test_different_tasks_get_relevant_questions_and_simple_explanations_need_none(client):
    _, chat_id = workspace(client)
    questions = []
    for content in ("Build a restaurant POS", "Analyze these numbers", "Write a launch plan"):
        message = client.post(
            f"/api/v1/conversations/{chat_id}/messages", json={"role": "user", "content": content}
        ).json()
        client.post(
            f"/api/v1/conversations/{chat_id}/messages/{message['id']}/analysis?mode=baseline"
        )
        result = client.get(f"/api/v1/conversations/{chat_id}/questions/next").json()
        questions.append(result["next_question"]["text"])
    assert len(set(questions)) == 3
    assert "restaurant POS" in questions[0]
    assert "data" in questions[1].lower()
    assert "launch" in questions[2].lower()
    message = client.post(
        f"/api/v1/conversations/{chat_id}/messages",
        json={"role": "user", "content": "Explain photosynthesis simply"},
    ).json()
    client.post(f"/api/v1/conversations/{chat_id}/messages/{message['id']}/analysis?mode=baseline")
    assert (
        client.get(f"/api/v1/conversations/{chat_id}/questions/next").json()["next_question"]
        is None
    )


def test_gemini_recovers_rate_limit_and_invalid_json_in_one_user_request(monkeypatch):
    requests = []
    bodies = [
        httpx.Response(429, headers={"retry-after": "0"}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "bad JSON"}]}}]}),
        httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "task_category": "writing",
                                            "dimensions": {},
                                            "information_gaps": [],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        ),
    ]

    def handler(request):
        requests.append(request)
        return bodies.pop(0)

    original = httpx.Client
    monkeypatch.setattr(
        "promptpilot_backend.provider_gateway.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr("promptpilot_backend.provider_gateway.time.sleep", lambda _: None)
    result = ProviderGateway("gemini", "models/example-model", "example-key").analyze(
        "Write a poem"
    )
    assert result.task_category == "writing"
    assert len(requests) == 3
    assert all(str(item.url).endswith("models/example-model:generateContent") for item in requests)
    assert all(item.headers["x-goog-api-key"] == "example-key" for item in requests)
    assert (
        json.loads(requests[-1].content)["generationConfig"]["responseMimeType"]
        == "application/json"
    )


def test_invalid_key_fails_once_with_actionable_error(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(401)

    original = httpx.Client
    monkeypatch.setattr(
        "promptpilot_backend.provider_gateway.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ProviderUnavailable, match="key was rejected"):
        ProviderGateway("grok", "grok-model", "private-test-key").complete("test")
    assert len(attempts) == 1
    assert str(attempts[0].url) == "https://api.x.ai/v1/chat/completions"


def test_chat_generation_uses_user_vault_and_preserves_provider_failures(client, monkeypatch):
    _, chat_id = workspace(client)
    provider_id = connection(client)
    message = client.post(
        f"/api/v1/conversations/{chat_id}/messages",
        json={
            "role": "user",
            "content": "Write a friendly email about tomorrow's meeting.",
        },
    ).json()
    captured = []

    def generate(self, payload):
        captured.append((self.name, payload["input"]["original_prompt"]))
        return PromptGenerationResult(
            optimized_prompt="Write a friendly meeting email.",
            task_summary="Meeting email",
            assumptions=[],
            incorporated_context=[],
            incorporated_requirements=[],
            output_format="Email",
            quality_notes=[],
            warnings=[],
            generation_metadata={},
        )

    monkeypatch.setattr(ProviderGateway, "generate_prompt", generate)
    response = client.post(
        f"/api/v1/conversations/{chat_id}/prompts/generate",
        json={
            "message_id": message["id"],
            "connection_id": provider_id,
        },
    )
    assert response.status_code == 200, response.text
    assert captured == [("gemini", message["content"])]
    assert response.json()["generation_metadata"]["provider"] == "gemini"

    def fail(*_):
        raise ProviderUnavailable("Provider rate limit reached. Wait before running again.")

    monkeypatch.setattr(ProviderGateway, "generate_prompt", fail)
    failed = client.post(
        f"/api/v1/conversations/{chat_id}/prompts/generate",
        json={
            "message_id": message["id"],
            "connection_id": provider_id,
        },
    )
    assert failed.status_code == 503
    assert "rate limit" in failed.json()["error"]["message"]


def test_catalog_grok_custom_endpoint_and_multiple_models(client):
    workspace(client)
    catalog = client.get("/api/v1/provider-connections/catalog").json()["items"]
    assert {"grok", "gemini", "custom"}.issubset({item["id"] for item in catalog})
    grok = connection(client, "grok")
    assert (
        client.patch(
            f"/api/v1/provider-connections/{grok}", json={"default_model": "second-model"}
        ).status_code
        == 200
    )
    for url in ("http://example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1"):
        bad = client.post(
            "/api/v1/provider-connections",
            json={
                "provider": "custom",
                "label": "Invalid",
                "api_key": "test-key-1234",
                "default_model": "model",
                "base_url": url,
            },
        )
        assert bad.status_code == 422
    valid = client.post(
        "/api/v1/provider-connections",
        json={
            "provider": "custom",
            "label": "Another service",
            "api_key": "test-key-1234",
            "default_model": "model",
            "base_url": "https://models.example.com/v1",
        },
    )
    assert valid.status_code == 201
    assert "api_key" not in valid.json()


def test_workflow_editing_rejects_cycles_and_requires_real_output_for_approval(client):
    project_id, _ = workspace(client)
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={
            "title": "POS workflow",
            "idea": "Build a restaurant POS with receipts and inventory",
        },
    ).json()
    tasks = [task for phase in plan["milestones"] for task in phase["tasks"]]
    assert (
        client.patch(
            f"/api/v1/agent-tasks/{tasks[0]['id']}",
            json={
                "dependencies": [tasks[1]["id"]],
            },
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/agent-tasks/{tasks[0]['id']}",
            json={
                "status": "completed",
            },
        ).status_code
        == 409
    )
    created = client.post(
        f"/api/v1/plans/{plan['id']}/tasks",
        json={
            "title": "Review receipt UX",
            "description": "Check the print layout",
            "role": "tester",
        },
    )
    assert created.status_code == 201
    assert client.get(f"/api/v1/agent-tasks/{created.json()['id']}/runs").json() == []
    assert client.delete(f"/api/v1/agent-tasks/{tasks[0]['id']}").status_code == 409
    assert client.delete(f"/api/v1/agent-tasks/{created.json()['id']}").status_code == 204


def test_ai_planner_returns_idea_specific_nodes_and_routes_grok(client, monkeypatch):
    project_id, _ = workspace(client)
    grok = connection(client, "grok")
    result = PlannedWorkflow.model_validate(
        {
            "milestones": [
                {
                    "title": "Receipt delivery",
                    "description": "Readable thermal receipts",
                    "tasks": [
                        {
                            "key": "receipt",
                            "title": "Build the receipt preview",
                            "description": "80mm preview",
                            "role": "frontend",
                            "acceptance_criteria": ["Prints at 80mm"],
                            "dependencies": [],
                        },
                        {
                            "key": "qa",
                            "title": "Review the receipt",
                            "description": "Check readability",
                            "role": "tester",
                            "acceptance_criteria": ["Readable totals"],
                            "dependencies": ["receipt"],
                        },
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr("promptpilot_backend.workflow_service.generate_workflow", lambda *_: result)
    response = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={
            "title": "Receipt workflow",
            "idea": "Build and test readable restaurant receipts",
            "planner_connection_id": grok,
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["planning_mode"] == "ai"
    tasks = plan["milestones"][0]["tasks"]
    assert tasks[1]["dependencies"] == [tasks[0]["id"]]
    assert all(task["assigned_provider"] == "grok" for task in tasks)


def test_connections_are_not_usable_by_another_account(client):
    project_id, _ = workspace(client)
    private = connection(client)
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "display_name": "Other",
            "password": "correct horse battery",
        },
    )
    assert client.post(f"/api/v1/provider-connections/{private}/test").status_code == 404
    assert client.get(f"/api/v1/projects/{project_id}/plans").status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(ProviderConnection)).encrypted_api_key != "example-not-live-key"
