"""Feature building, and the leakage tests.

If one of these fails, every accuracy number produced by the tree model is
worthless, because the model will have been scored on data it was shown. They
are cheap to run and they are the evidence behind the claim in the methodology
chapter that the protocol prevents leakage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.forecasting.features import (
    FeatureSpec,
    build_features,
    describe_coverage,
    feature_names,
    fit_scaling,
)

PERIODS = pd.date_range("2010-01-04", periods=120, freq="W-MON")


def _panel(series_count: int = 3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for s in range(series_count):
        frames.append(pd.DataFrame({
            "series_id": f"SKU{s}",
            "period": PERIODS,
            "value": 100 * (s + 1) + rng.normal(0, 10, len(PERIODS)).cumsum(),
        }))
    return pd.concat(frames, ignore_index=True)


SPEC = FeatureSpec(lags=(1, 2, 4), rolling_windows=(4,), calendar=True, horizon=1)


def test_a_spike_in_the_future_cannot_reach_any_feature_of_an_earlier_row():
    """The central leakage test. A single enormous value is planted at one
    period; no feature row dated before it may change."""
    clean = _panel(series_count=1)
    contaminated = clean.copy()
    spike_at = 80
    contaminated.loc[spike_at, "value"] = 1e9

    before = build_features(clean, SPEC)
    after = build_features(contaminated, SPEC)

    spike_period = clean.loc[spike_at, "period"]
    columns = feature_names(SPEC)

    earlier_before = before[before["period"] < spike_period][columns].reset_index(drop=True)
    earlier_after = after[after["period"] < spike_period][columns].reset_index(drop=True)

    # The target y of the row immediately before the spike IS the spike at
    # horizon 1, which is correct - that is the thing being predicted. The
    # features must be untouched.
    pd.testing.assert_frame_equal(earlier_before, earlier_after)


def test_the_rolling_mean_excludes_the_current_period():
    """`y.rolling(4).mean().shift(1)` and `y.shift(1).rolling(4).mean()` differ
    by exactly one observation and look nearly identical in a diff. This
    pins down which one is in use."""
    frame = pd.DataFrame({
        "series_id": "A",
        "period": PERIODS[:20],
        "value": np.arange(20, dtype=float),
    })

    built = build_features(frame, FeatureSpec(lags=(1,), rolling_windows=(4,), calendar=False))
    row = built[built["period"] == PERIODS[10]].iloc[0]

    # Value at period 10 is 10.0. A past-only 4-window mean is of 6,7,8,9.
    assert row["roll_mean_4"] == pytest.approx(np.mean([6, 7, 8, 9]))
    assert row["roll_mean_4"] != pytest.approx(np.mean([7, 8, 9, 10]))


def test_lag_k_is_exactly_the_value_k_periods_earlier():
    frame = pd.DataFrame({
        "series_id": "A",
        "period": PERIODS[:20],
        "value": np.arange(20, dtype=float) * 3,
    })
    built = build_features(frame, FeatureSpec(lags=(1, 2, 4), rolling_windows=(), calendar=False))
    row = built[built["period"] == PERIODS[10]].iloc[0]

    assert row["lag_1"] == pytest.approx(9 * 3)
    assert row["lag_2"] == pytest.approx(8 * 3)
    assert row["lag_4"] == pytest.approx(6 * 3)


def test_the_target_is_the_value_h_periods_ahead():
    frame = pd.DataFrame({
        "series_id": "A",
        "period": PERIODS[:30],
        "value": np.arange(30, dtype=float),
    })
    built = build_features(frame, FeatureSpec(lags=(1,), rolling_windows=(), calendar=False, horizon=6))
    row = built[built["period"] == PERIODS[10]].iloc[0]
    assert row["y"] == pytest.approx(16.0)


def test_features_never_cross_from_one_series_into_another():
    """A groupby omitted anywhere in this module would make SKU1's last week
    the lag of SKU2's first, and the error would be invisible in the output."""
    panel = pd.DataFrame({
        "series_id": ["A"] * 10 + ["B"] * 10,
        "period": list(PERIODS[:10]) * 2,
        "value": [1.0] * 10 + [1000.0] * 10,
    })

    built = build_features(panel, FeatureSpec(lags=(1,), rolling_windows=(), calendar=False))
    first_b = built[built["series_id"] == "B"].iloc[0]

    assert first_b["lag_1"] == pytest.approx(1000.0)     # not 1.0 from series A


def test_rows_without_complete_features_are_dropped_not_filled():
    """Filling a missing lag with zero would teach the model that early weeks
    had no sales."""
    frame = pd.DataFrame({
        "series_id": "A",
        "period": PERIODS[:30],
        "value": np.arange(30, dtype=float),
    })
    built = build_features(frame, FeatureSpec(lags=(52,), rolling_windows=(), calendar=False))
    assert built.empty       # a lag of 52 on 30 observations leaves nothing


def test_the_number_of_usable_rows_is_recoverable():
    """A model silently trained on 40 rows because a lag of 52 was requested on
    a two-year series is a failure worth noticing."""
    panel = _panel(series_count=2)
    spec = FeatureSpec(lags=(1, 52), rolling_windows=(), calendar=False)
    built = build_features(panel, spec)

    assert len(built) < len(panel)
    assert len(built) == 2 * (len(PERIODS) - 52 - 1)


def test_calendar_features_encode_the_year_without_a_seam_at_week_52():
    frame = pd.DataFrame({
        "series_id": "A",
        "period": PERIODS[:60],
        "value": np.arange(60, dtype=float),
    })
    built = build_features(frame, FeatureSpec(lags=(1,), rolling_windows=(), calendar=True))

    assert {"week_sin", "week_cos", "month", "day_of_week"} <= set(built.columns)
    assert built["week_sin"].between(-1, 1).all()
    # Weeks 1 and 52 should be neighbours in the encoding, not opposite ends.
    week_1 = built[built["week_of_year"] == 1].iloc[0]
    week_52 = built[built["week_of_year"] == 52].iloc[0]
    distance = np.hypot(week_1["week_sin"] - week_52["week_sin"],
                        week_1["week_cos"] - week_52["week_cos"])
    assert distance < 0.3


def test_feature_names_are_stable_so_fit_and_predict_cannot_be_misaligned():
    spec = FeatureSpec(lags=(1, 4), rolling_windows=(4, 12), calendar=True)
    assert feature_names(spec) == feature_names(spec)
    assert feature_names(spec)[:2] == ["lag_1", "lag_4"]


def test_scaling_statistics_come_from_the_training_rows_only():
    """If the scaler saw the test window, the model would know the test
    window's level before predicting it."""
    panel = _panel(series_count=1)
    training = panel.iloc[:80]
    full = panel

    from_training = fit_scaling(training)
    from_everything = fit_scaling(full)

    assert from_training.centre["SKU0"] != pytest.approx(from_everything.centre["SKU0"])


def test_scaling_uses_the_median_so_one_spike_barely_moves_it():
    """The claim is robustness *relative to the mean*, which is why median and
    IQR were chosen over mean and standard deviation: a single promotional week
    should not decide the scale every other week is divided by."""
    rng = np.random.default_rng(0)
    values = 100 + rng.normal(0, 5, 200)
    ordinary = pd.DataFrame({"series_id": "A", "value": values})
    spiked = ordinary.copy()
    spiked.loc[0, "value"] = 1e6

    median_shift = abs(fit_scaling(spiked).centre["A"] - fit_scaling(ordinary).centre["A"])
    mean_shift = abs(spiked["value"].mean() - ordinary["value"].mean())

    assert median_shift < 1.0            # the median hardly notices
    assert mean_shift > 1000.0           # the mean is destroyed
    assert median_shift < mean_shift / 1000


def test_scaling_round_trips():
    stats = fit_scaling(_panel(series_count=1))
    values = np.array([150.0, 200.0, 250.0])
    assert np.allclose(stats.invert("SKU0", stats.apply("SKU0", values)), values)


def test_a_constant_series_does_not_produce_a_zero_divisor():
    flat = pd.DataFrame({"series_id": "A", "value": [42.0] * 30})
    stats = fit_scaling(flat)
    assert stats.spread["A"] > 0
    assert np.all(np.isfinite(stats.apply("A", np.array([42.0, 43.0]))))


def test_features_outside_the_training_range_are_reported():
    """Auppakorn & Phumchusri found adding COVID case counts made their model
    worse, because the validation period held values training never saw. A tree
    cannot extrapolate past its splits, so this condition is worth surfacing."""
    training = pd.DataFrame({"covid_cases": [0, 10, 20, 30]})
    future = pd.DataFrame({"covid_cases": [5, 500, 900]})

    report = describe_coverage(training, future, ["covid_cases"])
    entry = report["features_outside_training_range"][0]

    assert entry["rows_outside_training_range"] == 2
    assert entry["share_outside"] == pytest.approx(2 / 3)
    assert "cannot extrapolate" in report["note"]


def test_nothing_is_reported_when_every_input_is_inside_the_training_range():
    training = pd.DataFrame({"price": [1.0, 5.0]})
    future = pd.DataFrame({"price": [2.0, 3.0]})
    report = describe_coverage(training, future, ["price"])

    assert report["features_outside_training_range"] == []
    assert report["note"] is None


def test_a_missing_required_column_names_what_is_missing():
    with pytest.raises(KeyError) as error:
        build_features(pd.DataFrame({"series_id": ["A"], "period": PERIODS[:1]}), SPEC)
    assert "value" in str(error.value)
