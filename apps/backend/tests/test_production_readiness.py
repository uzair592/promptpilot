from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from promptpilot_backend import main
from promptpilot_backend.config import ConfigurationError, Settings, normalize_database_url
from promptpilot_backend.document_service import DocumentService
from promptpilot_backend.models import AuthRateLimitCounter


def production_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://promptpilot:secret@db.example.com/promptpilot"
    )
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "persistent"))
    for variable in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(variable, raising=False)


def test_production_settings_accept_postgres_and_optional_llm(monkeypatch, tmp_path):
    production_environment(monkeypatch, tmp_path)

    settings = Settings.from_environment()
    settings.validate()

    assert settings.database_url == "postgresql+psycopg://promptpilot:secret@db.example.com/promptpilot"
    assert settings.secure_cookies
    assert settings.ensure_storage_directory().is_dir()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite:///./promptpilot.db"),
        ("cors_origins", ["*"]),
        ("storage_path", "./relative"),
        ("llm_api_key", "partial"),
    ],
)
def test_production_settings_reject_unsafe_configuration(
    monkeypatch, tmp_path, field, value
):
    production_environment(monkeypatch, tmp_path)
    settings = replace(Settings.from_environment(), **{field: value})

    with pytest.raises(ConfigurationError):
        settings.validate()


def test_production_llm_endpoint_requires_https(monkeypatch, tmp_path):
    production_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://provider.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    with pytest.raises(ConfigurationError, match="HTTPS"):
        Settings.from_environment().validate()


def test_database_url_normalizes_render_postgres_scheme():
    assert (
        normalize_database_url("postgresql://user:password@db.example.com/app")
        == "postgresql+psycopg://user:password@db.example.com/app"
    )


def test_installed_application_finds_migrations_from_backend_working_directory(
    monkeypatch, tmp_path
):
    backend_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(backend_root)
    monkeypatch.setattr(main, "__file__", str(tmp_path / "site-packages" / "main.py"))

    assert main.migration_config_path() == backend_root / "alembic.ini"


def test_storage_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        DocumentService._resolve_storage_path(tmp_path / "storage", "../outside.txt")


def test_health_and_readiness_endpoints(client: TestClient):
    health_response = client.get("/healthz")
    readiness_response = client.get("/readyz")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert readiness_response.status_code == 200
    assert readiness_response.json() == {"status": "ready"}


def test_api_responses_are_not_cacheable(client: TestClient):
    response = client.get("/api/v1/projects")

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_authentication_rate_limit_is_persisted_and_returns_retry_after(
    client: TestClient, db_session: Session
):
    payload = {
        "email": "rate-limited@example.com",
        "display_name": "Rate Limit",
        "password": "correct horse battery",
    }
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    for _ in range(19):
        response = client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 200

    limited = client.post("/api/v1/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "900"

    counter = db_session.scalar(
        select(AuthRateLimitCounter).where(
            AuthRateLimitCounter.key
            == sha256(b"rate-limited@example.com").hexdigest()
        )
    )
    assert counter is not None
    assert counter.request_count == 21
    assert counter.key != "rate-limited@example.com"
