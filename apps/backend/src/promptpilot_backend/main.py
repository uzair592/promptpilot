from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import Base, engine
from .errors import error_response
from .routes import router

app = FastAPI(title="PromptPilot API", version="0.1.0")


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
