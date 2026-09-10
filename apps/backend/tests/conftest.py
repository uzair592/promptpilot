import os

os.environ["DATABASE_URL"] = "sqlite:///./test-promptpilot.db"
os.environ["SESSION_COOKIE_NAME"] = "promptpilot_test_session"

import pytest
from fastapi.testclient import TestClient

from promptpilot_backend.db import Base, engine
from promptpilot_backend.main import app


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
