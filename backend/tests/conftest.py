"""Shared test fixtures.

Two kinds of test live here:

* **unit tests** exercise the pure preprocessing code with small DataFrames.
  They need no database and run in milliseconds;
* **API and integration tests** need a real PostgreSQL test database. If one is
  not reachable they are skipped with a clear message rather than failing, so
  `pytest` is always runnable.

Create the test database once:
    docker compose exec db createdb -U retailpulse retailpulse_test
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")

from app.core.config import get_settings  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def settings():
    return get_settings()


# --- Fixtures for the pure pipeline -----------------------------------------

@pytest.fixture
def mapping() -> dict[str, str | None]:
    """The mapping the detector produces for an Online Retail II style file."""
    return {
        "invoice_id": "Invoice",
        "occurred_at": "InvoiceDate",
        "product_code": "StockCode",
        "product_name": "Description",
        "quantity": "Quantity",
        "unit_price": "Price",
        "customer_id": "Customer ID",
        "region": "Country",
        "revenue": None,
        "category": None,
        "discount": None,
    }


@pytest.fixture
def raw_frame() -> pd.DataFrame:
    """Eight rows, each triggering one cleaning step. Hand-checked expectations."""
    header = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price",
              "Customer ID", "Country"]
    rows = [
        ["1001", "85123A", "WHITE MUG", "2", "2024-01-01 09:00:00", "3.00", "501", "United Kingdom"],
        ["1001", "85123A", "WHITE MUG", "2", "2024-01-01 09:00:00", "3.00", "501", "United Kingdom"],
        ["1002", "POST", "POSTAGE", "1", "2024-01-02 09:00:00", "18.00", "502", "United Kingdom"],
        ["1003", "22423", "CAKE STAND", "1", "2024-01-03 09:00:00", "0.00", "503", "France"],
        ["C1004", "85123A", "WHITE MUG", "-1", "2024-01-04 09:00:00", "3.00", "501", "United Kingdom"],
        ["1005", "22423", "CAKE STAND", "4", "not a date", "2.50", "", "France"],
        ["1006", "22423", "cake stand", "4", "2024-01-05 09:00:00", "2.50", "", "France"],
        ["1007", "22423", "CAKE STAND", "3", "2024-01-08 09:00:00", "2.50", "504.0", "France"],
    ]
    return pd.DataFrame(rows, columns=header).astype("string")


# --- Database-backed fixtures -----------------------------------------------

def _test_database_url() -> str | None:
    settings = get_settings()
    return settings.test_database_url


@pytest.fixture(scope="session")
def db_engine():
    """Engine for the test database, or skip everything that needs one."""
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; database tests skipped.")

    from sqlalchemy import create_engine, text

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Test database is not reachable ({error.__class__.__name__}); skipped.")

    from app.db.base import Base
    from app.db import models  # noqa: F401 - registers the models

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """A session wrapped in a transaction that is rolled back after each test,
    so tests cannot affect each other."""
    from sqlalchemy.orm import Session

    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


class _SharedSession:
    """The test session, lent to code that expects to own its own.

    The background job closes the session it opened. Here that session belongs
    to the test, and closing it would end the transaction the next assertion
    reads from - so `close` is the one method that does nothing. Everything
    else is passed straight through.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:
        pass


@pytest.fixture
def client(db_session, tmp_path, monkeypatch):
    """A TestClient whose database session is the rolled-back test session."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import create_app
    from app.services import processing_service

    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path / "uploads", raising=False)

    # The background job opens its own session in production. In tests it must
    # join this transaction, or it queries the development database, finds no
    # such dataset, and silently skips - which is exactly what an earlier
    # version of this file did.
    monkeypatch.setattr(
        processing_service, "_open_session", lambda: _SharedSession(db_session)
    )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def registered_client(client):
    """A client that is already signed in, plus the account's details."""
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    password = "a long test passphrase"
    client.post("/api/v1/auth/register", json={"email": email, "password": password,
                                               "full_name": "Test User"})
    token = client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    ).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client, email, password