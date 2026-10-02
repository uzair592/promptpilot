import copy
import json
import os
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

os.environ["DATABASE_URL"] = "sqlite:///./test-promptpilot.db"
os.environ["SESSION_COOKIE_NAME"] = "promptpilot_test_session"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_call_ledger import BenchmarkCallLedger
from promptpilot_backend.benchmark_experiment_binding import ProtocolBinding, bind_protocol
from promptpilot_backend.benchmark_fixtures import FixtureManifest, manifest_sha256
from promptpilot_backend.db import Base, SessionLocal, engine
from promptpilot_backend.main import app
from promptpilot_backend.models import BenchmarkProviderCallAttempt, User
from promptpilot_backend.production_benchmark_protocol import (
    AdmissionReport,
    HumanApprovalBoundary,
    LiveStudyProtocol,
    calculate_call_ceiling,
    protocol_sha256,
)


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(client):
    from promptpilot_backend.db import SessionLocal

    with SessionLocal() as db:
        yield db


# --- Shared helpers for the pre-live experiment-engine tests -----------------

EXPERIMENT_DATASET = Path(__file__).resolve().parents[1] / "benchmark_dataset.json"
EXPERIMENT_FIXTURES = Path(__file__).resolve().parent / "fixtures/production_pipeline"
EXPERIMENT_PROTOCOL = EXPERIMENT_FIXTURES / "synthetic_protocol.json"
EXPERIMENT_MANIFEST = EXPERIMENT_FIXTURES / "synthetic_manifest.json"

EXPERIMENT_TASK_IDS = (
    "writing-email-001",
    "summarization-policy-001",
    "qa-geography-001",
    "extraction-invoice-001",
    "planning-launch-001",
    "technical-api-001",
    "business-analysis-001",
    "research-information-001",
)


def protocol_payload() -> dict:
    return json.loads(EXPERIMENT_PROTOCOL.read_text(encoding="utf-8"))


def parse_protocol(payload: dict | None = None) -> LiveStudyProtocol:
    return LiveStudyProtocol.model_validate(payload or protocol_payload())


def production_shape_payload() -> dict:
    """The frozen production shape: 8 fixtures, R=3, Q=2, llm_judge."""

    payload = copy.deepcopy(protocol_payload())
    base = payload["selected_fixtures"][0]
    selections = []
    for index in range(1, 9):
        item = copy.deepcopy(base)
        fixture_id = f"unverified-unit-task-{index:02d}"
        item["fixture_id"] = fixture_id
        item["attestation"]["fixture_id"] = fixture_id
        selections.append(item)
    payload["selected_fixtures"] = selections
    payload["repetitions"] = 3
    payload["question_cap"] = 2
    payload["evaluation"] = {"primary": "llm_judge", "secondary": None}
    payload["providers"]["judge"] = {
        "provider": "offline-test",
        "model": "judge-test-model",
    }
    return payload


def bind_offline_fixture(
    tmp_path: Path, payload: dict | None = None
) -> tuple[ProtocolBinding, LiveStudyProtocol]:
    """Bind the synthetic fixture so a real ledger run can be staged offline."""

    dataset = load_dataset(EXPERIMENT_DATASET)
    manifest_payload = json.loads(EXPERIMENT_MANIFEST.read_text(encoding="utf-8"))
    manifest_payload.update(
        {
            "project_facts": [],
            "clarification_answers": [],
            "frozen_documents": [],
            "evaluation_only": [],
        }
    )
    frozen = copy.deepcopy(payload or protocol_payload())
    selection = frozen["selected_fixtures"][0]
    manifest_payload["fixture_id"] = selection["fixture_id"]
    manifest = FixtureManifest.model_validate(manifest_payload)
    manifest_path = tmp_path / "bound_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    digest = manifest_sha256(manifest)
    selection["manifest_path"] = manifest_path.name
    selection["manifest_sha256"] = digest
    selection["attestation"]["fixture_id"] = selection["fixture_id"]
    selection["attestation"]["manifest_sha256"] = digest
    protocol = parse_protocol(frozen)
    return bind_protocol(protocol, dataset, [(manifest, manifest_path)]), protocol


def technical_admission(protocol: LiveStudyProtocol) -> AdmissionReport:
    """Technical admission whose external human approval stays unverified."""

    return AdmissionReport(
        protocol_id=protocol.protocol_id,
        technical_ready=True,
        ready=True,
        protocol_sha256=protocol_sha256(protocol),
        dataset_sha256=protocol.dataset_sha256,
        admitted_fixture_ids=tuple(item.fixture_id for item in protocol.selected_fixtures),
        call_ceiling=calculate_call_ceiling(protocol),
        blockers=(),
        human_approval=HumanApprovalBoundary(
            externally_verified=False,
            statement="Unverified technical engine unit-test claim",
        ),
        authorization_statement="Technical validation does not authorize a live run.",
    )


def experiment_owner(client) -> UUID:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "engine-owner@example.com",
            "display_name": "Engine Owner",
            "password": "correct horse battery",
        },
    )
    assert response.status_code in {201, 409}
    with SessionLocal() as session:
        user = session.scalar(
            select(User).where(User.normalized_email == "engine-owner@example.com")
        )
        assert user is not None
        return user.id


class ExperimentEnvironment(NamedTuple):
    run_id: UUID
    binding: ProtocolBinding
    protocol: LiveStudyProtocol


@pytest.fixture()
def experiment_env(client, tmp_path):
    """A staged, running ledger run plus the binding it was staged against."""

    owner = experiment_owner(client)
    binding, protocol = bind_offline_fixture(tmp_path)
    with SessionLocal() as session:
        run = BenchmarkCallLedger.stage_run(
            session, owner, protocol, technical_admission(protocol)
        )
        BenchmarkCallLedger.start_run(session, run.id)
    return ExperimentEnvironment(run_id=run.id, binding=binding, protocol=protocol)


@pytest.fixture()
def experiment_attempts():
    """Read persisted provider-call attempts for a staged run."""

    def read(run_id: UUID) -> list[BenchmarkProviderCallAttempt]:
        with SessionLocal() as session:
            return list(
                session.scalars(
                    select(BenchmarkProviderCallAttempt).where(
                        BenchmarkProviderCallAttempt.experiment_run_id == run_id
                    )
                )
            )

    return read
