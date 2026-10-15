"""Forecast run persistence (architecture §13, run persistence).

A results table in a report is a claim. These two tables are what makes it a
*checkable* claim: the protocol that produced it, the library versions it ran
against, the seed, the per-fold numbers, and the moment the hold-out was
scored. Six months later, or in a viva, the question "how did you get 14.2%?"
has an answer that does not depend on anyone's memory.

Two tables rather than one blob:

* **`forecast_runs`** - one row per experiment. Holds the declared config, the
  realised protocol, the summary, the significance result and the environment.
* **`forecast_results`** - one row per model per fold. The metrics are stored
  both as typed columns (so SQL can sort and aggregate) and as JSONB (so the
  observation counts that `metrics.Metric` carries are not lost). A WAPE of
  14.2 computed on 38 of 52 weeks is a different number from one computed on
  all 52, and the typed column alone cannot tell them apart.

`fold = 0` means the locked hold-out. Folds 1..k are cross-validation. That
convention is enforced in the service, not just documented, because the whole
value of the hold-out is that it is distinguishable from the folds used for
selection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# The hold-out is fold 0. Named rather than written as a bare 0 in five places.
HOLDOUT_FOLD = 0

RUN_STATUSES = ("queued", "running", "ready", "failed")


class ForecastRun(Base):
    """One forecasting experiment over one series."""

    __tablename__ = "forecast_runs"
    __table_args__ = (
        # The dashboard asks "the most recent ready run for this dataset and
        # this series", which is exactly this index.
        Index("ix_forecast_runs_dataset_id_series_key_created_at",
              "dataset_id", "series_key", "created_at"),
        Index("ix_forecast_runs_dataset_id_status", "dataset_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")

    # What was forecast. `series_key` is NULL for the whole-business total and
    # a product code for a single SKU, which keeps one table for both.
    series_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="total")
    series_key: Mapped[str | None] = mapped_column(String(100))
    granularity: Mapped[str] = mapped_column(String(10), nullable=False, default="week")
    value_column: Mapped[str] = mapped_column(String(30), nullable=False, default="net_revenue")

    # The protocol, declared before the run.
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    folds: Mapped[int] = mapped_column(Integer, nullable=False)
    season_length: Mapped[int] = mapped_column(Integer, nullable=False, default=52)
    window_style: Mapped[str] = mapped_column(String(20), nullable=False, default="expanding")
    primary_metric: Mapped[str] = mapped_column(String(20), nullable=False, default="WAPE")

    # SHA-256 of the canonical config. Two runs with the same hash ran the same
    # experiment; a different hash means something was changed, which is the
    # question anyone auditing the results will ask first.
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Everything produced by the run.
    protocol: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    significance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    combination: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    series_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # The selected model's interval around the hold-out forecast, sized from
    # its cross-validation errors, with the coverage it actually achieved.
    intervals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Permutation importance from the global tree model, and whether it agrees
    # with the Phase 4 mutual-information ranking (§12.7).
    feature_importance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # The selection decision, recorded *before* the hold-out was scored. The
    # difference between "we selected on CV and confirmed" and "we scored
    # everything and reported the best" lives in these three columns.
    selected_model: Mapped[str | None] = mapped_column(String(50))
    holdout_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    holdout_warning: Mapped[str | None] = mapped_column(Text)

    # Reproducibility. NFR-03 asks for the same inputs to give the same
    # outputs; that only means anything alongside the versions it held for.
    library_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    random_seed: Mapped[int | None] = mapped_column(Integer)
    pipeline_version: Mapped[str | None] = mapped_column(String(20))

    error: Mapped[str | None] = mapped_column(Text)
    computed_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list["ForecastModelResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class ForecastModelResult(Base):
    """One model's score on one fold. `fold = 0` is the locked hold-out."""

    __tablename__ = "forecast_results"
    __table_args__ = (
        Index("ix_forecast_results_run_id_model", "run_id", "model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )

    model: Mapped[str] = mapped_column(String(50), nullable=False)
    fold: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    uses_exogenous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Typed columns for sorting and aggregating in SQL. Numeric rather than
    # float: these end up in a report, and binary floating point drift in a
    # published figure is avoidable.
    wape: Mapped[float | None] = mapped_column(Numeric(12, 4))
    mase: Mapped[float | None] = mapped_column(Numeric(12, 4))
    mae: Mapped[float | None] = mapped_column(Numeric(16, 4))
    rmse: Mapped[float | None] = mapped_column(Numeric(16, 4))
    mape: Mapped[float | None] = mapped_column(Numeric(12, 4))
    smape: Mapped[float | None] = mapped_column(Numeric(12, 4))
    bias: Mapped[float | None] = mapped_column(Numeric(16, 4))

    # The full Metric records, including how many observations each measure
    # actually used and how many it had to exclude.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Point forecast and actuals for this fold, so a chart can be redrawn and a
    # disputed number recomputed without re-running the experiment.
    forecast: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[ForecastRun] = relationship(back_populates="results")
