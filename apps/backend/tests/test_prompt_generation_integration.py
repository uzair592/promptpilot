from uuid import UUID

from sqlalchemy import select

from promptpilot_backend.db import SessionLocal
from promptpilot_backend.models import (
    Answer,
    Document,
    DocumentChunk,
    InformationGap,
    ProjectMemoryItem,
    PromptAnalysis,
    PromptVersion,
    Question,
    QuestionSession,
)
from promptpilot_backend.prompt_generation import PromptGenerationResult


def test_generation_api_connects_analysis_answers_memory_and_documents(client, monkeypatch):
    client.post("/api/v1/auth/register", json={"email": "integration@example.com", "display_name": "Integration", "password": "correct horse battery"})
    project_id = client.post("/api/v1/projects", json={"name": "Foil business"}).json()["id"]
    conversation_id = client.post(f"/api/v1/projects/{project_id}/conversations", json={"title": "Marketing"}).json()["id"]
    message = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"role": "user", "content": "Create a marketing plan for my aluminium foil business targeting customers across Pakistan."}).json()
    message_id = UUID(message["id"])
    with SessionLocal() as db:
        db.add(ProjectMemoryItem(project_id=UUID(project_id), category="business", subject="business", content="Pakistani aluminium foil manufacturer", source="user"))
        document = Document(project_id=UUID(project_id), name="business.txt", media_type="text/plain", storage_key="test/integration.txt", size_bytes=35, checksum="integration-checksum", status="processed")
        db.add(document)
        db.flush()
        db.add(DocumentChunk(document_id=document.id, chunk_index=0, content="Wholesale foil delivery across Pakistan", provenance="business.txt — chunk 1", character_count=38, processing_version="test"))
        analysis = PromptAnalysis(project_id=UUID(project_id), conversation_id=UUID(conversation_id), message_id=message_id, task_category="marketing", overall_score=45, status="Needs improvement", analysis_version="test", analysis_mode="baseline", fallback_used=True)
        db.add(analysis)
        db.flush()
        gap = InformationGap(analysis_id=analysis.id, dimension="audience", title="Target customers", description="Target customers are unclear", severity="important", importance="high", question_target="Who are the target customers?")
        db.add(gap)
        db.flush()
        session = QuestionSession(project_id=UUID(project_id), conversation_id=UUID(conversation_id), analysis_id=analysis.id, status="active")
        db.add(session)
        db.flush()
        question = Question(session_id=session.id, gap_id=gap.id, text="Who are the target customers?", question_type="free_text", priority=1, status="answered")
        db.add(question)
        db.flush()
        db.add(Answer(question_id=question.id, content="Wholesale customers across Pakistan", source="user"))
        db.commit()

    captured = {}

    class Provider:
        name = "test-provider"
        model = "test-model"

        def generate_prompt(self, payload):
            captured["payload"] = payload
            source_ids = [item["identifier"] for item in payload["input"]["context_package"]["sources"]]
            return PromptGenerationResult(optimized_prompt="Create a Pakistan-focused foil marketing plan.", task_summary="Create a marketing plan.", assumptions=[], incorporated_context=source_ids, incorporated_requirements=[], output_format="Markdown plan", quality_notes=[], warnings=[], generation_metadata={})

    import promptpilot_backend.prompt_routes as routes

    monkeypatch.setattr(routes, "PromptGenerator", lambda: __import__("promptpilot_backend.prompt_generation", fromlist=["PromptGenerator"]).PromptGenerator(Provider()))
    response = client.post(f"/api/v1/conversations/{conversation_id}/prompts/generate", json={"message_id": message["id"], "mode": "detailed"})
    assert response.status_code == 200, response.text
    assert captured["payload"]["input"]["original_prompt"] == message["content"]
    assert captured["payload"]["input"]["task_category"] == "marketing"
    assert "Pakistani aluminium foil manufacturer" in str(captured["payload"]["input"]["project_memory"])
    assert "Wholesale customers across Pakistan" in str(captured["payload"]["input"]["relevant_answers"])
    assert "Wholesale foil delivery" in str(captured["payload"]["input"]["context_package"])
    assert response.json()["optimized_prompt"] == "Create a Pakistan-focused foil marketing plan."
    with SessionLocal() as db:
        version = db.scalar(select(PromptVersion).where(PromptVersion.conversation_id == UUID(conversation_id)))
        assert version is not None
        assert version.generation_mode == "detailed"
        assert version.original_prompt == message["content"]


def test_generation_denies_cross_project_message(client):
    client.post("/api/v1/auth/register", json={"email": "owner@example.com", "display_name": "Owner", "password": "correct horse battery"})
    first = client.post("/api/v1/projects", json={"name": "First"}).json()["id"]
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/register", json={"email": "other@example.com", "display_name": "Other", "password": "correct horse battery"})
    second = client.post("/api/v1/projects", json={"name": "Second"}).json()["id"]
    conversation = client.post(f"/api/v1/projects/{first}/conversations", json={"title": "Private"})
    assert conversation.status_code == 404
    assert second
