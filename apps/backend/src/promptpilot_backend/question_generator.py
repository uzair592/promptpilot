from typing import Protocol

from pydantic import BaseModel, Field


class GeneratedQuestion(BaseModel):
    question_text: str = Field(min_length=3, max_length=500)
    question_type: str = "free_text"
    related_gap: str
    priority: int = Field(ge=0)
    rationale: str
    options: list[str] | None = None


class QuestionGenerator(Protocol):
    def generate(self, gap_target: str, gap_id: str, priority: int) -> GeneratedQuestion: ...


class QuestionProvider(Protocol):
    def generate_question(self, payload: dict[str, object]) -> object: ...


class ProviderQuestionGenerator:
    def __init__(self, provider: QuestionProvider) -> None:
        self.provider = provider

    def generate(self, gap_target: str, gap_id: str, priority: int) -> GeneratedQuestion:
        result = self.provider.generate_question(
            {"gap_target": gap_target, "gap_id": gap_id, "priority": priority}
        )
        if not isinstance(result, GeneratedQuestion) or result.related_gap != gap_id:
            raise ValueError("Generated question did not target the selected gap")
        if result.question_type in {"single_choice", "multi_choice"} and not result.options:
            raise ValueError("Choice questions require options")
        if result.question_type == "free_text" and result.options:
            raise ValueError("Free-text questions cannot contain options")
        return result


class DeterministicQuestionGenerator:
    def generate(self, gap_target: str, gap_id: str, priority: int) -> GeneratedQuestion:
        return GeneratedQuestion(
            question_text=gap_target,
            related_gap=gap_id,
            priority=priority,
            rationale="Fallback question derived from the information gap.",
        )
