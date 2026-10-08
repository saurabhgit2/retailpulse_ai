"""Anomaly detection.

The tests here are mostly about **false positives**, because that is where the
first three attempts at this module failed. Each one encodes a specific way a
mean-based detector fools itself; the comments say which.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.anomalies import MIN_CYCLES_FOR_SEASONAL, detect_anomalies


def _series(periods: int, seed: int, spikes: dict[int, float] | None = None, noise: float = 10.0):
    rng = np.random.default_rng(seed)
    values = 1000 + 50 * np.sin(2 * np.pi * np.arange(periods) / 52) + rng.normal(0, noise, periods)
    for index, value in (spikes or {}).items():
        values[index] = value
    return pd.DataFrame({
        "period": pd.date_range("2022-01-03", periods=periods, freq="W-MON"),
        "gross_revenue": values,
    })


def _periods_of(result):
    return {row["period"] for row in result["anomalies"]}


def test_a_clear_spike_is_found():
    frame = _series(520, 9, {300: 4000})
    result = detect_anomalies(frame)

    assert result["available"] is True
    assert frame["period"].iloc[300].date().isoformat() in _periods_of(result)


def test_a_collapse_is_found_as_well_as_a_spike():
    frame = _series(520, 9, {300: 100})
    assert frame["period"].iloc[300].date().isoformat() in _periods_of(detect_anomalies(frame))


def test_a_clean_series_stays_quiet():
    """The detector must not cry wolf on ordinary noise."""
    assert detect_anomalies(_series(520, 5))["anomaly_rate"] < 0.03


def test_short_history_does_not_use_a_seasonal_profile():
    """A 52-phase profile fitted to two cycles has two observations per phase,
    so it absorbs the noise and the residuals lose any stable scale. Measured:
    47% of ordinary periods came back flagged."""
    result = detect_anomalies(_series(120, 3, {60: 5000}))

    assert "rolling median" in result["basis"]
    assert result["anomaly_rate"] < 0.05
    assert result["periods_assessed"] > 0


def test_plenty_of_history_does_use_a_seasonal_profile():
    result = detect_anomalies(_series(52 * MIN_CYCLES_FOR_SEASONAL + 10, 9))
    assert "seasonal profile" in result["basis"]


def test_multiplicative_seasonality_with_growth_is_not_flagged_as_anomalous():
    """December at three times the level is the pattern, not an anomaly - and
    an additive seasonal offset cannot track it while the level grows, so every
    December gets flagged. The baseline is a ratio when the series allows it."""
    rng = np.random.default_rng(1)
    periods = 520
    dates = pd.date_range("2014-01-06", periods=periods, freq="W-MON")
    level = 1000 + 2 * np.arange(periods)
    december = np.array([3.0 if date.month == 12 else 1.0 for date in dates])
    values = level * december * rng.normal(1, 0.03, periods)

    result = detect_anomalies(pd.DataFrame({"period": dates, "gross_revenue": values}))

    assert result["scored_on"].startswith("proportional")
    assert result["anomaly_rate"] < 0.03


def test_a_real_anomaly_inside_a_seasonal_series_is_still_found():
    rng = np.random.default_rng(1)
    periods = 520
    dates = pd.date_range("2014-01-06", periods=periods, freq="W-MON")
    level = 1000 + 2 * np.arange(periods)
    december = np.array([3.0 if date.month == 12 else 1.0 for date in dates])
    values = level * december * rng.normal(1, 0.03, periods)
    values[300] *= 2.5

    result = detect_anomalies(pd.DataFrame({"period": dates, "gross_revenue": values}))
    assert dates[300].date().isoformat() in _periods_of(result)


def test_a_constant_series_cannot_contain_an_anomaly():
    frame = pd.DataFrame({
        "period": pd.date_range("2022-01-03", periods=60, freq="W-MON"),
        "gross_revenue": [100.0] * 60,
    })
    assert detect_anomalies(frame)["available"] is False


def test_too_few_periods_is_refused():
    frame = pd.DataFrame({
        "period": pd.date_range("2022-01-03", periods=4, freq="W-MON"),
        "gross_revenue": [1.0, 2.0, 3.0, 4.0],
    })
    assert detect_anomalies(frame)["available"] is False


def test_every_anomaly_explains_itself_in_a_sentence():
    result = detect_anomalies(_series(520, 9, {300: 4000}))
    explanation = result["anomalies"][0]["explanation"]
    assert "robust standard deviations" in explanation
    assert result["anomalies"][0]["direction"] in {"above", "below"}


def test_anomalies_are_returned_worst_first():
    result = detect_anomalies(_series(520, 9, {300: 4000}))
    scores = [row["robust_z"] for row in result["anomalies"]]
    assert scores == sorted(scores, reverse=True)
