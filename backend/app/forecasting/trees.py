"""Model 7: a global gradient-boosted tree model over engineered features.

**A deviation from §13.2, to state plainly in the report.** The architecture
names XGBoost. This implements the same model family with scikit-learn's
`HistGradientBoostingRegressor`, which is already a dependency, and registers
an XGBoost variant that activates only if the package is installed. Both are
histogram-based gradient boosting over decision trees; they differ in defaults
and regularisation, not in family. The reasons for the default:

* `requirements.txt` does not grow, and the result is reproducible on any
  machine that can already run the project;
* every number in the report can be regenerated without an optional install;
* the research question is whether a *tree family* beats statistical models on
  these series (RQ1), not whether one implementation beats another.

If XGBoost is installed, `xgboost_global` runs and both appear in the results
table. Auppakorn & Phumchusri (2022) found XGBoost best on their daily data
with a revenue-weighted MAPE of 16.7 against 17.35 for stepwise multiple
regression - and noted that the difference was small, concluding that "in case
that the case-study company is not ready for machine learning application, we
have found regression model can be a good fit". That margin is a useful prior
for what to expect here, and a reminder to report the size of a win and not
only its direction.

**Global, and what that changes.** One model is fitted across all selected
SKUs rather than one per SKU, because a single series has at most ~105 weekly
points. This is the only realistic way to fit a tree ensemble on this data, and
it makes the comparison local-statistical versus global-learned, which is a
different claim from model-versus-model on one series. Say so in the method.

**Uses exogenous features.** Unlike models 1-5, this one sees calendar
information. The results table carries that column (A1 §8.4) so the comparison
is not read as like-for-like.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from app.forecasting.base import Forecaster, register, requires
from app.forecasting.features import (
    FeatureSpec,
    ScalingStats,
    build_features,
    feature_names,
    fit_scaling,
)

# Conservative defaults for a few thousand rows. Deeper trees and more
# iterations overfit a dataset this size, and the point of the ladder is a fair
# comparison rather than a tuned champion.
DEFAULT_PARAMETERS: dict[str, Any] = {
    "max_depth": 4,
    "learning_rate": 0.05,
    "max_iter": 300,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 20260101,
}


class GlobalTreeModel:
    """Fit one model per horizon step across many series.

    Not a `Forecaster`: that interface is one series at a time, and the whole
    point here is pooling. The harness uses this directly for the global models
    and `Forecaster` for the local ones, and `evaluate.py` reconciles the two.
    """

    label = "Gradient-boosted trees (global)"
    uses_exogenous = True

    def __init__(
        self,
        spec: FeatureSpec | None = None,
        horizon: int = 12,
        parameters: dict[str, Any] | None = None,
        scale_per_series: bool = True,
    ) -> None:
        self.spec = spec or FeatureSpec()
        self.horizon = int(horizon)
        self.parameters = {**DEFAULT_PARAMETERS, **(parameters or {})}
        self.scale_per_series = bool(scale_per_series)
        self._models: dict[int, HistGradientBoostingRegressor] = {}
        self._scaling: ScalingStats | None = None
        self._columns: list[str] = []
        self.training_rows: dict[int, int] = {}

    def _make_estimator(self):
        return HistGradientBoostingRegressor(**self.parameters)

    def fit(self, panel: pd.DataFrame) -> "GlobalTreeModel":
        """`panel` is long: series_id, period, value - training rows only."""
        self._scaling = fit_scaling(panel) if self.scale_per_series else ScalingStats()
        scaled = self._scale(panel)

        for step in range(1, self.horizon + 1):
            spec = FeatureSpec(
                lags=self.spec.lags,
                rolling_windows=self.spec.rolling_windows,
                calendar=self.spec.calendar,
                horizon=step,
            )
            built = build_features(scaled, spec)
            self._columns = feature_names(spec)
            self.training_rows[step] = int(len(built))
            if built.empty:
                continue
            model = self._make_estimator()
            model.fit(built[self._columns].to_numpy(), built["y"].to_numpy())
            self._models[step] = model
        return self

    def predict(self, panel: pd.DataFrame, series_id: str) -> np.ndarray:
        """Forecast `horizon` steps beyond the end of this series' history.

        `panel` is the same long frame used for fitting, holding history only.
        Features are built from its final row, which is the last period the
        model is allowed to know about.
        """
        if self._scaling is None:
            raise RuntimeError("fit() must be called before predict().")

        scaled = self._scale(panel)
        series = scaled[scaled["series_id"].astype(str) == str(series_id)]
        if series.empty:
            raise KeyError(f"Series '{series_id}' is not in the supplied panel.")

        forecasts = np.full(self.horizon, np.nan, dtype="float64")
        for step in range(1, self.horizon + 1):
            model = self._models.get(step)
            if model is None:
                continue
            spec = FeatureSpec(
                lags=self.spec.lags,
                rolling_windows=self.spec.rolling_windows,
                calendar=self.spec.calendar,
                horizon=step,
            )
            row = _latest_feature_row(series, spec)
            if row is None:
                continue
            forecasts[step - 1] = float(model.predict(row[self._columns].to_numpy())[0])

        if self.scale_per_series and self._scaling is not None:
            forecasts = self._scaling.invert(str(series_id), forecasts)
        # A step whose model could not be fitted leaves a gap; carrying the last
        # usable value forward is better than returning NaN into the metrics,
        # and the gap is recorded in `describe`.
        return _fill_forward(forecasts)

    def _scale(self, panel: pd.DataFrame) -> pd.DataFrame:
        if not self.scale_per_series or self._scaling is None:
            return panel
        work = panel.copy()
        work["value"] = [
            float(self._scaling.apply(str(sid), np.array([value]))[0])
            for sid, value in zip(work["series_id"], work["value"], strict=True)
        ]
        return work

    def describe(self) -> dict[str, Any]:
        gaps = [step for step in range(1, self.horizon + 1) if step not in self._models]
        return {
            "model": "gbt_global",
            "label": self.label,
            "family": "tree",
            "uses_exogenous": True,
            "implementation": "sklearn.HistGradientBoostingRegressor",
            "parameters": dict(self.parameters),
            "feature_spec": self.spec.as_dict(),
            "scaled_per_series": self.scale_per_series,
            "training_rows_per_step": dict(self.training_rows),
            "steps_without_a_model": gaps,
            "deviation_note": (
                "§13.2 specifies XGBoost. This is the same model family from "
                "scikit-learn, which is already a dependency; the XGBoost variant "
                "runs as well when the optional package is installed."
            ),
        }


def _latest_feature_row(series: pd.DataFrame, spec: FeatureSpec) -> pd.DataFrame | None:
    """Build features for the most recent period, with no target.

    `build_features` drops rows with no target, which is every row at the end
    of the history - exactly the rows needed to forecast. So the target is
    appended as a placeholder, the features are built, and the placeholder is
    discarded. The features themselves never touch it.
    """
    padded = series.copy()
    last = padded["period"].max()
    step = pd.Series(padded["period"].sort_values().unique()).diff().median()
    if pd.isna(step):
        return None

    future = pd.DataFrame({
        "series_id": padded["series_id"].iloc[0],
        "period": [last + step * (i + 1) for i in range(spec.horizon)],
        "value": np.nan,
    })
    extended = pd.concat([padded, future], ignore_index=True)
    # Target the placeholder row so the feature row for `last` survives the
    # dropna; then take the features only.
    extended["value"] = extended["value"].fillna(0.0)
    built = build_features(extended, spec)
    if built.empty:
        return None
    return built.tail(1)


def _fill_forward(values: np.ndarray) -> np.ndarray:
    filled = values.copy()
    last_good = np.nan
    for i, value in enumerate(filled):
        if np.isnan(value):
            filled[i] = last_good
        else:
            last_good = value
    if np.isnan(filled).all():
        return np.zeros_like(filled)
    # Any leading gap takes the first usable value.
    first_good = filled[~np.isnan(filled)][0]
    return np.where(np.isnan(filled), first_good, filled)


@register
@requires("xgboost", "xgboost~=2.1")
class _XGBoostMarker(Forecaster):
    """Registry entry so the optional model is listed and reported as missing.

    The real fitting path for the global tree model is `GlobalTreeModel`; this
    exists so `available_models()` tells the truth about what can run before a
    long experiment starts, rather than failing an hour in.
    """

    name = "xgboost_global"
    label = "XGBoost (global)"
    family = "tree"
    uses_exogenous = True
    min_observations = 1

    def _fit(self, y: pd.Series, exog: pd.DataFrame | None) -> None:
        raise NotImplementedError(
            "XGBoost runs through GlobalTreeModel with implementation='xgboost', "
            "not through the single-series Forecaster interface."
        )

    def _predict(self, horizon: int, exog_future: pd.DataFrame | None) -> np.ndarray:
        raise NotImplementedError


class XGBoostGlobal(GlobalTreeModel):
    """The same harness, with XGBoost as the estimator. Optional."""

    label = "XGBoost (global)"

    def _make_estimator(self):
        try:
            from xgboost import XGBRegressor
        except ImportError as error:   # pragma: no cover - depends on the install
            raise ImportError(
                "XGBoost is not installed. Run the default gradient-boosted model, "
                "or `pip install xgboost~=2.1` to enable this one."
            ) from error

        return XGBRegressor(
            max_depth=self.parameters["max_depth"],
            learning_rate=self.parameters["learning_rate"],
            n_estimators=self.parameters["max_iter"],
            reg_lambda=self.parameters["l2_regularization"],
            min_child_weight=self.parameters["min_samples_leaf"],
            random_state=self.parameters["random_state"],
            tree_method="hist",
        )

    def describe(self) -> dict[str, Any]:
        record = super().describe()
        record["model"] = "xgboost_global"
        record["label"] = self.label
        record["implementation"] = "xgboost.XGBRegressor"
        record["deviation_note"] = None
        return record
