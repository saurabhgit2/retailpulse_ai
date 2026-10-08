"""Time series over a chosen granularity, with partial periods marked.

The architecture is explicit about one thing here: the last bucket of a dataset
is almost always incomplete, and plotting it next to whole ones draws a cliff
that does not exist. So every point carries `is_partial`, the frontend greys
those, and growth is not computed across them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GRANULARITIES = ("day", "week", "month", "year")

# Pandas period aliases. 'W-MON' starts weeks on Monday, matching
# date_trunc('week', ...) in PostgreSQL, so SQL and pandas agree on bucket
# boundaries - a mismatch here would shift every weekly figure by days.
_PERIOD_FREQ = {"day": "D", "week": "W-MON", "month": "MS", "year": "YS"}

_PERIOD_LENGTH = {
    "day": pd.Timedelta(days=1),
    "week": pd.Timedelta(days=7),
}


def week_start(timestamps: pd.Series) -> pd.Series:
    """The Monday that starts each timestamp's week.

    Use this rather than `to_period(...)` directly, because pandas' weekly
    aliases name the day a week **ends** on, not the day it starts:

        to_period("W-MON").start_time  ->  Tuesday   (week ending Monday)
        to_period("W-SUN").start_time  ->  Monday    (week ending Sunday)

    PostgreSQL's `date_trunc('week', ...)` starts weeks on Monday, so the
    second one is what agrees with the database. Getting this wrong shifts
    every weekly figure by a day and makes a `date_range(freq="W-MON")`
    reindex miss every row - silently, because the result is a full series of
    zeros rather than an error.
    """
    return pd.to_datetime(timestamps).dt.to_period("W-SUN").dt.start_time


def period_end(period_start: pd.Timestamp, granularity: str) -> pd.Timestamp:
    """The last instant that belongs to the bucket starting at `period_start`."""
    start = pd.Timestamp(period_start)
    if granularity in _PERIOD_LENGTH:
        return start + _PERIOD_LENGTH[granularity] - pd.Timedelta(nanoseconds=1)
    if granularity == "month":
        return start + pd.offsets.MonthBegin(1) - pd.Timedelta(nanoseconds=1)
    if granularity == "year":
        return start + pd.offsets.YearBegin(1) - pd.Timedelta(nanoseconds=1)
    raise ValueError(f"Unknown granularity: {granularity}")


def build_trend(
    frame: pd.DataFrame,
    granularity: str,
    *,
    data_max: pd.Timestamp | None = None,
    ma_window: int = 4,
    value_columns: tuple[str, ...] = ("gross_revenue", "net_revenue", "units", "orders"),
) -> dict[str, object]:
    """Turn an aggregated frame into chart-ready points.

    `frame` is what SQL produced: one row per period with the value columns.
    `data_max` is the dataset's last transaction timestamp; a bucket that
    extends beyond it is partial.
    """
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity must be one of {GRANULARITIES}")

    if frame.empty:
        return {
            "granularity": granularity,
            "ma_window": ma_window,
            "points": [],
            "complete_points": 0,
            "partial_points": 0,
        }

    series = frame.copy()
    series["period"] = pd.to_datetime(series["period"])
    series = series.sort_values("period").reset_index(drop=True)

    # Missing buckets are real zeros - a week with no sales is information, and
    # leaving the gap would make the moving average span unequal spans of time.
    full_index = pd.date_range(
        series["period"].iloc[0], series["period"].iloc[-1], freq=_PERIOD_FREQ[granularity]
    )
    series = (
        series.set_index("period")
        .reindex(full_index)
        .rename_axis("period")
        .reset_index()
    )
    present = [column for column in value_columns if column in series.columns]
    for column in present:
        series[column] = (
            pd.to_numeric(series[column], errors="coerce").fillna(0.0).astype("float64")
        )

    if data_max is not None:
        last_instant = pd.Timestamp(data_max)
        series["is_partial"] = series["period"].apply(
            lambda start: period_end(start, granularity) > last_instant
        )
    else:
        series["is_partial"] = False

    headline = "gross_revenue" if "gross_revenue" in present else (present[0] if present else None)

    if headline:
        # The moving average is computed on complete periods only, so a partial
        # final bucket cannot drag the smoothed line down.
        complete_values = series[headline].where(~series["is_partial"])
        series["moving_average"] = (
            complete_values.rolling(window=max(1, ma_window), min_periods=max(1, ma_window)).mean()
        )
        previous = complete_values.shift(1)
        series["growth"] = np.where(
            series["is_partial"] | previous.isna() | (previous == 0),
            np.nan,
            (complete_values - previous) / previous.abs(),
        )
    else:
        series["moving_average"] = np.nan
        series["growth"] = np.nan

    points = []
    for row in series.itertuples(index=False):
        point: dict[str, object] = {
            "period": pd.Timestamp(row.period).date().isoformat(),
            "is_partial": bool(row.is_partial),
        }
        for column in present:
            point[column] = float(getattr(row, column))
        point["moving_average"] = (
            None if pd.isna(row.moving_average) else float(row.moving_average)
        )
        point["growth"] = None if pd.isna(row.growth) else float(row.growth)
        points.append(point)

    partial_count = int(series["is_partial"].sum())
    return {
        "granularity": granularity,
        "ma_window": ma_window,
        "headline": headline,
        "points": points,
        "complete_points": len(points) - partial_count,
        "partial_points": partial_count,
    }
