"""Offline coverage for shared question operations and provider attempt observation."""

import json
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from promptpilot_backend.analyzer_v2 import analyze_hybrid
from promptpilot_backend.db import SessionLocal
from promptpilot_backend.llm_provider import AIAnalysis, ProviderUnavailable
from promptpilot_backend.models import (
    InformationGap,
    Message,
    PromptAnalysis,
    Question,
    QuestionSession,
)
from promptpilot_backend.provider_observation import ProviderCallObservation
from promptpilot_backend.question_generator import GeneratedQuestion
from promptpilot_backend.question_service import (
    create_question_session,
    next_question,
    skip_and_next_question,
)


def create_message(client) -> tuple[UUID, UUID, UUID]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "pilot-owner@example.com",
            "display_name": "Owner",
            "password": "correct horse battery",
        },
    )
    assert registered.status_code == 201
    project = client.post("/api/v1/projects", json={"name": "Offline test project"})
    assert project.status_code == 201
    project_id = UUID(project.json()["id"])
    conversation = client.post(
        f"/api/v1/projects/{project_id}/conversations", json={"title": "Offline test"}
    )
    assert conversation.status_code == 201
    conversation_id = UUID(conversation.json()["id"])
    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Plan a small workshop for a local group."},
    )
    assert message.status_code == 201
    return project_id, conversation_id, UUID(message.json()["id"])


def create_session_with_gap(db, project_id: UUID, conversation_id: UUID, message_id: UUID):
    analysis = PromptAnalysis(
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_category="planning",
        overall_score=40,
        status="Poor",
        analysis_version="test",
        analysis_mode="baseline",
        fallback_used=False,
    )
    db.add(analysis)
    db.flush()
    db.add(
        InformationGap(
            analysis_id=analysis.id,
            dimension="audience",
            title="Audience",
            description="Audience is missing",
            severity="important",
            importance="high",
            question_target="Who is the audience?",
            status="unresolved",
        )
    )
    db.commit()
    return create_question_session(db, analysis)


def assert_attempt(event: ProviderCallObservation, purpose: str, outcome: str) -> None:
    assert event.purpose == purpose
    assert event.request_outcome == outcome
    assert event.started_at is not None and event.finished_at is not None
    assert event.finished_at >= event.started_at
    assert event.latency_ms is not None and event.latency_ms >= 0
    assert event.request_hash is not None and len(event.request_hash) == 64


def test_routes_preserve_session_creation_skip_contract_and_authorization(client) -> None:
    _, conversation_id, message_id = create_message(client)
    analysis_response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages/{message_id}/analysis?mode=baseline"
    )
    assert analysis_response.status_code == 201
    next_response = client.get(f"/api/v1/conversations/{conversation_id}/questions/next")
    assert next_response.status_code == 200
    question_id = next_response.json()["next_question"]["id"]
    with SessionLocal() as db:
        session = db.scalar(
            select(QuestionSession).where(QuestionSession.conversation_id == conversation_id)
        )
        assert session is not None
        assert str(session.id) == next_response.json()["id"]
        assert str(session.analysis_id) == analysis_response.json()["id"]
    client.post("/api/v1/auth/logout")
    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": "pilot-intruder@example.com",
            "display_name": "Intruder",
            "password": "correct horse battery",
        },
    )
    assert intruder.status_code == 201
    denied = client.post(f"/api/v1/conversations/{conversation_id}/questions/{question_id}/skip")
    assert denied.status_code == 404  # Existing policy conceals projects from nonmembers.
    with SessionLocal() as db:
        assert db.get(Question, UUID(question_id)).status == "presented"
    client.post("/api/v1/auth/logout")
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "pilot-owner@example.com", "password": "correct horse battery"},
    )
    assert logged_in.status_code == 200
    skipped = client.post(f"/api/v1/conversations/{conversation_id}/questions/{question_id}/skip")
    assert skipped.status_code == 200
    assert set(skipped.json()) == {
        "id",
        "status",
        "stop_reason",
        "next_question",
        "analysis",
        "memory_updates",
    }
    with SessionLocal() as db:
        assert db.get(Question, UUID(question_id)).status == "skipped"


def test_analysis_injected_provider_success_and_observer_isolation(client, monkeypatch) -> None:
    project_id, conversation_id, message_id = create_message(client)
    import promptpilot_backend.analyzer_v2 as module

    monkeypatch.setattr(
        module,
        "OpenAICompatibleProvider",
        lambda: (_ for _ in ()).throw(AssertionError("real provider constructed")),
    )

    class FakeProvider:
        name = "fake-analysis"
        model = "fake-model"
        calls = 0

        def analyze(self, prompt):
            self.calls += 1
            assert prompt == "Plan a small workshop for a local group."
            return AIAnalysis(task_category="planning", dimensions={}, information_gaps=[])

    provider = FakeProvider()
    events = []
    with SessionLocal() as db:
        message = db.get(Message, message_id)
        result = analyze_hybrid(
            db,
            project_id,
            conversation_id,
            message,
            provider=provider,
            observer=lambda event: events.append(event),
        )
        assert result.ai_succeeded and not result.fallback_used
    assert provider.calls == 1
    assert len(events) == 1
    assert_attempt(events[0], "analysis", "succeeded")
    assert events[0].service_result == "ai" and events[0].fallback_reason is None

    with SessionLocal() as db:
        message = db.get(Message, message_id)
        # Observation failure cannot alter a successful analysis.
        second = analyze_hybrid(
            db,
            project_id,
            conversation_id,
            message,
            provider=provider,
            observer=lambda _: (_ for _ in ()).throw(RuntimeError("observer failure")),
        )
        assert second.ai_succeeded


def test_analysis_no_configuration_is_not_a_provider_request(client, monkeypatch) -> None:
    project_id, conversation_id, message_id = create_message(client)
    import promptpilot_backend.analyzer_v2 as module

    class UnconfiguredProvider:
        name = "openai-compatible"
        model = ""
        base_url = ""
        api_key = ""

        def analyze(self, prompt):
            raise AssertionError("no request expected")

    monkeypatch.setattr(module, "OpenAICompatibleProvider", UnconfiguredProvider)
    events = []
    with SessionLocal() as db:
        result = analyze_hybrid(
            db,
            project_id,
            conversation_id,
            db.get(Message, message_id),
            observer=events.append,
        )
        assert result.fallback_used and not result.ai_succeeded
    assert len(events) == 1
    assert events[0].request_outcome == "not_attempted"
    assert events[0].request_hash is None and events[0].started_at is None
    assert events[0].fallback_reason == "not_configured"


def test_analysis_records_successful_request_even_if_reconciliation_fails(
    client, monkeypatch
) -> None:
    project_id, conversation_id, message_id = create_message(client)
    import promptpilot_backend.analyzer_v2 as module

    class FakeProvider:
        name = "fake-analysis"
        model = "fake-model"

        def analyze(self, prompt):
            return AIAnalysis(task_category="planning", dimensions={}, information_gaps=[])

    monkeypatch.setattr(
        module.AnalysisReconciler,
        "reconcile",
        lambda self, baseline, ai_result: (_ for _ in ()).throw(ValueError("bad reconciliation")),
    )
    events = []
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="bad reconciliation"):
            analyze_hybrid(
                db,
                project_id,
                conversation_id,
                db.get(Message, message_id),
                provider=FakeProvider(),
                observer=events.append,
            )
    assert_attempt(events[0], "analysis", "succeeded")
    assert events[0].service_result == "error"


def test_analysis_failed_attempt_falls_back_without_recording_secret(client, monkeypatch) -> None:
    project_id, conversation_id, message_id = create_message(client)
    import promptpilot_backend.provider_observation as observation

    monkeypatch.setattr(
        observation, "get_settings", lambda: SimpleNamespace(llm_api_key="credential-123")
    )

    class FailingProvider:
        name = "fake-credential-123"
        model = "model-credential-123"

        def analyze(self, prompt):
            raise ProviderUnavailable("credential-123 must not be recorded")

    events = []
    with SessionLocal() as db:
        result = analyze_hybrid(
            db,
            project_id,
            conversation_id,
            db.get(Message, message_id),
            provider=FailingProvider(),
            observer=events.append,
        )
        assert result.fallback_used and not result.ai_succeeded
    assert_attempt(events[0], "analysis", "failed")
    assert events[0].fallback_reason == "provider_failed"
    assert "credential-123" not in json.dumps(asdict(events[0]), default=str)
    assert "Authorization" not in json.dumps(asdict(events[0]), default=str)


def test_question_injected_calls_duplicate_and_failed_fallbacks(client, monkeypatch) -> None:
    project_id, conversation_id, message_id = create_message(client)
    import promptpilot_backend.provider_observation as observation
    import promptpilot_backend.question_service as service

    monkeypatch.setattr(
        observation, "get_settings", lambda: SimpleNamespace(llm_api_key="question-secret")
    )
    monkeypatch.setattr(
        service,
        "OpenAICompatibleProvider",
        lambda: (_ for _ in ()).throw(AssertionError("real provider constructed")),
    )

    class FakeProvider:
        name = "fake-question-secret"
        model = "fake-model-question-secret"
        calls = 0

        def generate_question(self, payload):
            self.calls += 1
            return GeneratedQuestion(
                question_text="What is the audience size?",
                related_gap=payload["gap_id"],
                priority=200,
                rationale="Ask for size",
            )

    provider = FakeProvider()
    events = []
    with SessionLocal() as db:
        session = create_session_with_gap(db, project_id, conversation_id, message_id)
        first = next_question(db, session, provider=provider, observer=events.append)
        assert first.source == "ai"
        second = next_question(db, session, provider=provider, observer=events.append)
        assert second.source == "fallback"
        assert second.text == "Who is the audience?"
        assert first.id != second.id
    assert provider.calls == 2
    assert_attempt(events[0], "question", "succeeded")
    assert events[0].service_result == "ai" and events[0].fallback_reason is None
    assert_attempt(events[1], "question", "succeeded")
    assert events[1].service_result == "fallback"
    assert events[1].fallback_reason == "duplicate_question"
    assert "question-secret" not in json.dumps([asdict(event) for event in events], default=str)

    class FailingProvider:
        name = "fake-question"
        model = "fake-model"

        def generate_question(self, payload):
            raise ProviderUnavailable("offline failure")

    failed_events = []
    with SessionLocal() as db:
        session = db.scalar(
            select(QuestionSession).where(QuestionSession.conversation_id == conversation_id)
        )
        fallback = next_question(
            db, session, provider=FailingProvider(), observer=failed_events.append
        )
        assert fallback.source == "fallback"
    assert_attempt(failed_events[0], "question", "failed")
    assert failed_events[0].fallback_reason == "provider_failed"

    class InvalidProvider:
        name = "fake-question"
        model = "fake-model"

        def generate_question(self, payload):
            return GeneratedQuestion(
                question_text="An unrelated question?",
                related_gap="wrong-gap",
                priority=200,
                rationale="Wrong mapping",
            )

    invalid_events = []
    with SessionLocal() as db:
        session = db.scalar(
            select(QuestionSession).where(QuestionSession.conversation_id == conversation_id)
        )
        fallback = next_question(
            db, session, provider=InvalidProvider(), observer=invalid_events.append
        )
        assert fallback.source == "fallback"
    assert_attempt(invalid_events[0], "question", "succeeded")
    assert invalid_events[0].fallback_reason == "invalid_question"


def test_question_no_configuration_and_shared_skip_service(client, monkeypatch) -> None:
    project_id, conversation_id, message_id = create_message(client)
    import promptpilot_backend.question_service as service

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(llm_provider="", llm_base_url="", llm_model="", llm_api_key=""),
    )
    monkeypatch.setattr(
        service,
        "OpenAICompatibleProvider",
        lambda: (_ for _ in ()).throw(AssertionError("unconfigured provider constructed")),
    )
    events = []
    with SessionLocal() as db:
        session = create_session_with_gap(db, project_id, conversation_id, message_id)
        first = next_question(db, session, observer=events.append)
        assert first.source == "fallback"
        following = skip_and_next_question(db, session, first, observer=events.append)
        assert first.status == "skipped"
        assert following is None
        assert session.status == "completed"
        assert session.stop_reason == "no_unresolved_gaps"
    assert len(events) == 1
    assert events[0].request_outcome == "not_attempted"
    assert events[0].fallback_reason == "not_configured"
    assert events[0].request_hash is None

    with SessionLocal() as db:
        another = create_session_with_gap(db, project_id, conversation_id, message_id)
        question = next_question(
            db,
            another,
            observer=lambda _: (_ for _ in ()).throw(RuntimeError("observer failure")),
        )
        assert question.source == "fallback"
