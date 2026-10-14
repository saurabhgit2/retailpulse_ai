"""Model 5: exponential smoothing with a damped trend, written out in full.

Why implement it rather than import statsmodels: the whole family is about
fifteen lines of recursion, the parameters are the interesting part of the
model, and writing it out means the report can state exactly what was fitted
instead of naming a function. It also keeps `requirements.txt` as it is. The
statistical content is standard Holt-Winters; nothing here is novel, and the
report should present it as a textbook method implemented directly.

The state recursion, additive errors, damped additive trend, optional additive
seasonality of period m:

    level_t  = alpha*(y_t - season_{t-m}) + (1 - alpha)*(level_{t-1} + phi*trend_{t-1})
    trend_t  = beta*(level_t - level_{t-1}) + (1 - beta)*phi*trend_{t-1}
    season_t = gamma*(y_t - level_t) + (1 - gamma)*season_{t-m}

    forecast(h) = level_T + (phi + phi^2 + ... + phi^h)*trend_T + season_{T+h-m}

**Why damped.** With `phi = 1` the trend extrapolates forever, and on a
12-week horizon a trend fitted to a short noisy series produces forecasts that
are visibly absurd. `phi < 1` makes the trend decay towards a constant, which
is both more accurate in practice and much easier to defend when a manager
asks why the model thinks sales will treble.

**Why it belongs in this comparison.** Aras et al. (2017) included ETS as one
of five single models on ten weekly retail series and found it comparable with
ARIMA, ARFIMA, neural networks and ANFIS - no single model beat the others
across all series. ETS is the representative of the statistical family here
for the same reason.

Parameters are estimated by minimising in-sample sum of squared one-step
errors with scipy's L-BFGS-B, from several starting points, because the
likelihood surface has local minima and a single start can land in a bad one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from app.forecasting.base import Forecaster, register

# Keeping the smoothing parameters off the exact boundary avoids a degenerate
# fit (alpha = 0 ignores the data; alpha = 1 is the naive model) and keeps the
# optimiser's gradients finite.
BOUNDS = (1e-4, 1 - 1e-4)
# A damping factor below this makes the trend vanish within a step or two,
# which is indistinguishable from having no trend and makes beta unidentifiable.
PHI_BOUNDS = (0.80, 0.999)

# Several starts, because the surface is not convex.
STARTING_POINTS = (
    (0.3, 0.1, 0.95, 0.1),
    (0.6, 0.05, 0.90, 0.3),
    (0.1, 0.2, 0.98, 0.05),
)


def _recursion(
    values: np.ndarray,
    alpha: float,
    beta: float,
    phi: float,
    gamma: float,
    period: int,
    initial_level: float,
    initial_trend: float,
    initial_season: np.ndarray,
) -> tuple[np.ndarray, float, float, np.ndarray]:
    """One pass of the state recursion. Returns the one-step predictions."""
    level = initial_level
    trend = initial_trend
    season = initial_season.copy()
    predictions = np.empty(len(values), dtype="float64")

    for t, observed in enumerate(values):
        seasonal = season[t % period] if period > 1 else 0.0
        prediction = level + phi * trend + seasonal
        predictions[t] = prediction

        if np.isnan(observed):
            # A missing observation updates nothing: the state carries forward.
            # Interpolating here would invent data and flatter the fit.
            level = level + phi * trend
            trend = phi * trend
            continue

        previous_level = level
        level = alpha * (observed - seasonal) + (1 - alpha) * (previous_level + phi * trend)
        trend = beta * (level - previous_level) + (1 - beta) * phi * trend
        if period > 1:
            season[t % period] = gamma * (observed - level) + (1 - gamma) * seasonal

    return predictions, level, trend, season


def _initial_state(values: np.ndarray, period: int) -> tuple[float, float, np.ndarray]:
    """Starting level, trend and seasonal profile from the first cycles.

    Deliberately crude and deterministic. The optimiser refines the smoothing
    parameters, not these; a sophisticated initialisation would add a second
    place for a bug to hide without changing the result much.
    """
    usable = values[~np.isnan(values)]
    if period > 1 and len(values) >= 2 * period:
        first = np.nanmean(values[:period])
        second = np.nanmean(values[period: 2 * period])
        level = float(first)
        trend = float((second - first) / period)
        season = np.array([
            float(np.nanmean(values[phase::period][:2]) - first)
            for phase in range(period)
        ])
        season = np.nan_to_num(season - season.mean())
    else:
        head = usable[: max(2, min(len(usable), 4))]
        level = float(np.mean(head))
        trend = float(head[-1] - head[0]) / max(1, len(head) - 1)
        season = np.zeros(max(period, 1))
    return level, trend, season


@register
class DampedETS(Forecaster):
    """Holt's linear method with a damped trend, optionally seasonal."""

    name = "ets"
    label = "ETS (damped trend)"
    family = "statistical"

    def __init__(self, season_length: int = 1, seasonal: bool = False) -> None:
        super().__init__()
        if season_length < 1:
            raise ValueError(f"season_length must be at least 1; got {season_length}.")
        self.season_length = int(season_length)
        self.seasonal = bool(seasonal) and self.season_length > 1
        # Two full cycles to estimate a seasonal profile; otherwise each
        # seasonal index would rest on a single observation.
        self.min_observations = 2 * self.season_length + 2 if self.seasonal else 5
        self.parameters: dict[str, float] = {}
        self.converged = False

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        values = y.to_numpy(dtype="float64")
        period = self.season_length if self.seasonal else 1
        level0, trend0, season0 = _initial_state(values, period)
        observed = ~np.isnan(values)

        def objective(parameters: np.ndarray) -> float:
            alpha, beta, phi, gamma = parameters
            predictions, *_ = _recursion(
                values, alpha, beta, phi, gamma, period, level0, trend0, season0
            )
            errors = values[observed] - predictions[observed]
            if not np.all(np.isfinite(errors)):
                return 1e18
            return float(np.sum(errors ** 2))

        bounds = [BOUNDS, BOUNDS, PHI_BOUNDS, BOUNDS if period > 1 else (0.0, 0.0)]
        best: tuple[float, np.ndarray] | None = None
        for start in STARTING_POINTS:
            guess = np.array(start if period > 1 else (start[0], start[1], start[2], 0.0))
            outcome = minimize(objective, guess, method="L-BFGS-B", bounds=bounds)
            if best is None or outcome.fun < best[0]:
                best = (float(outcome.fun), outcome.x)
                self.converged = bool(outcome.success)

        assert best is not None
        alpha, beta, phi, gamma = best[1]
        self.parameters = {
            "alpha": float(alpha), "beta": float(beta),
            "phi": float(phi), "gamma": float(gamma),
        }

        predictions, level, trend, season = _recursion(
            values, alpha, beta, phi, gamma, period, level0, trend0, season0
        )
        self._level = float(level)
        self._trend = float(trend)
        self._season = season
        self._period = period
        self._observations = len(values)
        self._fitted = pd.Series(predictions, index=y.index)

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        phi = self.parameters["phi"]
        # Damped trend: the cumulative damping factor phi + phi^2 + ... + phi^h,
        # which converges rather than growing without bound.
        steps = np.arange(1, horizon + 1)
        damping = np.array([np.sum(phi ** np.arange(1, h + 1)) for h in steps])
        forecast = self._level + damping * self._trend

        if self._period > 1:
            phases = (self._observations + np.arange(horizon)) % self._period
            forecast = forecast + self._season[phases]
        return forecast

    def describe(self) -> dict[str, object]:
        record = super().describe()
        record["seasonal"] = self.seasonal
        record["season_length"] = self.season_length
        record["parameters"] = dict(self.parameters)
        record["converged"] = self.converged
        if self.parameters:
            phi = self.parameters["phi"]
            record["trend_half_life_periods"] = (
                None if phi >= 1 else float(np.log(0.5) / np.log(phi))
            )
        return record
