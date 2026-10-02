from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import User


def get_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.strip().lower()))


def get_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def create_user(session: Session, *, email: str, password_hash: str, full_name: str | None) -> User:
    user = User(email=email.strip().lower(), password_hash=password_hash, full_name=full_name)
    session.add(user)
    session.flush()
    return user
