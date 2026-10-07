from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from .analysis_routes import router as analysis_router
from .config import get_settings
from .context_routes import router as context_router
from .conversation_routes import conversation_router
from .conversation_routes import project_router as conversation_project_router
from .db import Base, engine
from .document_routes import router as document_router
from .errors import error_response
from .evaluation_routes import router as evaluation_router
from .execution_routes import router as execution_router
from .memory_routes import router as memory_router
from .project_routes import router as project_router
from .prompt_routes import router as prompt_router
from .question_routes import router as question_router
from .routes import router


def migration_config_path() -> Path:
    candidates = (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Alembic configuration is unavailable; run from the backend root")


def prepare_database_and_storage() -> None:
    settings = get_settings()
    settings.validate()
    settings.ensure_storage_directory()
    if settings.app_env in {"development", "test"}:
        Base.metadata.create_all(bind=engine)
        return

    inspector = inspect(engine)
    required_tables = set(Base.metadata.tables)
    missing_tables = required_tables.difference(inspector.get_table_names())
    if not inspector.has_table("alembic_version") or missing_tables:
        raise RuntimeError(
            "Database schema is not current; run Alembic migrations before startup"
        )
    with engine.connect() as connection:
        revisions: set[str] = set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    migration_config = AlembicConfig(str(migration_config_path()))
    expected_revisions = set(ScriptDirectory.from_config(migration_config).get_heads())
    if not expected_revisions or revisions != expected_revisions:
        raise RuntimeError(
            "Database migrations are not current; run Alembic migrations before startup"
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    prepare_database_and_storage()
    yield


app = FastAPI(title="PromptPilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Request-Id"],
)


@app.middleware("http")
async def disable_api_caching(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readiness() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = (
        "AUTHENTICATION_ERROR"
        if exc.status_code == 401
        else "RATE_LIMITED"
        if exc.status_code == 429
        else "REQUEST_ERROR"
    )
    response = error_response(exc.status_code, code, message, request)
    if exc.headers:
        for name, value in exc.headers.items():
            response.headers[name] = value
    return response


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
    return error_response(422, "VALIDATION_ERROR", "The request could not be validated", request)


app.include_router(router)
app.include_router(project_router)
app.include_router(conversation_project_router)
app.include_router(conversation_router)
app.include_router(analysis_router)
app.include_router(question_router)
app.include_router(memory_router)
app.include_router(document_router)
app.include_router(context_router)
app.include_router(prompt_router)
app.include_router(execution_router)
app.include_router(evaluation_router)
