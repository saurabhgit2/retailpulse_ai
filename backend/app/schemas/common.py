"""Shapes shared by several endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(examples=["MISSING_REQUIRED_FIELD"])
    message: str = Field(examples=["Map these before processing: occurred_at."])
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Every error the API returns looks like this, whatever went wrong."""

    error: ErrorBody


class Message(BaseModel):
    message: str
