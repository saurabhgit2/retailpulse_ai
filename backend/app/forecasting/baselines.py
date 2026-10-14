"""Models 1-3: the benchmarks everything else has to beat.

These are three or four lines of arithmetic each, and they are the most
important models in the ladder. A sophisticated model that cannot beat seasonal
naive has told you something, and the only way to know that is to run seasonal
naive under the same protocol. Published retail forecasting comparisons that
omit the naive benchmark are hard to interpret for exactly this reason.

Auppakorn & Phumchusri (2022) give a real-world calibration of how low the bar
can be: the case-study company's own existing forecasts scored a revenue-
weighted MAPE of 54.28, against 16.7 for XGBoost and 22.2 for TBATS. A simple
benchmark is not a formality.

`seasonal_naive` has a second job: it is the scaling denominator for MASE, so
its definition here and in `metrics.mase` must stay the same - period `m`,
taken from the training window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.forecasting.base import Forecaster, register


@register
class Naive(Forecaster):
    """Model 1. Tomorrow is like today: repeat the last observed value.

    Optimal when the series is a random walk, which is a better description of
    many short retail series than anyone expects.
    """

    name = "naive"
    label = "Naive (last value)"
    family = "baseline"
    min_observations = 1

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        usable = y.dropna()
        if usable.empty:
            raise ValueError("Naive needs at least one non-missing observation.")
        self._last = float(usable.iloc[-1])
        # One-step in-sample prediction is the previous value, which gives the
        # residuals that `intervals.py` needs.
        self._fitted = y.shift(1)

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        return np.full(horizon, self._last, dtype="float64")


@register
class SeasonalNaive(Forecaster):
    """Model 2, and the main benchmark: this season repeats the last one.

    For weekly data with `season_length=52`, the forecast for next week 7 is
    what happened in week 7 of the previous year. On retail data with a strong
    yearly shape this is a genuinely hard baseline to beat.

    **Falls back to naive** when the training window is shorter than one full
    season, and says so in its metadata rather than failing. With about two
    years of Online Retail II that fallback will trigger on the early CV folds,
    and the results table has to show which folds it applied to - otherwise
    "seasonal naive" means two different models in one column.
    """

    name = "seasonal_naive"
    label = "Seasonal naive"
    family = "baseline"
    min_observations = 1

    def __init__(self, season_length: int = 52) -> None:
        super().__init__()
        if season_length < 1:
            raise ValueError(f"season_length must be at least 1; got {season_length}.")
        self.season_length = int(season_length)
        self.fell_back = False

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        values = y.to_numpy(dtype="float64")
        self.fell_back = len(values) < self.season_length

        if self.fell_back:
            usable = y.dropna()
            if usable.empty:
                raise ValueError("Seasonal naive needs at least one observation.")
            self._season = np.array([float(usable.iloc[-1])])
            self._fitted = y.shift(1)
        else:
            # The last complete season, which is what gets repeated.
            self._season = values[-self.season_length:]
            self._fitted = y.shift(self.season_length)

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        period = len(self._season)
        positions = np.arange(horizon) % period
        return np.asarray(self._season[positions], dtype="float64")

    def describe(self) -> dict[str, object]:
        record = super().describe()
        record["season_length"] = self.season_length
        record["fell_back_to_naive"] = self.fell_back
        if self.fell_back:
            record["fallback_note"] = (
                f"The training window is shorter than one season of "
                f"{self.season_length} periods, so this fold used the last value "
                f"instead. Report which folds this applied to."
            )
        return record


@register
class SeasonalNaiveWithDrift(Forecaster):
    """Seasonal naive, corrected for the level change since last season.

    **Why this exists.** Plain seasonal naive repeats last year's *values*, so
    on a trending series it is systematically wrong by one year of trend. On a
    constructed series with a yearly sine of amplitude 250 and a trend of 3 per
    week, the trend contributes 156 over a season and plain seasonal naive
    scores worse than naive - measured, not assumed, in
    `test_forecast_evaluate.py`. Online Retail II trends, so the benchmark the
    whole ladder is judged against has to handle that or the comparison is
    rigged in favour of anything that models a level.

    The correction is the mean difference between the last season and the one
    before it, spread evenly:

        forecast(h) = y_{T+h-m} + drift,  drift = mean(y_t - y_{t-m}) over the
                                                  last complete season

    This is a standard adjustment, not an invention, and it costs one line. It
    needs **two** full seasons, so on Online Retail II it will not be available
    on the early CV folds; like `SeasonalNaive` it falls back and says so.
    """

    name = "seasonal_naive_drift"
    label = "Seasonal naive with drift"
    family = "baseline"
    min_observations = 2

    def __init__(self, season_length: int = 52) -> None:
        super().__init__()
        if season_length < 1:
            raise ValueError(f"season_length must be at least 1; got {season_length}.")
        self.season_length = int(season_length)
        self.drift = 0.0
        self.fell_back = False

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        values = y.to_numpy(dtype="float64")
        m = self.season_length
        self.fell_back = len(values) < 2 * m

        if self.fell_back:
            # Not enough history for a year-on-year difference. Fall back to
            # drift over whatever history there is, which is the same idea at
            # a shorter range.
            usable = y.dropna()
            self._season = np.array([float(usable.iloc[-1])])
            span = max(1, len(usable) - 1)
            self.drift = (float(usable.iloc[-1]) - float(usable.iloc[0])) / span
            self._fitted = y.shift(1) + self.drift
        else:
            self._season = values[-m:]
            year_on_year = values[-m:] - values[-2 * m: -m]
            self.drift = float(np.nanmean(year_on_year))
            self._fitted = y.shift(m) + self.drift

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        period = len(self._season)
        positions = np.arange(horizon) % period
        if self.fell_back:
            # The short-history branch is a drifting naive, so the drift
            # accumulates step by step.
            return self._season[positions] + self.drift * np.arange(1, horizon + 1)
        return self._season[positions] + self.drift

    def describe(self) -> dict[str, object]:
        record = super().describe()
        record["season_length"] = self.season_length
        record["drift_per_season"] = self.drift
        record["fell_back"] = self.fell_back
        if self.fell_back:
            record["fallback_note"] = (
                f"Fewer than two seasons of {self.season_length} periods, so the "
                f"year-on-year drift could not be measured; used the trend over "
                f"the available history instead."
            )
        return record


@register
class MovingAverage(Forecaster):
    """Model 3. The level is locally constant; average the last `window` periods.

    A flat forecast, but a less jumpy one than naive. Worth keeping because it
    separates two questions the naive model conflates: is the series hard to
    predict because the level moves, or because it is noisy around a stable
    level? If the moving average beats naive, the answer is noise.
    """

    name = "moving_average"
    label = "Moving average"
    family = "baseline"

    def __init__(self, window: int = 4) -> None:
        super().__init__()
        if window < 1:
            raise ValueError(f"window must be at least 1; got {window}.")
        self.window = int(window)
        self.min_observations = self.window

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        tail = y.dropna().tail(self.window)
        if tail.empty:
            raise ValueError("Moving average needs at least one observation.")
        self._level = float(tail.mean())
        self._fitted = y.shift(1).rolling(self.window, min_periods=1).mean()

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        return np.full(horizon, self._level, dtype="float64")

    def describe(self) -> dict[str, object]:
        record = super().describe()
        record["window"] = self.window
        return record


@register
class Drift(Forecaster):
    """Naive plus the average slope between the first and last observation.

    Not in the architecture's ladder, but it costs nothing and it guards
    against a specific embarrassment: a trending series where every model in
    the table is beaten by drawing a straight line through the first and last
    points. If that happens you want to know before the viva.
    """

    name = "drift"
    label = "Drift (naive with trend)"
    family = "baseline"
    min_observations = 2

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        usable = y.dropna()
        if len(usable) < 2:
            raise ValueError("Drift needs at least two non-missing observations.")
        self._last = float(usable.iloc[-1])
        span = len(usable) - 1
        self._slope = (float(usable.iloc[-1]) - float(usable.iloc[0])) / span
        self._fitted = y.shift(1) + self._slope

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        steps = np.arange(1, horizon + 1, dtype="float64")
        return self._last + self._slope * steps

    def describe(self) -> dict[str, object]:
        record = super().describe()
        record["slope_per_period"] = self._slope if self._history is not None else None
        return record
