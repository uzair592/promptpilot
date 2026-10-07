from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import AuthRateLimitCounter

WINDOW = timedelta(minutes=15)
MAX_ATTEMPTS = 20


def enforce_auth_rate_limit(db: Session, normalized_email: str) -> None:
    dialect = db.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Authentication throttling requires PostgreSQL or SQLite")

    now = datetime.now(UTC)
    cutoff = now - WINDOW
    key = sha256(normalized_email.casefold().encode("utf-8")).hexdigest()
    table = AuthRateLimitCounter.__table__
    reset_window = table.c.window_started_at < cutoff
    db.execute(delete(AuthRateLimitCounter).where(reset_window))
    updates = {
        "window_started_at": case(
            (reset_window, now), else_=table.c.window_started_at
        ),
        "request_count": case(
            (reset_window, 1), else_=table.c.request_count + 1
        ),
    }
    if dialect == "postgresql":
        request_count: int = int(
            db.execute(
                postgres_insert(AuthRateLimitCounter)
                .values(key=key, window_started_at=now, request_count=1)
                .on_conflict_do_update(index_elements=[table.c.key], set_=updates)
                .returning(table.c.request_count)
            ).scalar_one()
        )
    else:
        request_count = int(
            db.execute(
                sqlite_insert(AuthRateLimitCounter)
                .values(key=key, window_started_at=now, request_count=1)
                .on_conflict_do_update(index_elements=[table.c.key], set_=updates)
                .returning(table.c.request_count)
            ).scalar_one()
        )
    db.commit()
    if request_count > MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts. Try again later.",
            headers={"Retry-After": str(int(WINDOW.total_seconds()))},
        )
