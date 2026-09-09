import json
from uuid import uuid4

import pytest

from promptpilot_backend.analyzer_v2 import AnalysisReconciler
from promptpilot_backend.llm_provider import (
    AIAnalysis,
    OpenAICompatibleProvider,
    ProviderUnavailable,
)
from promptpilot_backend.models import InformationGap, PromptAnalysis, PromptAnalysisDimension


def baseline() -> PromptAnalysis:
    analysis = PromptAnalysis(
        id=uuid4(),
        project_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        task_category="general",
        overall_score=30,
        status="Poor",
        analysis_version="prompt-analyzer-v2",
        analysis_mode="hybrid",
        ai_succeeded=False,
        fallback_used=True,
    )
    analysis.dimensions = [
        PromptAnalysisDimension(
            key="context",
            score=20,
            status="missing",
            applicable=True,
            explanation="Baseline context is missing.",
        ),
        PromptAnalysisDimension(
            key="audience",
            score=70,
            status="present",
            applicable=True,
            explanation="Audience is present.",
        ),
    ]
    analysis.gaps = []
    return analysis


def ai_result(category="software_development") -> AIAnalysis:
    return AIAnalysis.model_validate(
        {
            "task_category": category,
            "dimensions": {
                "context": {
                    "applicable": True,
                    "score": 65,
                    "status": "partial",
                    "evidence": "A product is described.",
                    "explanation": "Some context is available.",
                }
            },
            "information_gaps": [
                {
                    "dimension": "context",
                    "title": "Target audience",
                    "description": "The target audience is missing.",
                    "severity": "critical",
                    "importance": "high",
                    "question_target": "Who is the target audience?",
                }
            ],
        }
    )


def test_hybrid_reconciler_consumes_ai_findings_and_is_deterministic():
    first = AnalysisReconciler().reconcile(baseline(), ai_result())
    second = AnalysisReconciler().reconcile(baseline(), ai_result())
    assert first.task_category == "software_development"
    assert next(item for item in first.dimensions if item.key == "context").score == 65
    assert first.gaps[0].title == "Target audience"
    assert first.overall_score == second.overall_score
    assert 0 <= first.overall_score <= 100


def test_ai_classification_wins_documented_disagreement_policy():
    assert (
        AnalysisReconciler().reconcile(baseline(), ai_result("data_analysis")).task_category
        == "data_analysis"
    )


def test_equivalent_gap_is_not_duplicated():
    analysis = baseline()
    analysis.gaps = [
        InformationGap(
            dimension="context",
            title="Target audience",
            description="No users are specified.",
            severity="important",
            importance="high",
            question_target="Who are the users?",
        )
    ]
    result = AnalysisReconciler().reconcile(analysis, ai_result())
    assert len(result.gaps) == 1


def test_openrouter_http_contract_and_structured_validation(monkeypatch):
    import promptpilot_backend.llm_provider as module

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": ai_result().model_dump_json()}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        captured["request"], captured["timeout"] = request, timeout
        return FakeResponse()

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "llm_base_url": "https://example.test/v1",
                "llm_model": "test-model",
                "llm_api_key": "test-secret",
                "llm_timeout": 3,
            },
        )(),
    )
    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    result = OpenAICompatibleProvider().analyze("Build a store")
    request = captured["request"]
    body = json.loads(request.data)
    assert result.task_category == "software_development"
    assert request.full_url.endswith("/chat/completions")
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert body["model"] == "test-model"
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_malformed_provider_response_is_rejected(monkeypatch):
    import promptpilot_backend.llm_provider as module

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b'{"choices": [{"message": {"content": "not-json"}}]}'

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "llm_base_url": "https://example.test/v1",
                "llm_model": "test-model",
                "llm_api_key": "test-secret",
                "llm_timeout": 3,
            },
        )(),
    )
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(ProviderUnavailable):
        OpenAICompatibleProvider().analyze("Build a store")
