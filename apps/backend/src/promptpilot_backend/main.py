from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

app = FastAPI(title="PromptPilot API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-Id"],
)


@app.on_event("startup")
def create_dev_schema() -> None:
    # Development convenience; production uses the checked-in migration.
    Base.metadata.create_all(bind=engine)


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = "AUTHENTICATION_ERROR" if exc.status_code == 401 else "REQUEST_ERROR"
    return error_response(exc.status_code, code, message, request)


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
