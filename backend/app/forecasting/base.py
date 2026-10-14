"""The one interface every model implements, and the registry that lists them.

Every model in the ladder - a one-line naive rule and a gradient-boosted
ensemble alike - is used the same way:

    model = get_model("seasonal_naive", season_length=52)
    model.fit(train)
    result = model.predict(horizon=12)

That uniformity is what makes the comparison fair. A harness that had to know
which model it was running could, without anyone intending it, give one of them
an advantage - an extra fitting pass, a different treatment of the last
observation - and the results table would be measuring the harness.

**Declared, not inferred.** Each model states its own `min_observations`,
whether it `uses_exogenous` features, and whether its dependencies are
installed. The architecture requires the results table to carry an "uses
exogenous features" column, because a model given price information is not
competing on equal terms with one that is not (A1 §8.4), and that column is
filled from this attribute rather than from memory.

**Optional dependencies.** statsmodels (ARIMA) and xgboost are not in
`requirements.txt`: the ladder runs without them on numpy, scipy and
scikit-learn alone. A model whose library is missing reports
`is_available() == False` with a reason, and the harness skips it and records
the skip. It never crashes a run that was going to take an hour, and it never
silently substitutes something else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd


class NotFittedError(RuntimeError):
    """predict() was called before fit(). Always a bug in the caller."""


@dataclass(frozen=True)
class ForecastResult:
    """A point forecast, optional interval, and how it was produced."""

    model: str
    point: np.ndarray
    lower: np.ndarray | None = None
    upper: np.ndarray | None = None
    index: pd.Index | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def horizon(self) -> int:
        return int(len(self.point))

    def as_series(self) -> pd.Series:
        return pd.Series(self.point, index=self.index, name=self.model)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "horizon": self.horizon,
            "point": [float(v) for v in self.point],
            "lower": None if self.lower is None else [float(v) for v in self.lower],
            "upper": None if self.upper is None else [float(v) for v in self.upper],
            "index": None if self.index is None else [str(i) for i in self.index],
            "metadata": self.metadata,
        }


class Forecaster(ABC):
    """Fit on a history, predict a horizon. Everything else is detail."""

    name: str = "forecaster"
    label: str = "Forecaster"
    family: str = "baseline"
    uses_exogenous: bool = False
    min_observations: int = 1

    def __init__(self) -> None:
        self._fitted: pd.Series | None = None
        self._history: pd.Series | None = None

    # -- the two methods a model must provide ----------------------------

    @abstractmethod
    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        """Estimate whatever this model estimates. Called by `fit`."""

    @abstractmethod
    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        """Point forecasts for the next `horizon` periods, oldest first."""

    # -- the uniform surface the harness uses ----------------------------

    def fit(self, y: pd.Series, exog: pd.DataFrame | None = None) -> "Forecaster":
        series = _clean_history(y)
        if len(series) < self.min_observations:
            raise ValueError(
                f"{self.label} needs at least {self.min_observations} observations; "
                f"the training window has {len(series)}."
            )
        self._history = series
        self._fit(series, exog)
        return self

    def predict(
        self, horizon: int, exog_future: pd.DataFrame | None = None
    ) -> ForecastResult:
        if self._history is None:
            raise NotFittedError(f"{self.label}: fit() must be called before predict().")
        if horizon < 1:
            raise ValueError(f"Horizon must be at least 1; got {horizon}.")

        point = np.asarray(self._predict(horizon, exog_future), dtype="float64")
        if point.shape != (horizon,):
            raise ValueError(
                f"{self.label} returned {point.shape[0]} values for a horizon of "
                f"{horizon}. This is a bug in the model, not in the data."
            )
        return ForecastResult(
            model=self.name,
            point=point,
            index=self._future_index(horizon),
            metadata=self.describe(),
        )

    # -- shared helpers --------------------------------------------------

    @property
    def history(self) -> pd.Series:
        if self._history is None:
            raise NotFittedError(f"{self.label}: fit() must be called first.")
        return self._history

    def fitted_values(self) -> pd.Series | None:
        """In-sample one-step predictions, where the model can produce them.

        Used by `intervals.py` to size prediction intervals from residuals. A
        model that cannot produce them returns None and gets its intervals from
        cross-validation residuals instead.
        """
        return self._fitted

    def residuals(self) -> pd.Series | None:
        fitted = self.fitted_values()
        if fitted is None or self._history is None:
            return None
        return (self._history - fitted).dropna()

    def describe(self) -> dict[str, Any]:
        """What went into this fit, for the run log and the method card."""
        return {
            "model": self.name,
            "label": self.label,
            "family": self.family,
            "uses_exogenous": self.uses_exogenous,
            "min_observations": self.min_observations,
        }

    def _future_index(self, horizon: int) -> pd.Index | None:
        """Continue the training index by `horizon` steps, if it can be continued."""
        index = self.history.index
        if not isinstance(index, pd.DatetimeIndex) or len(index) < 2:
            return None
        freq = index.freq or pd.infer_freq(index)
        if freq is None:
            # Irregular spacing: fall back to the median gap rather than guess a
            # calendar rule, and say so by returning plain timestamps.
            step = pd.Series(index).diff().median()
            return pd.DatetimeIndex([index[-1] + step * (i + 1) for i in range(horizon)])
        return pd.date_range(index[-1], periods=horizon + 1, freq=freq)[1:]

    @classmethod
    def is_available(cls) -> tuple[bool, str | None]:
        """Whether this model's dependencies are installed.

        Returns (True, None) or (False, reason). Overridden by the models that
        need an optional library.
        """
        return True, None


def _clean_history(y: pd.Series) -> pd.Series:
    """A float series, sorted, with leading and trailing gaps removed.

    Interior NaNs are left alone: a missing week in the middle is information,
    and each model decides what to do about it. Dropping them here would
    silently shorten the series and shift every lag.
    """
    series = pd.Series(y).astype("float64")
    if isinstance(series.index, pd.DatetimeIndex) and not series.index.is_monotonic_increasing:
        raise ValueError(
            "The training series must be sorted in time. Sorting it inside the "
            "model would hide an ordering bug in whatever produced it."
        )
    return series.loc[series.first_valid_index():series.last_valid_index()] if series.notna().any() else series


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[Forecaster]] = {}


def register(model: type[Forecaster]) -> type[Forecaster]:
    """Class decorator. Makes a model addressable by name from a config file."""
    if model.name in _REGISTRY and _REGISTRY[model.name] is not model:
        raise ValueError(
            f"Two models claim the name '{model.name}'. Names appear in research "
            f"configs and in the results table, so they have to be unique."
        )
    _REGISTRY[model.name] = model
    return model


def get_model(name: str, **kwargs: Any) -> Forecaster:
    """Build a model by the name a config file uses."""
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "none registered"
        raise KeyError(f"Unknown model '{name}'. Registered models: {known}.")
    return _REGISTRY[name](**kwargs)


def model_class(name: str) -> type[Forecaster]:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown model '{name}'.")
    return _REGISTRY[name]


def available_models() -> list[dict[str, Any]]:
    """Every registered model, and whether it can actually run here.

    The research CLI prints this before a run, so a missing optional library is
    discovered in the first second rather than an hour in.
    """
    rows = []
    for name, cls in sorted(_REGISTRY.items()):
        ready, reason = cls.is_available()
        rows.append({
            "model": name,
            "label": cls.label,
            "family": cls.family,
            "uses_exogenous": cls.uses_exogenous,
            "min_observations": cls.min_observations,
            "available": ready,
            "unavailable_reason": reason,
        })
    return rows


def requires(module: str, extra: str) -> Callable[[type[Forecaster]], type[Forecaster]]:
    """Attach an optional-dependency check to a model class."""

    def decorate(cls: type[Forecaster]) -> type[Forecaster]:
        def is_available() -> tuple[bool, str | None]:
            try:
                __import__(module)
            except ImportError:
                return False, (
                    f"{cls.label} needs the optional package '{module}', which is "
                    f"not installed. Install it with `pip install {extra}` and "
                    f"re-run; the rest of the ladder runs without it."
                )
            return True, None

        cls.is_available = staticmethod(is_available)   # type: ignore[assignment]
        return cls

    return decorate
