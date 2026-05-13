from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings


class TheCeeError(Exception):
    def __init__(self, code: str, message: str, detail: str = "", status: int = 400):
        self.code = code
        self.message = message
        self.detail = detail
        self.status = status


async def thecee_error_handler(_request: Request, exc: TheCeeError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, RequestValidationError):
        detail = (
            exc.errors() if settings.ENVIRONMENT.lower() != "production" else {}
        )
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "Invalid request body"
                if settings.ENVIRONMENT.lower() == "production"
                else "Invalid request",
                "detail": detail,
            },
        )
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "detail": str(exc.detail),
            },
        )
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "detail": str(exc.detail),
            },
        )
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Something went wrong. Our team has been notified.",
            "detail": "",
        },
    )
