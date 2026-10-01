from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DATASET_STATUSES = ("awaiting_mapping", "processing", "ready", "failed")


class Dataset(Base):
    """One uploaded file and everything known about it.

    Why JSONB for the profile, mapping, options, capabilities and quality report:
    each is written once, read whole, and never filtered on an inner field. A
    table per document would add half a dozen tables and several joins for no
    query benefit. Their *shape* is still validated - by Pydantic, on the way in
    and out (architecture ADR-08).
    """

    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_mapping', 'processing', 'ready', 'failed')",
            name="dataset_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # The user declares this at upload. It makes every screen able to label
    # invented data, so synthetic results are never reported as real findings.
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="awaiting_mapping")
    status_message: Mapped[str | None] = mapped_column(String(500))

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Server-generated path. The user's filename is never used on disk.
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    profile: Mapped[dict | None] = mapped_column(JSONB)          # detected columns + suggestions
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)   # confirmed by the user
    cleaning_options: Mapped[dict | None] = mapped_column(JSONB)
    capabilities: Mapped[list | None] = mapped_column(JSONB)
    quality_report: Mapped[dict | None] = mapped_column(JSONB)

    pipeline_version: Mapped[str | None] = mapped_column(String(20))
    clean_data_sha256: Mapped[str | None] = mapped_column(String(64))  # reproducibility check
    row_count_raw: Mapped[int | None] = mapped_column(Integer)
    row_count_clean: Mapped[int | None] = mapped_column(Integer)
    date_min: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    date_max: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    currency: Mapped[str | None] = mapped_column(String(3))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
