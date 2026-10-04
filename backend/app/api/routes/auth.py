"""Registration, sign-in and "who am I".

The endpoints are thin on purpose: validate, call, return. Password hashing and
token signing live in core/security.py, user lookups in the repository.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DbSession
from app.core.errors import Conflict, Unauthorized
from app.core.security import create_access_token, hash_password, verify_password
from app.db.repositories import users as user_repo
from app.schemas.auth import RegisterRequest, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: DbSession) -> UserOut:
    if user_repo.get_by_email(session, payload.email):
        raise Conflict(
            "An account with this email already exists. Sign in instead.",
            code="EMAIL_ALREADY_REGISTERED",
        )

    user = user_repo.create_user(
        session,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenOut)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession
) -> TokenOut:
    """OAuth2 password flow: a form with `username` and `password`.

    We use the email as the username. The same message is returned whether the
    email is unknown or the password is wrong, so the endpoint cannot be used to
    discover which addresses have accounts.
    """
    user = user_repo.get_by_email(session, form.username)
    if user is None or not verify_password(form.password, user.password_hash):
        raise Unauthorized("Email or password is incorrect.", code="INVALID_CREDENTIALS")

    token, expires_in = create_access_token(str(user.id))
    return TokenOut(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
