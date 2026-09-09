from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, model_validator


@dataclass(frozen=True)
class QuestionGenerationInput:
    original_prompt: str
    task_category: str
    gap_id: str
    gap_target: str
    severity: str
    importance: str
    priority: int
    memory: tuple[dict[str, str], ...] = ()
    previous_questions: tuple[str, ...] = ()
    previous_answers: tuple[str, ...] = ()


class GeneratedQuestion(BaseModel):
    question_text: str = Field(min_length=3, max_length=500)
    question_type: str = "free_text"
    related_gap: str
    priority: int = Field(ge=0)
    rationale: str
    options: list[str] | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "GeneratedQuestion":
        if self.question_type not in {"free_text", "single_choice", "multi_choice"}:
            raise ValueError("Unsupported question type")
        if self.question_type != "free_text" and not self.options:
            raise ValueError("Choice questions require options")
        if self.question_type == "free_text" and self.options:
            raise ValueError("Free-text questions cannot contain options")
        return self


class QuestionGenerator(Protocol):
    def generate(self, request: QuestionGenerationInput) -> GeneratedQuestion: ...


class QuestionProvider(Protocol):
    def generate_question(self, payload: dict[str, object]) -> object: ...


class ProviderQuestionGenerator:
    def __init__(self, provider: QuestionProvider) -> None:
        self.provider = provider

    def generate(self, request: QuestionGenerationInput) -> GeneratedQuestion:
        result = self.provider.generate_question(
            {
                "original_prompt": request.original_prompt,
                "task_category": request.task_category,
                "gap_id": request.gap_id,
                "gap_target": request.gap_target,
                "severity": request.severity,
                "importance": request.importance,
                "memory": list(request.memory),
                "previous_questions": list(request.previous_questions),
                "previous_answers": list(request.previous_answers),
            }
        )
        if not isinstance(result, GeneratedQuestion) or result.related_gap != request.gap_id:
            raise ValueError("Generated question did not target the selected gap")
        return result


class DeterministicQuestionGenerator:
    def generate(self, request: QuestionGenerationInput) -> GeneratedQuestion:
        return GeneratedQuestion(
            question_text=request.gap_target,
            related_gap=request.gap_id,
            priority=request.priority,
            rationale="Fallback question derived from the information gap.",
        )
