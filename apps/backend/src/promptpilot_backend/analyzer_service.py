from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from .models import InformationGap, Message, PromptAnalysis, PromptAnalysisDimension

ANALYSIS_VERSION = "prompt-analyzer-v1"
THRESHOLDS = {"Poor": (0, 49), "Medium": (50, 79), "Good": (80, 100)}
DIMENSIONS = (
    "intent",
    "objective",
    "requirements",
    "context",
    "constraints",
    "output",
    "audience",
    "success_criteria",
    "ambiguity",
)


@dataclass(frozen=True)
class DimensionResult:
    key: str
    score: int | None
    status: str
    applicable: bool
    evidence: str | None
    explanation: str


def classify_task(text: str) -> str:
    lowered = text.lower()
    rules = {
        "software_development": ("build", "website", "app", "api", "code", "software"),
        "business_analysis": ("business", "market", "process", "stakeholder"),
        "data_analysis": ("data", "dataset", "分析", "dashboard", "csv"),
        "marketing": ("marketing", "campaign", "customer", "seo", "advertise"),
        "education": ("teach", "lesson", "course", "student", "learn"),
        "writing": ("write", "article", "essay", "blog", "story"),
        "research": ("research", "study", "literature", "investigate"),
    }
    return next(
        (category for category, words in rules.items() if any(word in lowered for word in words)),
        "general",
    )


def status_for(score: int) -> str:
    return next(label for label, (low, high) in THRESHOLDS.items() if low <= score <= high)


def analyze_message(
    db: Session, project_id: UUID, conversation_id: UUID, message: Message
) -> PromptAnalysis:
    text = message.content.strip()
    lowered = text.lower()
    category = classify_task(text)
    has_objective = any(
        token in lowered
        for token in ("build", "create", "analyze", "write", "design", "explain", "help")
    )
    has_constraints = any(
        token in lowered for token in ("must", "use ", "under ", "within ", "avoid", "format")
    )
    has_output = any(
        token in lowered for token in ("as a ", "format", "deliver", "return", "report", "document")
    )
    applicable_audience = (
        category not in {"software_development", "data_analysis"}
        or "user" in lowered
        or "audience" in lowered
    )
    dimensions = [
        DimensionResult(
            "intent",
            85 if has_objective else 35,
            "present" if has_objective else "missing",
            True,
            text if has_objective else None,
            "The request states an actionable intent."
            if has_objective
            else "The requested action is not clear enough to guide execution.",
        ),
        DimensionResult(
            "objective",
            80 if has_objective else 30,
            "present" if has_objective else "missing",
            True,
            None,
            "A target result is identifiable."
            if has_objective
            else "The desired result is not defined.",
        ),
        DimensionResult(
            "requirements",
            75 if len(text.split()) > 15 else 35,
            "present" if len(text.split()) > 15 else "missing",
            True,
            None,
            "The prompt provides some task detail."
            if len(text.split()) > 15
            else "Important features or requirements are not stated.",
        ),
        DimensionResult(
            "context",
            65 if len(text.split()) > 25 else 25,
            "present" if len(text.split()) > 25 else "missing",
            True,
            None,
            "Some working context is provided."
            if len(text.split()) > 25
            else "The existing system, source material, or background is missing.",
        ),
        DimensionResult(
            "constraints",
            70 if has_constraints else 35,
            "present" if has_constraints else "missing",
            True,
            None,
            "Relevant limitations are mentioned."
            if has_constraints
            else "No meaningful limitations or preferences are stated.",
        ),
        DimensionResult(
            "output",
            80 if has_output else 40,
            "present" if has_output else "missing",
            True,
            None,
            "The expected output form is indicated."
            if has_output
            else "The desired output format is unclear.",
        ),
        DimensionResult(
            "audience",
            70 if applicable_audience else None,
            "present" if applicable_audience else "not_applicable",
            applicable_audience,
            None,
            "The target audience is sufficiently indicated."
            if applicable_audience
            else "Audience is not required for this task category.",
        ),
        DimensionResult(
            "success_criteria",
            65
            if any(x in lowered for x in ("success", "complete", "quality", "acceptance"))
            else 30,
            "present"
            if any(x in lowered for x in ("success", "complete", "quality", "acceptance"))
            else "missing",
            True,
            None,
            "A quality bar is mentioned."
            if any(x in lowered for x in ("success", "complete", "quality", "acceptance"))
            else "There is no stated definition of a successful result.",
        ),
        DimensionResult(
            "ambiguity",
            75 if len(text.split()) > 20 else 45,
            "clear" if len(text.split()) > 20 else "uncertain",
            True,
            None,
            "The request has limited unresolved ambiguity."
            if len(text.split()) > 20
            else "Short wording leaves important interpretation choices unresolved.",
        ),
    ]
    applicable = [item for item in dimensions if item.applicable and item.score is not None]
    score = round(sum(item.score or 0 for item in applicable) / len(applicable))
    gaps: list[dict[str, str]] = []
    if not has_constraints and category == "software_development":
        gaps.append(
            {
                "dimension": "constraints",
                "title": "Technology and constraints",
                "description": "The implementation technologies, limitations, or deployment expectations are not specified.",
                "severity": "critical",
                "importance": "critical",
                "question_target": "Which technologies, constraints, and deployment requirements should be used?",
            }
        )
    if not has_output:
        gaps.append(
            {
                "dimension": "output",
                "title": "Expected output",
                "description": "The form of the result is not specified.",
                "severity": "important",
                "importance": "important",
                "question_target": "What should the completed result look like?",
            }
        )
    if not has_constraints and category != "software_development":
        gaps.append(
            {
                "dimension": "constraints",
                "title": "Constraints",
                "description": "Relevant limits or preferences have not been provided.",
                "severity": "optional",
                "importance": "optional",
                "question_target": "Are there important constraints, limits, or preferences?",
            }
        )
    analysis = PromptAnalysis(
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message.id,
        task_category=category,
        overall_score=score,
        status=status_for(score),
        analysis_version=ANALYSIS_VERSION,
    )
    analysis.dimensions = [PromptAnalysisDimension(**item.__dict__) for item in dimensions]
    analysis.gaps = [InformationGap(**gap) for gap in gaps]
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis
