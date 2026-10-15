"""Reading series for forecasting, and storing what came back.

The series queries deliberately **reuse `repositories/analytics.py`** rather
than writing their own SQL. That is not laziness: if the forecast trained on a
series built by different SQL from the one the dashboard draws, the two would
disagree sooner or later, and the disagreement would be invisible until someone
compared a chart with a number. One definition of "weekly revenue", used by
both.

The only thing added here is the shaping the forecasting core needs: a
`pd.Series` indexed by period for the local models, and a long panel for the
global tree model.

**Incomplete final periods are dropped.** Finding F9: the data ends part-way
through a week, and a partial week looks like a collapse in demand. Training a
model on it teaches a fall that never happened, and scoring against it makes
every model look bad in the same way.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.forecast import HOLDOUT_FOLD, ForecastModelResult, ForecastRun
from app.db.repositories import analytics as analytics_repo
from app.db.repositories.analytics import Filters

# Which column of the trend query is forecast. Net revenue by default: returns
# are real events that reduce what the business actually took, and a forecast
# of gross revenue overstates what a manager can plan against.
VALUE_COLUMNS = ("net_revenue", "gross_revenue", "units", "orders")

# A period is complete only if the data runs to its end. The dataset's stored
# `date_max` is what makes that decidable; see `_drop_incomplete_final`.


def weekly_series(
    session: Session,
    dataset_id: uuid.UUID,
    filters: Filters,
    *,
    granularity: str = "week",
    value_column: str = "net_revenue",
    drop_incomplete_final: bool = True,
    date_max: pd.Timestamp | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """The whole-business series to forecast, plus what was done to build it.

    Returns the series and a metadata block. The metadata is not decoration:
    it records how many periods were dropped as incomplete and how many gaps
    were filled, and both change what the numbers mean.
    """
    if value_column not in VALUE_COLUMNS:
        raise ValueError(
            f"Unknown value column '{value_column}'. Choose one of {list(VALUE_COLUMNS)}."
        )

    frame = analytics_repo.trend(session, dataset_id, filters, granularity)
    if frame.empty:
        return pd.Series(dtype="float64"), {
            "available": False,
            "reason": "No rows match these filters, so there is no series to forecast.",
        }

    frame = frame.copy()
    frame["period"] = pd.to_datetime(frame["period"])
    frame = frame.sort_values("period").set_index("period")
    series = pd.to_numeric(frame[value_column], errors="coerce").astype("float64")

    meta: dict[str, Any] = {
        "available": True,
        "granularity": granularity,
        "value_column": value_column,
        "periods_from_query": int(len(series)),
    }

    series, filled = _fill_period_gaps(series, granularity)
    meta["gaps_filled_with_zero"] = filled
    if filled:
        meta["gap_note"] = (
            f"{filled} period(s) had no rows at all and were filled with zero so the "
            f"series is evenly spaced, which every model here assumes. A zero from a "
            f"closure is not the same as zero demand - see the closure calendar in "
            f"the data-quality report before reading these as weak weeks."
        )

    if drop_incomplete_final:
        series, dropped = _drop_incomplete_final(series, granularity, date_max)
        meta["incomplete_final_periods_dropped"] = dropped
        if dropped:
            meta["incomplete_note"] = (
                f"Dropped {dropped} incomplete period(s) at the end. A partial period "
                f"looks like a collapse in demand and would be learned as one."
            )

    meta["periods"] = int(len(series))
    if len(series):
        meta["first_period"] = str(series.index[0].date())
        meta["last_period"] = str(series.index[-1].date())
    return series, meta


def product_panel(
    session: Session,
    dataset_id: uuid.UUID,
    filters: Filters,
    *,
    granularity: str = "week",
    value_column: str = "gross_revenue",
    limit_products: int = 100,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Long frame (series_id, period, value) for the global tree model.

    One SKU has at most about 105 weekly points. Pooling the top N by revenue
    gives thousands of training rows, which is the only way a tree ensemble is
    fittable here. The cut-off is returned in the metadata because "the top 100
    products" and "all products" support different claims.
    """
    frame = analytics_repo.product_periods(
        session, dataset_id, filters,
        granularity=granularity, limit_products=limit_products,
    )
    if frame.empty:
        return pd.DataFrame(columns=["series_id", "period", "value"]), {
            "available": False,
            "reason": "No product-period rows match these filters.",
        }

    panel = pd.DataFrame({
        "series_id": frame["product_code"].astype(str),
        "period": pd.to_datetime(frame["period"]),
        "value": pd.to_numeric(frame[value_column], errors="coerce").astype("float64"),
    }).dropna(subset=["period"])

    # Each series is reindexed onto the shared calendar: a SKU that sold in
    # weeks 1 and 5 has genuinely zero in weeks 2-4, and leaving those rows out
    # would make every lag feature wrong.
    calendar = pd.date_range(panel["period"].min(), panel["period"].max(),
                             freq=_frequency(granularity))
    filled = []
    for series_id, group in panel.groupby("series_id", observed=True):
        reindexed = (
            group.set_index("period")["value"]
            .reindex(calendar)
            .fillna(0.0)
            # Series.reset_index takes `name`, not `names` - `names` is a
            # DataFrame-only argument and raises on a Series in every pandas
            # version. The axis is renamed first so the index column lands as
            # "period".
            .rename_axis("period")
            .reset_index(name="value")
        )
        reindexed["series_id"] = series_id
        filled.append(reindexed)

    panel = pd.concat(filled, ignore_index=True)[["series_id", "period", "value"]]

    meta = {
        "available": True,
        "series": int(panel["series_id"].nunique()),
        "periods": int(len(calendar)),
        "rows": int(len(panel)),
        "value_column": value_column,
        "product_limit": limit_products,
        "selection_note": (
            f"The {limit_products} products with the highest revenue under these "
            f"filters. Results describe those products, not the whole catalogue; "
            f"the long tail is mostly single sales and its exclusion is a "
            f"survivorship bias worth stating (finding F5)."
        ),
    }
    return panel, meta


def _frequency(granularity: str) -> str:
    # W-MON labels weeks by Monday, matching PostgreSQL's date_trunc('week').
    return {"day": "D", "week": "W-MON", "month": "MS", "year": "YS"}[granularity]


def _fill_period_gaps(series: pd.Series, granularity: str) -> tuple[pd.Series, int]:
    """Put the series on an even grid. Returns the series and how many were added."""
    if len(series) < 2:
        return series, 0
    calendar = pd.date_range(series.index[0], series.index[-1], freq=_frequency(granularity))
    if len(calendar) == len(series):
        return series, 0
    filled = series.reindex(calendar).fillna(0.0)
    return filled, int(len(calendar) - len(series))


def _drop_incomplete_final(
    series: pd.Series, granularity: str, date_max: pd.Timestamp | None = None
) -> tuple[pd.Series, int]:
    """Remove trailing periods the data does not fully cover.

    `date_max` is the dataset's last transaction timestamp, which makes the
    rule exact: the final bucket starts at `series.index[-1]` and ends one
    period later, so it is complete only if the data runs to that end. Without
    it the only safe rule is to drop the last bucket always, which throws away
    a complete period whenever the data happens to end on a period boundary -
    so the caller is expected to pass it.
    """
    if len(series) < 2:
        return series, 0

    last_start = series.index[-1]
    period_end = _period_end(last_start, granularity)

    if date_max is None:
        # No information: drop one, and the metadata says the rule was applied
        # without a known end date.
        return series.iloc[:-1], 1

    # Complete when the data reaches the final *calendar day* of the period.
    # Comparing against `period_end` itself would be wrong: that is the first
    # instant of the next period, so a week with sales up to Sunday 23:00 would
    # be judged incomplete and thrown away.
    #
    # The conservative edge: a retailer closed on the last days of the period -
    # Online Retail II does not trade Saturdays - has its final period dropped
    # even though collection covered it. That costs at most one period out of
    # about a hundred, and erring this way protects the models from learning a
    # fall that never happened. The count is reported either way.
    last_day = (period_end - pd.Timedelta(days=1)).normalize()
    if pd.Timestamp(date_max).normalize() >= last_day:
        return series, 0
    return series.iloc[:-1], 1


def _period_end(start: pd.Timestamp, granularity: str) -> pd.Timestamp:
    """The first instant *after* the period beginning at `start`.

    Months and years are not a fixed number of days, so they use an offset
    rather than a timedelta; using 31 days for a month would mark February
    complete a few days early and incomplete for the rest of the year.
    """
    offsets = {
        "day": pd.DateOffset(days=1),
        "week": pd.DateOffset(weeks=1),
        "month": pd.DateOffset(months=1),
        "year": pd.DateOffset(years=1),
    }
    return pd.Timestamp(start) + offsets[granularity]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def create_run(session: Session, **fields: Any) -> ForecastRun:
    run = ForecastRun(**fields)
    session.add(run)
    session.flush()
    return run


def get_run(session: Session, run_id: uuid.UUID) -> ForecastRun | None:
    return session.get(ForecastRun, run_id)


def get_owned_run(
    session: Session, run_id: uuid.UUID, dataset_id: uuid.UUID
) -> ForecastRun | None:
    """A run is reachable only through the dataset it belongs to.

    Checking both means a run id guessed or copied from elsewhere cannot be
    read through someone else's dataset.
    """
    return session.execute(
        select(ForecastRun).where(
            ForecastRun.id == run_id, ForecastRun.dataset_id == dataset_id
        )
    ).scalar_one_or_none()


def list_runs(
    session: Session, dataset_id: uuid.UUID, *, limit: int = 20
) -> list[ForecastRun]:
    return list(
        session.execute(
            select(ForecastRun)
            .where(ForecastRun.dataset_id == dataset_id)
            .order_by(ForecastRun.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def latest_ready_run(
    session: Session, dataset_id: uuid.UUID, series_key: str | None
) -> ForecastRun | None:
    """What the dashboard asks for: the newest finished run for this series."""
    statement = select(ForecastRun).where(
        ForecastRun.dataset_id == dataset_id,
        ForecastRun.status == "ready",
    )
    statement = statement.where(
        ForecastRun.series_key.is_(None) if series_key is None
        else ForecastRun.series_key == series_key
    )
    return session.execute(
        statement.order_by(ForecastRun.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def add_results(session: Session, run: ForecastRun, rows: list[dict[str, Any]]) -> int:
    """Store the per-model per-fold rows. Fold 0 is the hold-out."""
    for row in rows:
        session.add(ForecastModelResult(run_id=run.id, **row))
    session.flush()
    return len(rows)


def results_for_run(
    session: Session, run_id: uuid.UUID, *, holdout_only: bool = False
) -> list[ForecastModelResult]:
    statement = select(ForecastModelResult).where(ForecastModelResult.run_id == run_id)
    if holdout_only:
        statement = statement.where(ForecastModelResult.fold == HOLDOUT_FOLD)
    return list(
        session.execute(
            statement.order_by(ForecastModelResult.fold, ForecastModelResult.model)
        ).scalars()
    )


def mark_stuck_runs_failed(session: Session) -> int:
    """A run left 'running' by a crash or restart can never finish.

    Called at start-up for the same reason `recover_stuck_datasets` is: a row
    stuck in a transient state is worse than a failed one, because the UI waits
    on it forever.
    """
    stuck = list(
        session.execute(
            select(ForecastRun).where(ForecastRun.status.in_(("queued", "running")))
        ).scalars()
    )
    for run in stuck:
        run.status = "failed"
        run.error = (
            "The server restarted while this run was in progress. Start it again."
        )
    return len(stuck)
