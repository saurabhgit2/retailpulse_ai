"""Seasonality: calendar indices and a decomposition of the weekly series.

**A deliberate deviation from the architecture, to state in the report.** §12.6
specifies STL. STL lives in statsmodels, which Phase 5 brings in for ETS and
ARIMA; until then this module uses **classical decomposition** - a centred
moving average for the trend, the mean of the detrended values at each phase
for the seasonal component, and whatever is left as the remainder.

The difference that matters: classical decomposition assumes the seasonal shape
is constant over time, while STL lets it evolve, and it loses m/2 points at each
end. Seasonal strength is defined the same way for both, so the measure stays
comparable when the switch happens:

    F_S = max(0, 1 - Var(remainder) / Var(seasonal + remainder))

0 means no seasonality the decomposition can find; values near 1 mean the
seasonal component explains almost all the variation left after the trend.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _index_table(frame: pd.DataFrame, group: pd.Series, labels: list[str] | None = None,
                 value: str = "gross_revenue") -> list[dict[str, object]]:
    """Mean value per calendar bucket, as an index where 1.0 is the overall mean.

    An index rather than a raw total because totals confound "busy" with "how
    many Mondays were in the data"; the mean per occurrence does not.
    """
    numbers = pd.to_numeric(frame[value], errors="coerce")
    grouped = numbers.groupby(group, observed=True)
    means = grouped.mean()
    overall = float(numbers.mean()) if len(numbers) else 0.0

    rows = []
    for key, mean_value in means.items():
        position = int(key)
        rows.append({
            "bucket": position,
            "label": labels[position] if labels and 0 <= position < len(labels) else str(key),
            "mean": float(mean_value),
            "total": float(grouped.sum().loc[key]),
            "observations": int(grouped.size().loc[key]),
            "index": float(mean_value / overall) if overall else None,
        })
    return sorted(rows, key=lambda row: row["bucket"])


def calendar_indices(daily: pd.DataFrame, value: str = "gross_revenue") -> dict[str, object]:
    """Day-of-week, month and (when present) hour indices.

    `daily` has a `period` column of timestamps and the value column. Hour
    indices need hour-level data, so they are returned only when the caller
    supplied an `hour` column.
    """
    if daily.empty:
        return {"day_of_week": [], "month": [], "hour": [], "value": value}

    frame = daily.copy()
    frame["period"] = pd.to_datetime(frame["period"])

    result = {
        "value": value,
        "day_of_week": _index_table(frame, frame["period"].dt.dayofweek, DAY_NAMES, value),
        "month": _index_table(frame, frame["period"].dt.month - 1, MONTH_NAMES, value),
        "hour": [],
    }
    if "hour" in frame.columns:
        result["hour"] = _index_table(frame, pd.to_numeric(frame["hour"]), None, value)
    return result


def classical_decomposition(
    values: pd.Series,
    period: int,
    model: str = "additive",
) -> dict[str, object]:
    """Trend / seasonal / remainder by the classical moving-average method.

    `values` is indexed by period start and already regularly spaced (the trend
    builder fills gaps with zeros before this is called).

    The seasonal value for each phase is the **mean** of the detrended values
    at that phase, which is the textbook definition. That makes it sensitive to
    a single extreme period, which is why anomaly detection does not reuse this
    function: `app/analytics/anomalies.py` builds its own all-median baseline.
    """
    series = pd.to_numeric(pd.Series(values), errors="coerce").astype("float64")
    observations = len(series)

    if period < 2 or observations < 2 * period:
        return {
            "available": False,
            "reason": (
                f"A decomposition with period {period} needs at least {2 * period} "
                f"observations; this series has {observations}."
            ),
            "period": period,
            "model": model,
        }

    if model == "multiplicative" and (series <= 0).any():
        model = "additive"  # multiplicative is undefined at or below zero

    # Centred moving average. For an even period the window is averaged twice,
    # so the result sits on an observation rather than between two of them.
    if period % 2 == 0:
        trend = series.rolling(window=period, center=True).mean().rolling(window=2, center=True).mean()
        trend = trend.shift(-1)
    else:
        trend = series.rolling(window=period, center=True).mean()

    detrended = series - trend if model == "additive" else series / trend.replace(0, np.nan)

    phase = np.arange(observations) % period
    seasonal_means = pd.Series(detrended.to_numpy(), index=phase).groupby(level=0).mean()
    # Centre the seasonal component so it adds (or multiplies) to nothing
    # overall: without this the trend and seasonal parts both carry the level.
    if model == "additive":
        seasonal_means = seasonal_means - seasonal_means.mean()
    else:
        average = seasonal_means.mean()
        seasonal_means = seasonal_means / average if average else seasonal_means

    seasonal = pd.Series(seasonal_means.reindex(phase).to_numpy(), index=series.index)
    remainder = (
        series - trend - seasonal if model == "additive"
        else series / (trend * seasonal).replace(0, np.nan)
    )

    strength = seasonal_strength(seasonal, remainder, model)
    cycles = observations / period
    return {
        "available": True,
        "period": period,
        "model": model,
        "method": "classical moving-average decomposition",
        "cycles": float(cycles),
        # Each seasonal phase is estimated from `cycles` observations. At two
        # cycles that is two points per phase, so the seasonal component
        # absorbs the noise and the remainder collapses towards zero. The
        # decomposition is still returned - it is what the data supports - but
        # anything reading the remainder must know how thin it is.
        "weak_seasonal_estimate": bool(cycles < 3),
        "seasonal_estimate_note": (
            None if cycles >= 3 else
            f"Only {cycles:.1f} cycles of history: each seasonal phase is "
            f"estimated from about {cycles:.0f} observations, so the seasonal "
            f"component is fitted to noise as much as to season."
        ),
        "seasonal_strength": strength,
        "index": [str(pd.Timestamp(i).date()) if not isinstance(i, int) else int(i)
                  for i in series.index],
        "observed": [float(v) for v in series.to_numpy()],
        "trend": [None if pd.isna(v) else float(v) for v in trend.to_numpy()],
        "seasonal": [None if pd.isna(v) else float(v) for v in seasonal.to_numpy()],
        "remainder": [None if pd.isna(v) else float(v) for v in remainder.to_numpy()],
        # The seasonally adjusted series: the observations with the seasonal
        # component taken out, trend and noise left in.
        #
        # This is not decoration. Chu and Zhang (2003), "A comparative study of
        # linear and nonlinear models for aggregate retail sales forecasting",
        # Int. J. Production Economics 86, 217-231, found that prior seasonal
        # adjustment significantly improved neural-network accuracy, and that
        # the best model overall was a neural network fitted to deseasonalised
        # data. Phase 5 can therefore train on this series directly and compare
        # against models fitted to the raw one, which is a cheap and
        # well-grounded experiment for RQ1.
        "deseasonalised": [
            None if pd.isna(v) else float(v) for v in _deseasonalise(series, seasonal, model)
        ],
    }


def _deseasonalise(series: pd.Series, seasonal: pd.Series, model: str) -> pd.Series:
    """Remove the seasonal component: subtract it, or divide it out."""
    if model == "multiplicative":
        return series / seasonal.replace(0, np.nan)
    return series - seasonal


def seasonal_strength(
    seasonal: pd.Series, remainder: pd.Series, model: str = "additive"
) -> float | None:
    """F_S = max(0, 1 - Var(R) / Var(S + R)), on the points where both exist."""
    combined = pd.DataFrame({"seasonal": seasonal, "remainder": remainder}).dropna()
    if len(combined) < 3:
        return None
    if model == "multiplicative":
        total = combined["seasonal"] * combined["remainder"]
    else:
        total = combined["seasonal"] + combined["remainder"]
    denominator = float(total.var(ddof=1))
    if denominator <= 0:
        return None
    return float(max(0.0, 1.0 - float(combined["remainder"].var(ddof=1)) / denominator))


def weekly_seasonality(
    weekly: pd.DataFrame, *, value: str = "gross_revenue", period: int = 52
) -> dict[str, object]:
    """Decompose the weekly total series.

    The default period is 52 (a yearly cycle in weekly data). Online Retail II
    covers about two cycles, which is the bare minimum - the yearly component is
    estimated weakly and the report should say so (architecture §0 F6).
    """
    if weekly.empty:
        return {"available": False, "reason": "No data in range.", "period": period}

    frame = weekly.copy()
    frame["period"] = pd.to_datetime(frame["period"])
    frame = frame.sort_values("period").set_index("period")
    series = pd.to_numeric(frame[value], errors="coerce").fillna(0.0).astype("float64")

    result = classical_decomposition(series, period=period)
    if not result.get("available") and period == 52:
        # Fall back to a shorter cycle so a one-year dataset still gets an
        # answer, clearly labelled as a different question.
        shorter = classical_decomposition(series, period=13)
        if shorter.get("available"):
            shorter["note"] = (
                "Not enough history for a 52-week cycle; decomposed on a 13-week "
                "(quarterly) cycle instead."
            )
            return shorter
    return result
