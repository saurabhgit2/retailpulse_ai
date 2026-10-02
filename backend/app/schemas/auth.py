from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings

MIN_PASSWORD_LENGTH = get_settings().min_password_length


class RegisterRequest(BaseModel):
    email: EmailStr
    # Pydantic enforces the length before the endpoint runs, so the rule lives
    # in one place and appears in the generated API documentation.
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    full_name: str | None = Field(default=None, max_length=120)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None = None

    model_config = {"from_attributes": True}  # build from the ORM object


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
