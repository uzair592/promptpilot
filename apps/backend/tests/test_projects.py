from uuid import UUID

from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import ProjectMember, User


def register(client, email: str, name: str = "User"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": "correct horse battery"},
    )
    assert response.status_code == 201
    return response


def create_project(client):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "PromptPilot",
            "description": "FYP project",
            "domain": "Software Development",
        },
    )
    assert response.status_code == 201
    return response.json()


def login(client, email: str):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct horse battery"},
    )
    assert response.status_code == 200


def test_create_owner_list_detail_update_archive(client):
    register(client, "owner@example.com", "Owner")
    project = create_project(client)
    assert project["status"] == "active"

    with SessionLocal() as db:
        member = db.scalar(
            select(ProjectMember).where(ProjectMember.project_id == UUID(project["id"]))
        )
        assert member is not None
        assert member.role == "owner"

    assert client.get("/api/v1/projects").json()["items"][0]["id"] == project["id"]
    assert client.get(f"/api/v1/projects/{project['id']}").json()["current_user_role"] == "owner"
    assert (
        client.patch(f"/api/v1/projects/{project['id']}", json={"name": "Updated"}).status_code
        == 200
    )
    assert client.post(f"/api/v1/projects/{project['id']}/archive").json()["status"] == "archived"
    assert (
        client.patch(f"/api/v1/projects/{project['id']}", json={"name": "Nope"}).status_code
        == 409
    )


def test_member_can_read_editor_can_update_and_member_cannot(client):
    register(client, "owner@example.com", "Owner")
    project = create_project(client)
    project_id = project["id"]
    client.post("/api/v1/auth/logout")
    register(client, "member@example.com", "Member")
    client.post("/api/v1/auth/logout")
    register(client, "editor@example.com", "Editor")
    client.post("/api/v1/auth/logout")
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner@example.com"))
        member_user = db.scalar(select(User).where(User.normalized_email == "member@example.com"))
        editor_user = db.scalar(select(User).where(User.normalized_email == "editor@example.com"))
        assert owner is not None and member_user is not None and editor_user is not None
        db.add_all(
            [
                    ProjectMember(
                        project_id=UUID(project_id), user_id=member_user.id, role="member"
                    ),
                    ProjectMember(
                        project_id=UUID(project_id), user_id=editor_user.id, role="editor"
                    ),
            ]
        )
        db.commit()

    client.post("/api/v1/auth/logout")
    login(client, "member@example.com")
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 200
    assert client.patch(f"/api/v1/projects/{project_id}", json={"name": "Nope"}).status_code == 403

    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "editor@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 200
    assert (
        client.patch(f"/api/v1/projects/{project_id}", json={"name": "Edited"}).status_code
        == 200
    )


def test_unrelated_user_cannot_enumerate_project(client):
    register(client, "owner@example.com", "Owner")
    project_id = create_project(client)["id"]
    client.post("/api/v1/auth/logout")
    register(client, "other@example.com", "Other")
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert client.get("/api/v1/projects").json()["items"] == []


def test_project_validation_and_cursor(client):
    register(client, "owner@example.com", "Owner")
    assert client.post("/api/v1/projects", json={"name": ""}).status_code == 422
    for index in range(2):
        assert client.post("/api/v1/projects", json={"name": f"Project {index}"}).status_code == 201
    response = client.get("/api/v1/projects?limit=1")
    assert response.status_code == 200
    assert response.json()["page"]["next_cursor"] is not None
    assert client.get("/api/v1/projects?cursor=bad").status_code == 422
