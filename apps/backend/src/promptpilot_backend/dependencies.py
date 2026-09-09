from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .auth import get_user_by_session
from .config import get_settings
from .db import get_db
from .models import User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_user_by_session(db, request.cookies.get(get_settings().session_cookie_name))
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def project_access_placeholder(user: User = Depends(current_user)) -> User:
    return user
