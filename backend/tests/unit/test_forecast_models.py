"""The model ladder: does each model do what its name claims?

These are behavioural tests on constructed series where the right answer is
known, not accuracy tests. Whether ETS beats seasonal naive on Online Retail II
is a research question; whether seasonal naive repeats last season is a fact
that has to hold or the whole comparison is measuring something else.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import app.forecasting  # noqa: F401  - registers the models
from app.forecasting.base import NotFittedError, available_models, get_model
from app.forecasting.baselines import Drift, MovingAverage, Naive, SeasonalNaive
from app.forecasting.ets import DampedETS
from app.forecasting.fourier import FourierRegression, max_harmonics

WEEKS = pd.date_range("2010-01-04", periods=156, freq="W-MON")
TIME = np.arange(156)
SEASONAL = pd.Series(1000 + 5 * TIME + 200 * np.sin(2 * np.pi * TIME / 52), index=WEEKS)


def test_naive_repeats_the_last_value():
    model = Naive().fit(SEASONAL)
    forecast = model.predict(5).point
    assert np.allclose(forecast, SEASONAL.iloc[-1])


def test_seasonal_naive_repeats_the_matching_week_of_last_season():
    model = SeasonalNaive(season_length=52).fit(SEASONAL)
    forecast = model.predict(12).point
    assert np.allclose(forecast, SEASONAL.iloc[-52:-40].to_numpy())


def test_seasonal_naive_falls_back_to_naive_and_says_so():
    """Two years of weekly data means the early CV folds have less than one
    season. The fallback must be visible in the results table, or 'seasonal
    naive' silently means two different models in one column."""
    short = SEASONAL.iloc[:30]
    model = SeasonalNaive(season_length=52).fit(short)

    assert model.fell_back is True
    assert np.allclose(model.predict(4).point, short.iloc[-1])
    assert "shorter than one season" in model.describe()["fallback_note"]


def test_a_full_season_of_history_does_not_trigger_the_fallback():
    model = SeasonalNaive(season_length=52).fit(SEASONAL.iloc[:52])
    assert model.fell_back is False


def test_the_moving_average_is_flat_and_equals_the_mean_of_its_window():
    model = MovingAverage(window=4).fit(SEASONAL)
    forecast = model.predict(6).point
    assert len(set(np.round(forecast, 9))) == 1
    assert forecast[0] == pytest.approx(SEASONAL.iloc[-4:].mean())


def test_drift_extends_the_average_slope():
    line = pd.Series(np.arange(50, dtype=float), index=pd.date_range("2020-01-06", periods=50, freq="W-MON"))
    forecast = Drift().fit(line).predict(3).point
    assert np.allclose(forecast, [50.0, 51.0, 52.0])


def test_fourier_recovers_a_clean_sinusoid_almost_exactly():
    """If it cannot fit a noiseless sine wave, nothing it says about real data
    is worth reading."""
    model = FourierRegression(season_length=52, harmonics=1).fit(SEASONAL.iloc[:104])
    forecast = model.predict(12).point
    expected = SEASONAL.iloc[104:116].to_numpy()
    assert np.max(np.abs(forecast - expected)) < 1.0


def test_fourier_harmonics_are_capped_below_the_nyquist_limit():
    """Above m/2 the extra columns are aliases of lower frequencies and make
    the design matrix singular."""
    assert max_harmonics(52) == 26
    model = FourierRegression(season_length=12, harmonics=40)
    assert model.harmonics == 6


def test_fourier_reduces_its_harmonics_on_a_short_window_and_records_it():
    model = FourierRegression(season_length=52, harmonics=10).fit(SEASONAL.iloc[:18])
    assert model.dropped_harmonics is True
    assert "Reduced from 10" in model.describe()["harmonics_note"]


def test_fourier_carries_the_contrary_finding_in_its_metadata():
    """Chu & Zhang found trigonometric models unhelpful for aggregate retail
    sales. A reader of the results should meet that where the model is
    described, not only in the discussion chapter."""
    note = FourierRegression().describe()["literature_note"]
    assert "Chu & Zhang" in note and "not useful" in note


def test_ets_tracks_a_level_shift_rather_than_averaging_across_it():
    level_shift = pd.Series([100.0] * 40 + [200.0] * 40)
    forecast = DampedETS().fit(level_shift).predict(4).point
    assert forecast.min() > 150        # has moved to the new level


def test_the_damped_trend_does_not_run_away():
    """The reason for damping: an undamped trend fitted to a short rising
    series produces forecasts that are indefensible at horizon 12."""
    rising = pd.Series(np.arange(60, dtype=float) * 10)
    model = DampedETS().fit(rising)

    short = model.predict(1).point[-1]
    long = model.predict(40).point[-1]
    undamped_at_40 = rising.iloc[-1] + 10 * 40

    assert long > short                      # still trending
    assert long < undamped_at_40             # but decaying
    assert model.parameters["phi"] < 1.0


def test_ets_estimates_parameters_inside_their_bounds():
    model = DampedETS().fit(SEASONAL)
    for name in ("alpha", "beta", "phi"):
        assert 0 < model.parameters[name] < 1


def test_a_seasonal_ets_needs_two_full_cycles():
    model = DampedETS(season_length=52, seasonal=True)
    assert model.min_observations == 106
    with pytest.raises(ValueError) as error:
        model.fit(SEASONAL.iloc[:60])
    assert "at least 106" in str(error.value)


def test_seasonal_ets_beats_non_seasonal_on_a_strongly_seasonal_series():
    train, test = SEASONAL.iloc[:130], SEASONAL.iloc[130:142]
    plain = DampedETS().fit(train).predict(12).point
    seasonal = DampedETS(season_length=52, seasonal=True).fit(train).predict(12).point

    actual = test.to_numpy()
    assert np.mean(np.abs(seasonal - actual)) < np.mean(np.abs(plain - actual))


def test_predicting_before_fitting_is_an_error_not_a_zero():
    with pytest.raises(NotFittedError):
        Naive().predict(3)


def test_the_future_index_continues_the_training_index():
    result = Naive().fit(SEASONAL).predict(3)
    assert list(result.index) == list(pd.date_range(WEEKS[-1], periods=4, freq="W-MON")[1:])


def test_every_model_is_reachable_by_the_name_a_config_file_uses():
    for name in ("naive", "seasonal_naive", "moving_average", "drift", "fourier", "ets"):
        assert get_model(name) is not None


def test_an_unknown_model_name_lists_the_known_ones():
    with pytest.raises(KeyError) as error:
        get_model("prophet")
    assert "seasonal_naive" in str(error.value)


def test_optional_dependencies_are_reported_before_a_run_not_during_one():
    rows = {row["model"]: row for row in available_models()}
    assert rows["naive"]["available"] is True

    xgb = rows["xgboost_global"]
    if not xgb["available"]:
        assert "xgboost" in xgb["unavailable_reason"]
        assert "pip install" in xgb["unavailable_reason"]


def test_the_results_table_can_tell_which_models_saw_exogenous_features():
    """A1 §8.4: a model given calendar or price information is not competing on
    equal terms with one that is not."""
    rows = {row["model"]: row for row in available_models()}
    assert rows["ets"]["uses_exogenous"] is False
    assert rows["xgboost_global"]["uses_exogenous"] is True
