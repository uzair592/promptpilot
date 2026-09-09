from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import User


def test_register_login_me_logout_and_protected_access(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "User@Example.com",
            "display_name": "Test User",
            "password": "correct horse battery",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "User@example.com"
    assert "promptpilot_test_session" in response.cookies
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/auth/protected-check").status_code == 200

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_is_hashed_duplicate_and_invalid_login_are_safe(client):
    payload = {
        "email": "user@example.com",
        "display_name": "Test User",
        "password": "correct horse battery",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.normalized_email == "user@example.com"))
        assert user is not None
        assert user.password_hash != payload["password"]
        user.status = "disabled"
        db.commit()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": payload["password"]},
        ).status_code
        == 401
    )


def test_validation_and_unauthorized_request(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "bad", "display_name": "", "password": "short"},
    )
    assert response.status_code == 422
