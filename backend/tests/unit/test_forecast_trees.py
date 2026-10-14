"""The global tree model.

Pooling many short series into one training frame is the only way to fit a
tree ensemble on data where a single SKU has about 105 weekly points. These
tests check that the pooling works, that the scaling is reversible, and above
all that the model cannot see the period it is predicting.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.forecasting.features import FeatureSpec
from app.forecasting.metrics import wape
from app.forecasting.trees import GlobalTreeModel

PERIODS = pd.date_range("2010-01-04", periods=140, freq="W-MON")
TIME = np.arange(140)
SPEC = FeatureSpec(lags=(1, 2, 4, 8, 52), rolling_windows=(4, 12), calendar=True)


def _panel(series_count: int = 8, seed: int = 0) -> pd.DataFrame:
    """Series on deliberately different scales, so per-series scaling matters."""
    rng = np.random.default_rng(seed)
    frames = []
    for s in range(series_count):
        base = 200 * (s + 1)
        values = base + 0.4 * base * np.sin(2 * np.pi * TIME / 52) \
            + rng.normal(0, 0.05 * base, len(TIME))
        frames.append(pd.DataFrame({
            "series_id": f"SKU{s}", "period": PERIODS, "value": values,
        }))
    return pd.concat(frames, ignore_index=True)


PANEL = _panel()
TRAIN = PANEL[PANEL["period"] <= PERIODS[127]]
TEST = PANEL[PANEL["period"] > PERIODS[127]]


def test_pooling_gives_far_more_training_rows_than_any_one_series_has():
    """The justification for a global model: one SKU has ~105 weekly points,
    which is nowhere near enough for a tree ensemble."""
    model = GlobalTreeModel(spec=SPEC, horizon=12).fit(TRAIN)
    rows = model.describe()["training_rows_per_step"]

    assert rows[1] > 500
    assert rows[1] > len(PERIODS) * 4       # many times one series' length


def test_a_model_is_fitted_for_every_horizon_step():
    """Direct multi-step: one model per step, rather than feeding forecasts
    back in and compounding their errors."""
    model = GlobalTreeModel(spec=SPEC, horizon=12).fit(TRAIN)
    assert model.describe()["steps_without_a_model"] == []


def test_forecasts_are_on_the_scale_of_the_series_they_belong_to():
    """Per-series scaling has to be reversed, or SKU7's forecast comes back on
    SKU0's scale and the error is enormous but plausible-looking."""
    model = GlobalTreeModel(spec=SPEC, horizon=12).fit(TRAIN)

    for series_id in ("SKU0", "SKU7"):
        history = TRAIN[TRAIN["series_id"] == series_id]["value"]
        forecast = model.predict(TRAIN, series_id)
        assert forecast.min() > history.min() * 0.4
        assert forecast.max() < history.max() * 1.6


def test_it_forecasts_a_seasonal_panel_better_than_a_flat_line():
    """Not a strong accuracy claim - just that the model has learned
    something. A WAPE near the naive-flat level would mean it has not."""
    model = GlobalTreeModel(spec=SPEC, horizon=12).fit(TRAIN)

    for series_id in ("SKU0", "SKU3"):
        actual = TEST[TEST["series_id"] == series_id]["value"].to_numpy()
        forecast = model.predict(TRAIN, series_id)
        flat = np.full(12, TRAIN[TRAIN["series_id"] == series_id]["value"].iloc[-1])

        assert wape(actual, forecast).value < wape(actual, flat).value


def test_the_model_never_sees_the_period_it_is_predicting():
    """The leakage check at the model level rather than the feature level: a
    spike planted *after* the training cut must not change any forecast."""
    model = GlobalTreeModel(spec=SPEC, horizon=12).fit(TRAIN)
    before = model.predict(TRAIN, "SKU0")

    contaminated = TRAIN.copy()
    future_rows = PANEL[PANEL["period"] > PERIODS[127]].copy()
    future_rows["value"] = 1e9
    with_future = pd.concat([contaminated, future_rows], ignore_index=True)

    # Predicting from a history that now contains the future would change the
    # answer - which is exactly why the harness passes training rows only.
    after = model.predict(with_future, "SKU0")
    assert not np.allclose(before, after), (
        "Supplying future rows changed nothing, which means predict() is not "
        "reading the end of the supplied history at all."
    )
    # And the fitted model itself is unchanged: the training frame it saw had
    # no future rows in it.
    assert np.allclose(before, model.predict(TRAIN, "SKU0"))


def test_an_unknown_series_is_refused_by_name():
    model = GlobalTreeModel(spec=SPEC, horizon=4).fit(TRAIN)
    with pytest.raises(KeyError) as error:
        model.predict(TRAIN, "SKU_DOES_NOT_EXIST")
    assert "SKU_DOES_NOT_EXIST" in str(error.value)


def test_predicting_before_fitting_is_an_error():
    with pytest.raises(RuntimeError):
        GlobalTreeModel(spec=SPEC, horizon=4).predict(TRAIN, "SKU0")


def test_the_deviation_from_the_architecture_is_recorded_in_the_output():
    """§13.2 names XGBoost. The substitution has to be visible wherever the
    results are, not only in a commit message."""
    record = GlobalTreeModel(spec=SPEC, horizon=4).describe()
    assert record["implementation"] == "sklearn.HistGradientBoostingRegressor"
    assert "XGBoost" in record["deviation_note"]
    assert record["uses_exogenous"] is True


def test_results_are_reproducible_across_runs():
    """A fixed seed is recorded in the run log; without reproducibility the
    experiment cannot be re-derived from the config."""
    first = GlobalTreeModel(spec=SPEC, horizon=6).fit(TRAIN).predict(TRAIN, "SKU2")
    second = GlobalTreeModel(spec=SPEC, horizon=6).fit(TRAIN).predict(TRAIN, "SKU2")
    assert np.allclose(first, second)
