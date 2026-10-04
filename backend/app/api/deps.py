"""Dependencies: the pieces FastAPI injects into endpoints.

A dependency is just a function. FastAPI calls it before the endpoint, passes
the result in, and (for generators) runs the cleanup afterwards. That is how a
database session is opened and closed around every request, and how a route
says "this needs a signed-in user" in its signature rather than in its body.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Path
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import NotFound, Unauthorized
from app.core.security import decode_access_token
from app.db.models.dataset import Dataset
from app.db.models.user import User
from app.db.repositories import users as user_repo
from app.db.session import SessionFactory
from app.services import dataset_service

# tokenUrl only tells the docs page where to get a token; it does not create a route.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_db() -> Iterator[Session]:
    """One session per request: commit if the endpoint returns, roll back if it raises."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_current_user(
    session: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    if not token:
        raise Unauthorized("Sign in to continue.")

    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise Unauthorized("Your session has expired. Sign in again.")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError as error:
        raise Unauthorized("Your session has expired. Sign in again.") from error

    user = user_repo.get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Your session has expired. Sign in again.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_owned_dataset(
    session: DbSession, user: CurrentUser, dataset_id: Annotated[uuid.UUID, Path()]
) -> Dataset:
    """Load a dataset and prove it belongs to the caller, in one dependency.

    Every dataset route uses this, so the ownership check cannot be forgotten
    on a new endpoint.
    """
    try:
        return dataset_service.get_owned_or_404(session, dataset_id, user.id)
    except NotFound:
        raise


OwnedDataset = Annotated[Dataset, Depends(get_owned_dataset)]
