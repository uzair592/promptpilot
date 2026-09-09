from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Answer, InformationGap, Question, QuestionSession

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
                InformationGap.status == "unresolved",
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
    question = Question(
        session_id=session.id,
        gap_id=gap.id,
        text=gap.question_target,
        question_type="free_text",
        priority=SEVERITY_WEIGHT.get(gap.severity, 0),
        status="presented",
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
        gap.status = "resolved"
    db.commit()
    db.refresh(answer)
    return answer
