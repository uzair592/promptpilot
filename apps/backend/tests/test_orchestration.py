import json
from uuid import UUID

import httpx
from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.github_repository import reviewed_files
from promptpilot_backend.models import AgentTask, ProviderConnection


def register(client, email: str = "owner@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Project Owner",
            "password": "correct horse battery",
        },
    )
    assert response.status_code == 201


def create_project(client) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"name": "Point of sale", "description": "A secure POS for a small shop"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def add_openrouter(client, key: str = "sk-or-test-secret-1234") -> dict[str, object]:
    response = client.post(
        "/api/v1/provider-connections",
        json={
            "provider": "openrouter",
            "label": "My OpenRouter",
            "api_key": key,
            "default_model": "openrouter/free",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_provider_key_is_encrypted_masked_and_tenant_scoped(client):
    register(client)
    created = add_openrouter(client)

    assert created["masked_key"] == "••••1234"
    assert "api_key" not in created
    with SessionLocal() as db:
        stored = db.scalar(select(ProviderConnection))
        assert stored is not None
        assert stored.encrypted_api_key != "sk-or-test-secret-1234"
        assert "test-secret" not in stored.encrypted_api_key

    client.post("/api/v1/auth/logout")
    register(client, "other@example.com")
    assert client.get("/api/v1/provider-connections").json()["items"] == []
    assert client.post(f"/api/v1/provider-connections/{created['id']}/test").status_code == 404


def test_connection_test_never_returns_key(client, monkeypatch):
    register(client)
    connection = add_openrouter(client)
    monkeypatch.setattr(
        "promptpilot_backend.orchestration_routes.test_provider_connection",
        lambda _: ["openrouter/free", "example/model"],
    )

    response = client.post(f"/api/v1/provider-connections/{connection['id']}/test")

    assert response.status_code == 200
    assert response.json()["available_models"] == ["openrouter/free", "example/model"]
    assert "api_key" not in response.text
    assert response.json()["connection"]["last_test_status"] == "passed"


def test_plan_creates_ordered_milestones_tasks_and_provider_routing(client):
    register(client)
    project_id = create_project(client)
    connection = add_openrouter(client)
    with SessionLocal() as db:
        stored = db.scalar(select(ProviderConnection))
        assert stored is not None
        stored.status = "active"
        db.commit()

    response = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={
            "title": "POS delivery plan",
            "idea": "Create a point of sale app with inventory, receipts, roles, and reports.",
            "start_at": "2026-10-13T09:00:00Z",
        },
    )

    assert response.status_code == 201
    plan = response.json()
    assert [item["position"] for item in plan["milestones"]] == [1, 2, 3, 4]
    tasks = [task for milestone in plan["milestones"] for task in milestone["tasks"]]
    assert {task["role"] for task in tasks} == {
        "orchestrator",
        "product_manager",
        "researcher",
        "frontend",
        "backend",
        "api",
        "tester",
    }
    assert all(task["assigned_connection_id"] == connection["id"] for task in tasks)
    assert all(task["assigned_provider"] == "openrouter" for task in tasks)
    assert all(task["status"] == "scheduled" for task in tasks)
    assert all(task["scheduled_for"] for task in tasks)
    assert tasks[0]["dependencies"] == []
    assert tasks[1]["dependencies"] == [tasks[0]["id"]]
    by_title = {task["title"]: task for task in tasks}
    assert by_title["Implement the primary interface"]["dependencies"] == [
        by_title["Design API contracts"]["id"]
    ]
    assert set(by_title["Run independent quality review"]["dependencies"]) == {
        by_title["Implement backend foundation"]["id"],
        by_title["Implement the primary interface"]["id"],
    }


def test_unrelated_user_cannot_read_or_create_project_plan(client):
    register(client)
    project_id = create_project(client)
    client.post("/api/v1/auth/logout")
    register(client, "other@example.com")

    assert client.get(f"/api/v1/projects/{project_id}/plans").status_code == 404
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/plans",
            json={"title": "No access", "idea": "This user must not create a plan."},
        ).status_code
        == 404
    )


def test_run_task_uses_assigned_provider_and_persists_review_output(client, monkeypatch):
    register(client)
    project_id = create_project(client)
    add_openrouter(client)
    with SessionLocal() as db:
        stored = db.scalar(select(ProviderConnection))
        assert stored is not None
        stored.status = "active"
        db.commit()
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={
            "title": "Execution plan",
            "idea": "Create and verify a secure point of sale application.",
        },
    ).json()
    task_id = plan["milestones"][0]["tasks"][0]["id"]

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": "Reviewable scope document"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            }

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout > 0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> FakeResponse:
            assert url == "https://openrouter.ai/api/v1/chat/completions"
            headers = kwargs["headers"]
            assert isinstance(headers, dict)
            assert headers["Authorization"] == "Bearer sk-or-test-secret-1234"
            return FakeResponse()

    monkeypatch.setattr("promptpilot_backend.orchestration_service.httpx.Client", FakeClient)

    response = client.post(f"/api/v1/agent-tasks/{task_id}/run")

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["output_text"] == "Reviewable scope document"
    refreshed = client.get(f"/api/v1/projects/{project_id}/plans").json()["items"][0]
    task = refreshed["milestones"][0]["tasks"][0]
    assert task["status"] == "review"
    assert task["attempt_count"] == 1
    assert task["output_text"] == "Reviewable scope document"

    next_task_id = plan["milestones"][0]["tasks"][1]["id"]
    captured: list[str] = []

    class HandoffClient(FakeClient):
        def post(self, url: str, **kwargs: object) -> FakeResponse:
            body = kwargs["json"]
            assert isinstance(body, dict)
            messages = body["messages"]
            assert isinstance(messages, list)
            captured.append(messages[0]["content"])
            return super().post(url, **kwargs)

    monkeypatch.setattr("promptpilot_backend.orchestration_service.httpx.Client", HandoffClient)
    second = client.post(f"/api/v1/agent-tasks/{next_task_id}/run")
    assert second.status_code == 200
    assert "Create and verify a secure point of sale application." in captured[0]
    assert "Reviewable scope document" in captured[0]


def test_task_waits_for_its_predecessor(client):
    register(client)
    project_id = create_project(client)
    add_openrouter(client)
    with SessionLocal() as db:
        stored = db.scalar(select(ProviderConnection))
        assert stored is not None
        stored.status = "active"
        db.commit()
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={"title": "POS plan", "idea": "Build and test an inventory and sales app."},
    ).json()
    next_task_id = plan["milestones"][0]["tasks"][1]["id"]
    response = client.post(f"/api/v1/agent-tasks/{next_task_id}/run")
    assert response.status_code == 409
    assert "prerequisite" in response.text.lower()


def test_tester_receives_both_parallel_implementation_handoffs(client, monkeypatch):
    register(client)
    project_id = create_project(client)
    add_openrouter(client)
    with SessionLocal() as db:
        connection = db.scalar(select(ProviderConnection))
        assert connection is not None
        connection.status = "active"
        db.commit()
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={"title": "POS", "idea": "Build a complete shop checkout application."},
    ).json()
    tasks = [task for milestone in plan["milestones"] for task in milestone["tasks"]]
    tester_id = next(task["id"] for task in tasks if task["role"] == "tester")
    with SessionLocal() as db:
        for item in tasks:
            if item["id"] == tester_id:
                break
            task = db.get(AgentTask, UUID(item["id"]))
            assert task is not None
            task.status = "review"
            task.output_text = f"Output from {task.role}: {task.title}"
        db.commit()

    received: list[str] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "Test plan"}}]}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def post(self, url: str, **kwargs: object) -> FakeResponse:
            body = kwargs["json"]
            assert isinstance(body, dict)
            received.append(body["messages"][0]["content"])
            return FakeResponse()

    monkeypatch.setattr("promptpilot_backend.orchestration_service.httpx.Client", FakeClient)
    response = client.post(f"/api/v1/agent-tasks/{tester_id}/run")
    assert response.status_code == 200
    assert "Output from backend: Implement backend foundation" in received[0]
    assert "Output from frontend: Implement the primary interface" in received[0]


def test_reviewed_code_creates_draft_pull_request_without_returning_token(client, monkeypatch):
    register(client)
    project_id = create_project(client)
    calls: list[tuple[str, str, object]] = []

    class FakeGitHub:
        def __enter__(self):
            return self

        def __exit__(self, *_: object):
            return None

        def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
            calls.append((method, path, kwargs.get("json")))
            if path == "/repos/owner/my-repo" and method == "GET":
                value = {"full_name": "owner/my-repo", "permissions": {"push": True},
                         "default_branch": "main"}
            elif path.endswith("/git/ref/heads/main"):
                value = {"object": {"sha": "base123"}}
            elif path.endswith("/git/commits/base123"):
                value = {"tree": {"sha": "tree123"}}
            elif path.endswith("/git/trees"):
                value = {"sha": "newtree123"}
            elif path.endswith("/git/commits"):
                value = {"sha": "newcommit123"}
            elif path.endswith("/pulls"):
                value = {"html_url": "https://github.com/owner/my-repo/pull/1"}
            else:
                value = {}
            request = httpx.Request(method, "https://api.github.com" + path)
            return httpx.Response(200, json=value, request=request)

        def get(self, path: str) -> httpx.Response:
            calls.append(("GET", path, None))
            request = httpx.Request("GET", "https://api.github.com" + path)
            return httpx.Response(404, json={}, request=request)

    monkeypatch.setattr("promptpilot_backend.github_repository._client", lambda _: FakeGitHub())
    response = client.put(
        f"/api/v1/projects/{project_id}/repository",
        json={"owner": "owner", "repo": "my-repo", "token": "github-private-secret"},
    )
    assert response.status_code == 200
    assert "github-private-secret" not in response.text
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={"title": "POS", "idea": "Build a small shop point of sale app."},
    ).json()
    task_id = next(
        task["id"] for milestone in plan["milestones"] for task in milestone["tasks"]
        if task["role"] == "api"
    )
    with SessionLocal() as db:
        task = db.get(AgentTask, UUID(task_id))
        assert task is not None
        task.status = "review"
        task.output_text = json.dumps(
            {"files": [{"path": "api/routes.py", "content": "print('ok')"}]}
        )
        db.commit()
    rejected = client.patch(
        f"/api/v1/agent-tasks/{task_id}/draft",
        json={"output_text": json.dumps({
            "files": [{"path": ".github/workflows/ci.yml", "content": "x"}]
        })},
    )
    assert rejected.status_code == 422
    saved = client.patch(
        f"/api/v1/agent-tasks/{task_id}/draft",
        json={"output_text": json.dumps({
            "files": [{"path": "api/routes.py", "content": "print('ok')"}]
        })},
    )
    assert saved.status_code == 200
    published = client.post(f"/api/v1/agent-tasks/{task_id}/publish")
    assert published.status_code == 200
    assert published.json()["pull_request_url"] == "https://github.com/owner/my-repo/pull/1"
    assert next(body for method, path, body in calls if path.endswith("/git/trees")) == {
        "base_tree": "tree123",
        "tree": [
            {"path": "api/routes.py", "mode": "100644", "type": "blob", "content": "print('ok')"}
        ],
    }
    assert next(body for method, path, body in calls if path.endswith("/pulls"))["draft"] is True
    assert client.post(f"/api/v1/agent-tasks/{task_id}/publish").status_code == 200
    assert "github-private-secret" not in str(calls)


def test_agent_files_reject_path_traversal_and_github_workflows():
    for path in ("../secret", "/etc/passwd", ".github/workflows/ci.yml", "src/../bad", "src\\bad"):
        try:
            reviewed_files(json.dumps({"files": [{"path": path, "content": "x"}]}))
        except Exception as error:
            assert getattr(error, "status_code", None) == 422
        else:
            raise AssertionError(f"Unsafe path accepted: {path}")
