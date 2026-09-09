from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Answer, InformationGap, Question, QuestionSession
from .question_generator import DeterministicQuestionGenerator

SEVERITY_WEIGHT = {"critical": 300, "important": 200, "optional": 100}


def next_question(db: Session, session: QuestionSession) -> Question | None:
    existing_gap_ids = select(Question.gap_id).where(
        Question.session_id == session.id,
        Question.status.in_(("answered", "skipped", "dismissed", "obsolete")),
    )
    gaps = list(
        db.scalars(
            select(InformationGap).where(
                InformationGap.analysis_id == session.analysis_id,
                InformationGap.status.in_(("unresolved", "partially_resolved")),
                InformationGap.id.not_in(existing_gap_ids),
            )
        ).all()
    )
    if not gaps:
        session.status = "completed"
        session.stop_reason = "no_unresolved_gaps"
        db.commit()
        return None
    gap = max(gaps, key=lambda item: (SEVERITY_WEIGHT.get(item.severity, 0), item.importance))
    priority = SEVERITY_WEIGHT.get(gap.severity, 0)
    generated = DeterministicQuestionGenerator().generate(
        gap.question_target, str(gap.id), priority
    )
    question = Question(
        session_id=session.id,
        gap_id=gap.id,
        text=generated.question_text,
        question_type=generated.question_type,
        priority=generated.priority,
        status="presented",
        source="fallback",
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def answer_question(db: Session, question: Question, content: str) -> Answer:
    answer = Answer(question_id=question.id, content=content.strip(), source="user")
    db.add(answer)
    question.status = "answered"
    question.answered_at = datetime.now(UTC)
    gap = db.get(InformationGap, question.gap_id)
    if gap:
        gap.status = "partially_resolved"
    db.commit()
    db.refresh(answer)
    return answer
