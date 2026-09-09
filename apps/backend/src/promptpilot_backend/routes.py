from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import create_session, hash_password, normalize_email, revoke_session, verify_password
from .config import get_settings
from .db import get_db
from .dependencies import current_user
from .models import User
from .schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest, response: Response, db: Session = Depends(get_db)
) -> AuthResponse:
    normalized = normalize_email(str(payload.email))
    if db.scalar(select(User).where(User.normalized_email == normalized)):
        raise HTTPException(status_code=409, detail="An account with these details already exists")
    user = User(
        email=str(payload.email),
        normalized_email=normalized,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An account with these details already exists"
        ) from None
    db.refresh(user)
    set_session_cookie(response, create_session(db, user))
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest, response: Response, db: Session = Depends(get_db)
) -> AuthResponse:
    user = db.scalar(
        select(User).where(User.normalized_email == normalize_email(str(payload.email)))
    )
    if (
        user is None
        or not verify_password(payload.password, user.password_hash)
        or user.status != "active"
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user.last_login_at = datetime.now(UTC)
    db.commit()
    set_session_cookie(response, create_session(db, user))
    return AuthResponse(user=UserResponse.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    revoke_session(db, request.cookies.get(get_settings().session_cookie_name))
    response.delete_cookie(get_settings().session_cookie_name, path="/")


@router.get("/me", response_model=AuthResponse)
def me(user: User = Depends(current_user)) -> AuthResponse:
    return AuthResponse(user=UserResponse.model_validate(user))


@router.get("/protected-check")
def protected_check(user: User = Depends(current_user)) -> dict[str, str]:
    return {"message": "Authenticated", "user_id": str(user.id)}
