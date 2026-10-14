"""Lag, rolling and calendar features for the global tree model.

This is the module most likely to leak, so it is the one with the strictest
rule: **every feature for period t is computed from information available
strictly before t.** In pandas terms, `shift(1)` always comes before
`rolling(...)`, never after. Written the other way round -
`y.rolling(4).mean().shift(1)` versus `y.shift(1).rolling(4).mean()` - the
first includes `y_t` in the window and the model gets to see the answer. The
two expressions look almost identical in a diff, which is why there is a test
that plants a spike in the future and asserts it cannot reach any feature.

**Direct multi-step, not recursive.** For a horizon of h the target is
`y_{t+h}` and the features are those known at `t`. One model is fitted per
horizon step. The alternative - forecasting one step and feeding the forecast
back in - compounds its own errors and makes the leakage argument harder to
state. Direct is more models to fit and a much simpler claim to defend.

**Global, across SKUs.** One SKU has at most about 105 weekly observations,
which is far too few for a tree ensemble. Pooling all selected SKUs into one
training frame gives thousands of rows. The cost is that the model no longer
has a per-series level, so each series is scaled by statistics computed **on
its training window only**; `scale_frame` returns those statistics so the same
scaling can be reapplied at prediction time without recomputing them on data
that includes the test window.

Calendar features follow Auppakorn & Phumchusri (2022), who used date, weekend,
mid/end of month and holiday indicators, and found via stepwise regression that
day-of-week effects were among the useful predictors of daily sales. Their
warning is worth carrying too: adding COVID case counts *hurt* their model,
because the validation period contained values far outside the training range.
Any exogenous feature here has the same risk, and `describe_coverage` reports
how much of the prediction range falls outside what training saw.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_LAGS = (1, 2, 3, 4, 8, 12, 52)
DEFAULT_WINDOWS = (4, 12, 52)


@dataclass(frozen=True)
class FeatureSpec:
    """What to build. Declared in the research config, not inferred from data."""

    lags: tuple[int, ...] = DEFAULT_LAGS
    rolling_windows: tuple[int, ...] = DEFAULT_WINDOWS
    calendar: bool = True
    horizon: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "lags": list(self.lags),
            "rolling_windows": list(self.rolling_windows),
            "calendar": self.calendar,
            "horizon": self.horizon,
        }


@dataclass
class ScalingStats:
    """Per-series centre and spread, fitted on training rows only."""

    centre: dict[str, float] = field(default_factory=dict)
    spread: dict[str, float] = field(default_factory=dict)

    def apply(self, series_id: str, values: np.ndarray) -> np.ndarray:
        centre = self.centre.get(series_id, 0.0)
        spread = self.spread.get(series_id, 1.0) or 1.0
        return (values - centre) / spread

    def invert(self, series_id: str, values: np.ndarray) -> np.ndarray:
        centre = self.centre.get(series_id, 0.0)
        spread = self.spread.get(series_id, 1.0) or 1.0
        return values * spread + centre


def build_features(
    frame: pd.DataFrame,
    spec: FeatureSpec,
    *,
    series_column: str = "series_id",
    time_column: str = "period",
    value_column: str = "value",
) -> pd.DataFrame:
    """One row per (series, period) with past-only features and target `y`.

    `frame` is long: a row per series per period, already regularly spaced.
    The returned frame keeps the identifying columns, adds the feature columns,
    and adds `y` = the value `spec.horizon` periods ahead.

    Rows whose features or target are not fully available are dropped, and the
    count is recoverable by comparing lengths - a model silently trained on 40
    rows because a lag of 52 was requested on a two-year series is a failure
    worth noticing.
    """
    required = {series_column, time_column, value_column}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f"build_features needs columns {sorted(required)}; missing {sorted(missing)}.")

    work = frame.loc[:, [series_column, time_column, value_column]].copy()
    work[time_column] = pd.to_datetime(work[time_column])
    work[value_column] = pd.to_numeric(work[value_column], errors="coerce").astype("float64")
    work = work.sort_values([series_column, time_column]).reset_index(drop=True)

    grouped = work.groupby(series_column, observed=True)[value_column]

    for lag in spec.lags:
        work[f"lag_{lag}"] = grouped.shift(lag)

    # shift(1) FIRST, then roll. The other order puts y_t inside its own window.
    shifted = grouped.shift(1)
    for window in spec.rolling_windows:
        by_series = shifted.groupby(work[series_column], observed=True)
        work[f"roll_mean_{window}"] = by_series.transform(
            lambda s, w=window: s.rolling(w, min_periods=max(2, w // 2)).mean()
        )
        work[f"roll_std_{window}"] = by_series.transform(
            lambda s, w=window: s.rolling(w, min_periods=max(2, w // 2)).std()
        )

    if spec.calendar:
        stamps = work[time_column].dt
        work["week_of_year"] = stamps.isocalendar().week.astype("int64")
        work["month"] = stamps.month.astype("int64")
        work["quarter"] = stamps.quarter.astype("int64")
        work["day_of_week"] = stamps.dayofweek.astype("int64")
        work["is_month_end"] = stamps.is_month_end.astype("int64")
        # A smooth encoding of position in the year, so the tree does not have
        # to learn that week 52 and week 1 are neighbours.
        angle = 2 * np.pi * work["week_of_year"] / 52.0
        work["week_sin"] = np.sin(angle)
        work["week_cos"] = np.cos(angle)

    # The target: the value `horizon` steps ahead of the feature row.
    work["y"] = grouped.shift(-spec.horizon)

    feature_columns = feature_names(spec)
    complete = work.dropna(subset=[*feature_columns, "y"]).reset_index(drop=True)
    return complete


def feature_names(spec: FeatureSpec) -> list[str]:
    """The feature columns `build_features` produces, in a stable order.

    Stable because the fitted model stores coefficients or split points against
    positions, and a reordering between fit and predict would silently scramble
    them.
    """
    names = [f"lag_{lag}" for lag in spec.lags]
    for window in spec.rolling_windows:
        names.append(f"roll_mean_{window}")
        names.append(f"roll_std_{window}")
    if spec.calendar:
        names += ["week_of_year", "month", "quarter", "day_of_week",
                  "is_month_end", "week_sin", "week_cos"]
    return names


def fit_scaling(
    training: pd.DataFrame,
    *,
    series_column: str = "series_id",
    value_column: str = "value",
) -> ScalingStats:
    """Per-series median and IQR, from training rows only.

    Median and IQR rather than mean and standard deviation because a single
    promotional spike moves the mean a long way, and the point of per-series
    scaling is to put series on a comparable footing, not to be dragged around
    by their outliers.
    """
    stats = ScalingStats()
    for series_id, group in training.groupby(series_column, observed=True):
        values = pd.to_numeric(group[value_column], errors="coerce").dropna()
        if values.empty:
            continue
        centre = float(values.median())
        spread = float(values.quantile(0.75) - values.quantile(0.25))
        if spread <= 0:
            spread = float(values.std(ddof=1)) if len(values) > 1 else 1.0
        stats.centre[str(series_id)] = centre
        stats.spread[str(series_id)] = spread if spread > 0 else 1.0
    return stats


def describe_coverage(
    training: pd.DataFrame, future: pd.DataFrame, columns: list[str]
) -> dict[str, object]:
    """How far outside the training range the prediction inputs fall.

    Auppakorn & Phumchusri found that adding COVID case counts made their model
    *worse*, because the validation period contained values the training period
    never saw - a tree cannot extrapolate past the range it was split on. This
    reports that condition instead of letting it show up as an unexplained
    accuracy drop.
    """
    report = []
    for column in columns:
        if column not in training or column not in future:
            continue
        low, high = float(training[column].min()), float(training[column].max())
        values = pd.to_numeric(future[column], errors="coerce").dropna()
        if values.empty:
            continue
        outside = int(((values < low) | (values > high)).sum())
        if outside:
            report.append({
                "feature": column,
                "training_min": low,
                "training_max": high,
                "rows_outside_training_range": outside,
                "share_outside": float(outside / len(values)),
            })
    return {
        "features_outside_training_range": report,
        "note": (
            "A tree model cannot extrapolate beyond the range it was split on. "
            "Auppakorn & Phumchusri (2022) report exactly this failure: adding "
            "COVID-19 case counts lowered accuracy because the validation period "
            "contained values not present in training."
        ) if report else None,
    }
