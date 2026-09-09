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


class DeterministicQuestionGenerator:
    def generate(self, gap_target: str, gap_id: str, priority: int) -> GeneratedQuestion:
        return GeneratedQuestion(
            question_text=gap_target,
            related_gap=gap_id,
            priority=priority,
            rationale="Fallback question derived from the information gap.",
        )
