"""Model 4: linear trend plus Fourier terms (harmonic regression).

    y_t = b0 + b1*t + SUM_k [ a_k sin(2*pi*k*t/m) + c_k cos(2*pi*k*t/m) ] + e_t

Two reasons it earns a place in a weekly retail ladder. First it is completely
transparent - the fitted coefficients are readable, and a category manager can
be shown the seasonal curve it implies. Second it handles `m = 52` with `2K`
parameters instead of the 51 that seasonal dummy variables would need, which is
the difference between a model that can be estimated on two years of weekly
data and one that cannot (architecture finding F4).

**State the contrary evidence in the report.** Chu & Zhang (2003) tested
exactly this family on aggregate retail sales and concluded that
"trigonometric models are not useful in aggregate retail sales forecasting",
reasoning that trigonometric models are best for sinusoidal behaviour, and that
retail sales do not have "a clear sinusoidal shape as in rainfall data". They
also found seasonal dummy regression's performance "may not be robust".

That is the one paper in the supplied set that tested this question, and it
found against the method. Keeping the model is still defensible - their series
was monthly aggregate national retail sales, ours is weekly revenue for one
retailer, and their alternative (51 dummies) is not available to us at m = 52 -
but the honest framing is that this model is a hypothesis under test, not a
method chosen because the literature supports it. If it loses to seasonal
naive, that is a result consistent with Chu & Zhang, and worth saying so.

**Ridge, lightly.** With K harmonics plus trend the design matrix can be close
to collinear on short series. A small ridge penalty is applied to the harmonic
coefficients only - never to the intercept or the trend - which keeps the fit
numerically stable without shrinking the level. It defaults low enough to be
nearly an ordinary least-squares fit, and it is recorded in the metadata.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.forecasting.base import Forecaster, register

# Enough to describe a yearly retail shape (a peak, a trough, a shoulder)
# without fitting the noise. Selectable per run; this is only the default.
DEFAULT_HARMONICS = 3

# Small enough to leave the fit essentially OLS, large enough to stop the
# normal equations blowing up when two harmonics are nearly collinear.
DEFAULT_RIDGE = 1e-6


def design_matrix(positions: np.ndarray, period: int, harmonics: int) -> np.ndarray:
    """[1, t, sin(2*pi*k*t/m), cos(2*pi*k*t/m) for k in 1..K]."""
    time = np.asarray(positions, dtype="float64")
    columns = [np.ones_like(time), time]
    for k in range(1, harmonics + 1):
        angle = 2.0 * np.pi * k * time / period
        columns.append(np.sin(angle))
        columns.append(np.cos(angle))
    return np.column_stack(columns)


def max_harmonics(period: int) -> int:
    """Above m/2 the harmonics repeat: sin(2*pi*k*t/m) for k > m/2 is an alias
    of a lower frequency sampled at integer t, so the extra columns add nothing
    and make the matrix singular."""
    return max(1, period // 2)


@register
class FourierRegression(Forecaster):
    """Trend plus K harmonics, by penalised least squares."""

    name = "fourier"
    label = "Linear trend + Fourier terms"
    family = "statistical"

    def __init__(
        self,
        season_length: int = 52,
        harmonics: int = DEFAULT_HARMONICS,
        ridge: float = DEFAULT_RIDGE,
    ) -> None:
        super().__init__()
        if season_length < 2:
            raise ValueError(f"season_length must be at least 2; got {season_length}.")
        if harmonics < 1:
            raise ValueError(f"harmonics must be at least 1; got {harmonics}.")
        if ridge < 0:
            raise ValueError(f"ridge must not be negative; got {ridge}.")

        self.season_length = int(season_length)
        self.requested_harmonics = int(harmonics)
        self.harmonics = min(int(harmonics), max_harmonics(int(season_length)))
        self.ridge = float(ridge)
        self.dropped_harmonics = False
        # The floor is what a *one-harmonic* fit needs: intercept, trend, one
        # sine and one cosine, plus slack so the fit is over-determined. It is
        # deliberately not 2K + 4 for the requested K - a short window should
        # degrade to fewer harmonics, which `_fit` does, rather than refuse to
        # run. Refusing would drop the model from the early CV folds entirely
        # and leave a hole in the results table that looks like a failure.
        self.min_observations = 6

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        values = y.to_numpy(dtype="float64")
        positions = np.arange(len(values), dtype="float64")
        usable = ~np.isnan(values)

        # Recomputed from the request on every fit, not carried over: the same
        # model object is refitted on a longer window at each CV fold, and a
        # reduction forced by fold 1 must not silently persist into fold 4.
        self.harmonics = min(self.requested_harmonics, max_harmonics(self.season_length))
        self.dropped_harmonics = False

        # Drop harmonics the sample cannot support, rather than returning a
        # fit whose coefficients are arbitrary.
        affordable = max(1, (int(usable.sum()) - 4) // 2)
        if affordable < self.harmonics:
            self.harmonics = affordable
            self.dropped_harmonics = True

        matrix = design_matrix(positions[usable], self.season_length, self.harmonics)
        target = values[usable]

        # Ridge on the harmonic columns only: penalising the intercept would
        # pull the whole forecast towards zero, and penalising the trend would
        # flatten a real trend towards zero for no reason.
        penalty = np.eye(matrix.shape[1]) * self.ridge
        penalty[0, 0] = 0.0
        penalty[1, 1] = 0.0

        gram = matrix.T @ matrix + penalty
        self._coefficients = np.linalg.solve(gram, matrix.T @ target)
        self._observations = len(values)

        full = design_matrix(positions, self.season_length, self.harmonics)
        self._fitted = pd.Series(full @ self._coefficients, index=y.index)

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        future = np.arange(self._observations, self._observations + horizon, dtype="float64")
        matrix = design_matrix(future, self.season_length, self.harmonics)
        return matrix @ self._coefficients

    def seasonal_shape(self) -> list[float]:
        """The fitted seasonal curve over one period, trend and level removed.

        This is what goes on the method card: the model's claim about what the
        year looks like, in a form a category manager can check against what
        they know about their own business.
        """
        positions = np.arange(self.season_length, dtype="float64")
        matrix = design_matrix(positions, self.season_length, self.harmonics)
        seasonal_only = matrix[:, 2:] @ self._coefficients[2:]
        return [float(v) for v in seasonal_only]

    def describe(self) -> dict[str, object]:
        record = super().describe()
        record["season_length"] = self.season_length
        record["harmonics"] = self.harmonics
        record["ridge"] = self.ridge
        if self.dropped_harmonics:
            record["harmonics_note"] = (
                f"Reduced from {self.requested_harmonics} to {self.harmonics}: the "
                f"training window was too short to estimate the requested number."
            )
        if self._history is not None:
            record["intercept"] = float(self._coefficients[0])
            record["trend_per_period"] = float(self._coefficients[1])
        record["literature_note"] = (
            "Chu & Zhang (2003) found trigonometric models were not useful for "
            "aggregate retail sales. This model is included as a hypothesis under "
            "test, not as a method the supplied literature endorses."
        )
        return record
