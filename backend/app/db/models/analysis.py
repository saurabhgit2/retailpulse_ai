"""The analysis cache (architecture §8.2).

Cheap aggregates - KPIs, trends, breakdowns - are fast enough in SQL to compute
every time. The expensive ones - statistics, feature analysis, series profiles,
seasonality - are cached here, keyed by everything that can change the answer:
the dataset, the kind of analysis, the filters and parameters, and the pipeline
version. Change any of those and you get a different row rather than a stale
one.

`computed_ms` is kept because it is the evidence for NFR-01: a claim that
analyses complete within a time budget needs measurements, not an assertion.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisResult(Base):
    """One cached analysis result."""

    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "analysis_type", "params_hash", "pipeline_version",
            name="uq_analysis_results_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # SHA-256 of the canonical JSON of filters and parameters: stable across
    # runs because the JSON is written with sorted keys.
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    computed_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
