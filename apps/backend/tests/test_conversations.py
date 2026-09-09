from uuid import UUID

from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import ProjectMember


def register(client, email: str, name: str = "User"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": "correct horse battery"},
    )
    assert response.status_code == 201


def project(client) -> str:
    response = client.post("/api/v1/projects", json={"name": "Conversation Project"})
    assert response.status_code == 201
    return response.json()["id"]


def test_conversation_message_persistence_and_idempotency(client):
    register(client, "owner@example.com", "Owner")
    project_id = project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/conversations", json={"title": "Planning"}
    )
    assert response.status_code == 201
    conversation_id = response.json()["id"]
    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Build a restaurant website."},
        headers={"Idempotency-Key": "message-1"},
    )
    duplicate = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Different retry body."},
        headers={"Idempotency-Key": "message-1"},
    )
    assert message.status_code == 201
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == message.json()["id"]
    history = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert history.status_code == 200
    assert [(item["sequence"], item["content"]) for item in history.json()["items"]] == [
        (1, "Build a restaurant website.")
    ]


def test_conversation_roles_update_and_member_permissions(client):
    register(client, "owner@example.com", "Owner")
    project_id = project(client)
    conversation_id = client.post(
        f"/api/v1/projects/{project_id}/conversations", json={"title": "Initial"}
    ).json()["id"]
    assert client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "Renamed"}
    ).status_code == 200
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "invalid", "content": "No"},
    ).status_code == 422

    client.post("/api/v1/auth/logout")
    register(client, "member@example.com", "Member")
    with SessionLocal() as db:
        member = db.scalar(
            select(ProjectMember).where(ProjectMember.project_id == UUID(project_id))
        )
        assert member is not None
        from promptpilot_backend.models import User

        user = db.scalar(select(User).where(User.normalized_email == "member@example.com"))
        assert user is not None
        db.add(ProjectMember(project_id=UUID(project_id), user_id=user.id, role="member"))
        db.commit()
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 200
    assert client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "Blocked"}
    ).status_code == 403
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Blocked"},
    ).status_code == 403


def test_cross_project_access_and_archived_mutation_denied(client):
    register(client, "owner@example.com", "Owner")
    project_id = project(client)
    conversation_id = client.post(
        f"/api/v1/projects/{project_id}/conversations", json={"title": "Initial"}
    ).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/archive")
    assert client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "Blocked"}
    ).status_code == 409
    assert client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Blocked"},
    ).status_code == 409

    client.post("/api/v1/auth/logout")
    register(client, "other@example.com", "Other")
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404
    assert client.get(f"/api/v1/conversations/{conversation_id}/messages").status_code == 404
