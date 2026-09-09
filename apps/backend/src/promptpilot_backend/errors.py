from fastapi import Request
from fastapi.responses import JSONResponse


def error_response(status_code: int, code: str, message: str, request: Request) -> JSONResponse:
    request_id = request.headers.get("x-request-id", "")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": {}, "request_id": request_id}
        },
    )
