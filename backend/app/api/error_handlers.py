"""Turning exceptions into the one error shape the API promises.

    {"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}

Three rules:
* the message is written for the person reading the screen;
* the code is stable, so the frontend can branch on it;
* internal detail (stack traces, SQL, file paths) never leaves the server.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import RetailPulseError
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


def error_response(status_code: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id_var.get(),
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RetailPulseError)
    def handle_app_error(_: Request, error: RetailPulseError) -> JSONResponse:
        # Expected, deliberate failures: 4xx with a helpful message.
        return error_response(error.status_code, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    def handle_request_validation(_: Request, error: RequestValidationError) -> JSONResponse:
        """FastAPI's own validation errors, reshaped into our envelope.

        Without this the frontend would have to understand two error formats.
        """
        first = error.errors()[0] if error.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", [])[1:]) or "request"
        return error_response(
            422,
            "VALIDATION_ERROR",
            f"{location}: {first.get('msg', 'invalid value')}",
            details=[
                {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")}
                for e in error.errors()
            ],
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_exception(_: Request, error: StarletteHTTPException) -> JSONResponse:
        codes = {401: "NOT_AUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                 405: "METHOD_NOT_ALLOWED", 413: "FILE_TOO_LARGE"}
        return error_response(
            error.status_code,
            codes.get(error.status_code, f"HTTP_{error.status_code}"),
            str(error.detail),
        )

    @app.exception_handler(Exception)
    def handle_unexpected(_: Request, error: Exception) -> JSONResponse:
        # The details go to the log; the user gets a request ID to quote.
        logger.exception("Unhandled error: %s", error)
        return error_response(
            500,
            "INTERNAL_ERROR",
            "Something went wrong on the server. Quote the request ID if you report this.",
        )
