"""Password hashing and access tokens.

Passwords are hashed with Argon2id, the current recommendation for password
storage. Hashing is one-way on purpose: the server can check a password but can
never recover it, so a database leak does not hand over anyone's password.

The access token is a JWT: three base64url parts (header.payload.signature).
Anyone can *read* the payload - it is not encrypted - but only the holder of
JWT_SECRET_KEY can produce a valid signature, so the payload cannot be forged.
Never put anything secret in it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(subject: str) -> tuple[str, int]:
    """Return (token, seconds until it expires)."""
    settings = get_settings()
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": subject,                                   # who the token is for
        "iat": int(now.timestamp()),                      # issued at
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),  # expires at
    }
    token = jwt.encode(payload, settings.require_jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Return the payload, or None if the token is invalid or expired."""
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.require_jwt_secret(), algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
