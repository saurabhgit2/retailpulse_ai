"""The application's error types.

Every failure the API reports deliberately is one of these. They carry an HTTP
status, a machine-readable code and a message written for the person reading the
screen. api/error_handlers.py turns them into the JSON envelope:

    {"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}

Raising these from services keeps HTTP concerns out of the business logic: the
service says "this dataset is not ready", and the API layer decides that means 409.
"""

from __future__ import annotations

from typing import Any


class RetailPulseError(Exception):
    """Base class. Never raised directly."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationFailed(RetailPulseError):
    """The request was understood but the data in it is not usable."""

    status_code = 422
    code = "VALIDATION_ERROR"

    def __init__(self, message: str, *, code: str | None = None, details: Any | None = None):
        super().__init__(message, details=details)
        if code:
            self.code = code


class NotFound(RetailPulseError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(RetailPulseError):
    """The resource exists but is in the wrong state for this action."""

    status_code = 409
    code = "CONFLICT"

    def __init__(self, message: str, *, code: str | None = None, details: Any | None = None):
        super().__init__(message, details=details)
        if code:
            self.code = code


class Unauthorized(RetailPulseError):
    status_code = 401
    code = "NOT_AUTHENTICATED"

    def __init__(self, message: str, *, code: str | None = None, details: Any | None = None):
        super().__init__(message, details=details)
        if code:
            self.code = code


class PayloadTooLarge(RetailPulseError):
    status_code = 413
    code = "FILE_TOO_LARGE"


class UnsupportedFile(RetailPulseError):
    status_code = 415
    code = "UNSUPPORTED_FILE"
