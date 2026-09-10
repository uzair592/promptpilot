from uuid import uuid4

import pytest

from promptpilot_backend.prompt_generation import (
    PromptGenerationInput,
    PromptGenerationResult,
    PromptGenerator,
)


def input_data() -> PromptGenerationInput:
    return PromptGenerationInput(
        original_prompt="Write a project email",
        task_category="writing",
        prompt_analysis={"id": "analysis-1"},
        analysis_score=60,
        analysis_gaps=[],
        relevant_answers=[],
        project_memory=[],
        requirements=[],
        constraints=[],
        context_package={"allowed_source_ids": ["memory-1"]},
    )


class Provider:
    name = "test"
    model = "test-model"

    def generate_prompt(self, payload):
        return PromptGenerationResult(
            optimized_prompt="Write a clear project email.",
            task_summary="Write an email.",
            assumptions=[],
            incorporated_context=[],
            incorporated_requirements=[],
            output_format="Email",
            quality_notes=["Clear structure"],
            warnings=[],
            generation_metadata={},
        )


def test_structured_generation_validates_and_preserves_provider_metadata():
    outcome = PromptGenerator(Provider()).generate(input_data())
    assert outcome.result.optimized_prompt.startswith("Write")
    assert outcome.provider == "test"
    assert outcome.fallback_used is False


def test_generation_rejects_unknown_context_reference():
    class BadProvider(Provider):
        def generate_prompt(self, payload):
            result = super().generate_prompt(payload)
            result.incorporated_context = [str(uuid4())]
            return result

    with pytest.raises(ValueError, match="context reference"):
        PromptGenerator(BadProvider()).generate(input_data())


def test_generation_mode_is_explicit():
    value = input_data()
    value.mode = "minimal"
    assert PromptGenerator(Provider()).generate(value).result.optimized_prompt
    value.mode = "unsupported"
    with pytest.raises(ValueError, match="Unsupported"):
        PromptGenerator(Provider()).generate(value)
