"""Application settings.

Every value that differs between machines or environments lives here and is read
from environment variables (or a .env file). Nothing is hard-coded and no secret
is ever committed.

pydantic-settings validates the values at start-up, so a typo in .env fails
immediately with a clear message instead of surfacing as a strange error later.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Application ---
    app_env: str = "development"
    log_level: str = "INFO"
    # NoDecode: pydantic-settings treats a list field as "complex" and tries to
    # JSON-decode the raw .env value *before* any validator runs, so a plain
    # CORS_ORIGINS=http://localhost:5173 fails with a SettingsError. NoDecode
    # hands the raw string to _split_origins below instead.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Database ---
    database_url: str = "postgresql+psycopg://retailpulse:change-me@localhost:5432/retailpulse"
    test_database_url: str | None = None

    # --- Security ---
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    min_password_length: int = 12

    # --- Uploads and processing ---
    upload_dir: Path = BACKEND_ROOT.parent / "data" / "uploads"
    max_upload_mb: int = 200
    max_columns: int = 200
    min_clean_rows: int = 100
    preview_rows: int = 5000  # rows read for the column profile shown in the wizard

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept either form in .env:

            CORS_ORIGINS=http://a,http://b        (comma-separated)
            CORS_ORIGINS=["http://a","http://b"]  (JSON)
        """
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def require_jwt_secret(self) -> str:
        """Fail loudly rather than signing tokens with an empty key."""
        if not self.jwt_secret_key:
            raise RuntimeError(
                "JWT_SECRET_KEY is not set. Generate one with:\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
                "and put it in backend/.env"
            )
        return self.jwt_secret_key


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached; every caller gets the same object."""
    return Settings()