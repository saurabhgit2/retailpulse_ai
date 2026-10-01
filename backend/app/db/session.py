"""Database engine and session factory.

One engine per process holds a pool of connections. One Session per request acts
as a unit of work: it collects changes and writes them in a single transaction
when the request ends.

Sessions are *not* thread-safe, which is exactly why each request gets its own
through the get_session dependency in app/api/deps.py.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # check a pooled connection is alive before handing it out
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope() -> Iterator[Session]:
    """Session for code outside a request (background tasks, scripts).

    Commits when the block finishes, rolls back if it raises, and always closes.
    """
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
