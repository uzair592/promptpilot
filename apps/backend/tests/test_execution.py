import json
from uuid import uuid4

from promptpilot_backend.execution_service import LLMExecutionService
from promptpilot_backend.models import Conversation, Message, Project, PromptVersion, User


class Provider:
    name = "test-provider"
    model = "test-model"

    def __init__(self):
        self.payloads = []

    def generate_response(self, payload):
        self.payloads.append(payload)
        return {"response_text": "deterministic response", "finish_reason": "stop", "usage": {"total_tokens": 7}}


def test_baseline_and_promptpilot_execute_exact_prompt(db_session):
    user = User(email="execute@example.com", normalized_email="execute@example.com", display_name="Execute", password_hash="hash")
    project = Project(owner_id=uuid4(), name="Execution")
    db_session.add_all([user, project])
    db_session.flush()
    project.owner_id = user.id
    conversation = Conversation(project_id=project.id, title="Run")
    db_session.add(conversation)
    db_session.flush()
    message = Message(conversation_id=conversation.id, role="user", content="Original exact prompt", sequence=1)
    db_session.add(message)
    db_session.flush()
    version = PromptVersion(project_id=project.id, conversation_id=conversation.id, source_message_id=message.id, version_number=1, original_prompt=message.content, optimized_prompt="Optimized exact prompt", generation_mode="structured", provider="test", model="test")
    db_session.add(version)
    db_session.commit()
    provider = Provider()
    service = LLMExecutionService(provider)
    baseline, _ = service.execute(db_session, None, message, None, {}, "baseline")
    pilot, _ = service.execute(db_session, version, message, None, {}, "promptpilot")
    assert provider.payloads == [{"prompt": "Original exact prompt", "system_instruction": None, "parameters": {}}, {"prompt": "Optimized exact prompt", "system_instruction": None, "parameters": {}}]
    assert baseline.execution_strategy == "baseline"
    assert pilot.prompt_version_id == version.id
    assert json.loads(baseline.generation_parameters_json) == {}
    assert json.loads(pilot.generation_parameters_json) == {}
    assert json.loads(baseline.usage_json) == {"total_tokens": 7}
