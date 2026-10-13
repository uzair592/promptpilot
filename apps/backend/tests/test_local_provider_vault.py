from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from promptpilot_backend import orchestration_service


def test_development_vault_key_survives_restart(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        orchestration_service,
        "get_settings",
        lambda: SimpleNamespace(
            provider_key_encryption_key=None,
            app_env="development",
            ensure_storage_directory=lambda: tmp_path,
        ),
    )
    secret = orchestration_service._cipher().encrypt(b"example-provider-key")
    assert orchestration_service._cipher().decrypt(secret) == b"example-provider-key"
    assert (tmp_path / ".provider-vault.key").stat().st_mode & 0o777 == 0o600


def test_production_vault_needs_explicit_key(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        orchestration_service,
        "get_settings",
        lambda: SimpleNamespace(
            provider_key_encryption_key=None,
            app_env="production",
            ensure_storage_directory=lambda: tmp_path,
        ),
    )
    with pytest.raises(HTTPException, match="PROVIDER_KEY_ENCRYPTION_KEY"):
        orchestration_service._cipher()
    assert not (tmp_path / ".provider-vault.key").exists()
