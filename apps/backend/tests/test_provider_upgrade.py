import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import MetaData, create_engine, inspect, text


def test_local_upgrade_preserves_provider_workflow_and_run_history(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "APP_ENV": "test",
        "STORAGE_PATH": str(tmp_path / "storage"),
        "PYTHONPATH": str(root / "src"),
        "LLM_PROVIDER": "",
        "LLM_BASE_URL": "",
        "LLM_MODEL": "",
        "LLM_API_KEY": "",
    }

    def run(*args):
        result = subprocess.run(
            [sys.executable, *args],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run("-m", "alembic", "upgrade", "9d6f4a8c2e11")
    engine = create_engine(database_url)
    metadata = MetaData()
    metadata.reflect(engine)
    ids = {
        name: uuid4().hex
        for name in ("user", "project", "connection", "plan", "phase", "task", "run")
    }
    now = datetime.now(UTC)
    with engine.begin() as db:

        def insert(name, values):
            table = metadata.tables[name]
            db.execute(
                table.insert().values(
                    **{
                        key: value
                        for key, value in {"created_at": now, "updated_at": now, **values}.items()
                        if key in table.c
                    }
                )
            )

        insert(
            "users",
            {
                "id": ids["user"],
                "email": "saved@example.com",
                "normalized_email": "saved@example.com",
                "display_name": "Saved",
                "password_hash": "synthetic",
                "status": "active",
            },
        )
        insert(
            "projects",
            {
                "id": ids["project"],
                "owner_id": ids["user"],
                "name": "Saved POS",
                "status": "active",
            },
        )
        insert(
            "provider_connections",
            {
                "id": ids["connection"],
                "user_id": ids["user"],
                "provider": "openrouter",
                "label": "Saved connection",
                "encrypted_api_key": "opaque",
                "key_fingerprint": "fingerprint",
                "key_last_four": "1234",
                "default_model": "model",
                "status": "active",
            },
        )
        insert(
            "project_plans",
            {
                "id": ids["plan"],
                "project_id": ids["project"],
                "created_by_id": ids["user"],
                "title": "Saved plan",
                "summary": "Saved goal",
                "status": "active",
            },
        )
        insert(
            "plan_milestones",
            {
                "id": ids["phase"],
                "plan_id": ids["plan"],
                "title": "Build",
                "description": "Build POS",
                "position": 1,
                "status": "pending",
            },
        )
        insert(
            "agent_tasks",
            {
                "id": ids["task"],
                "project_id": ids["project"],
                "plan_id": ids["plan"],
                "milestone_id": ids["phase"],
                "created_by_id": ids["user"],
                "assigned_connection_id": ids["connection"],
                "title": "Saved task",
                "description": "Saved instructions",
                "role": "frontend",
                "assignment_reason": "Selected",
                "assigned_model": "model",
                "acceptance_criteria_json": "[]",
                "dependencies_json": "[]",
                "status": "review",
                "attempt_count": 1,
            },
        )
        insert(
            "agent_runs",
            {
                "id": ids["run"],
                "task_id": ids["task"],
                "connection_id": ids["connection"],
                "provider": "openrouter",
                "model": "model",
                "status": "succeeded",
                "output_text": "Saved output",
                "usage_json": "{}",
                "started_at": now,
                "completed_at": now,
            },
        )
    # Development startup upgrades an existing database instead of requiring a reset.
    run(
        "-c",
        "from promptpilot_backend.main import prepare_database_and_storage; "
        "prepare_database_and_storage()",
    )
    with engine.connect() as db:
        assert db.execute(text("SELECT output_text FROM agent_runs")).scalar_one() == "Saved output"
        assert db.execute(text("SELECT title FROM agent_tasks")).scalar_one() == "Saved task"
        assert (
            db.execute(text("SELECT encrypted_api_key FROM provider_connections")).scalar_one()
            == "opaque"
        )
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    assert {"base_url", "models_json"}.issubset(
        {item["name"] for item in inspect(engine).get_columns("provider_connections")}
    )
    run("-m", "alembic", "check")
