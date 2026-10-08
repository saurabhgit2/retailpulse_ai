"""Seasonal decomposition and calendar indices."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.seasonality import (
    calendar_indices,
    classical_decomposition,
    weekly_seasonality,
)

WEEKS = pd.date_range("2022-01-03", periods=156, freq="W-MON")  # three years
TIME = np.arange(156)
SEASONAL_SIGNAL = 1000 + 5 * TIME + 200 * np.sin(2 * np.pi * TIME / 52)


def _weekly(values, periods=156):
    return pd.DataFrame({"period": WEEKS[:periods], "gross_revenue": values[:periods]})


def test_a_known_yearly_cycle_is_detected():
    result = weekly_seasonality(_weekly(SEASONAL_SIGNAL))

    assert result["available"] is True
    assert result["period"] == 52
    assert result["seasonal_strength"] > 0.8


def test_the_trend_component_follows_the_underlying_growth():
    result = weekly_seasonality(_weekly(SEASONAL_SIGNAL))
    assert result["trend"][100] > result["trend"][30]


def test_a_seasonal_series_scores_far_higher_than_a_trend_only_one():
    """An absolute threshold would be misleading here: with only three cycles
    the seasonal component fits some noise even when there is no season, so
    what is meaningful is the gap between the two cases."""
    rng = np.random.default_rng(0)
    trend_only = 1000 + 5 * TIME + rng.normal(0, 20, len(TIME))

    seasonal = weekly_seasonality(_weekly(SEASONAL_SIGNAL))["seasonal_strength"]
    flat = weekly_seasonality(_weekly(trend_only))["seasonal_strength"]

    assert seasonal > 0.8
    assert seasonal - flat > 0.3


def test_the_trend_of_a_straight_line_is_that_line():
    """Alignment check: an off-by-one in the centred moving average would show
    up here as a constant offset."""
    line = pd.Series(np.arange(100, dtype=float))
    for period in (4, 5):  # even and odd windows are handled differently
        trend = classical_decomposition(line, period=period)["trend"]
        for index, value in enumerate(trend):
            if value is not None:
                assert value == pytest.approx(float(index))


def test_too_little_history_falls_back_to_a_quarterly_cycle():
    result = weekly_seasonality(_weekly(SEASONAL_SIGNAL, periods=40))
    assert result["period"] == 13
    assert "note" in result


def test_a_very_short_series_is_refused_with_a_reason():
    result = weekly_seasonality(_weekly(SEASONAL_SIGNAL, periods=5))
    assert result["available"] is False
    assert "observations" in result["reason"]


def test_thin_history_is_flagged_rather_than_quietly_reported():
    """Two cycles means two observations per seasonal phase; the component
    then fits noise, and anything reading the remainder has to know."""
    result = classical_decomposition(pd.Series(np.arange(120, dtype=float)), period=52)

    assert result["cycles"] == pytest.approx(120 / 52)
    assert result["weak_seasonal_estimate"] is True
    assert result["seasonal_estimate_note"]


def test_plenty_of_history_is_not_flagged():
    result = classical_decomposition(pd.Series(np.arange(210, dtype=float)), period=52)
    assert result["weak_seasonal_estimate"] is False


def test_one_extreme_period_distorts_the_seasonal_profile_it_belongs_to():
    """This is why anomaly detection does not reuse this function. The mean of
    a phase moves with a spike in it, and the distortion lands on that phase in
    every cycle - so a detector built on this would flag ordinary weeks a year
    either side of a real event."""
    contaminated = SEASONAL_SIGNAL.copy()
    contaminated[60] = 20_000

    clean = classical_decomposition(pd.Series(SEASONAL_SIGNAL, index=WEEKS), 52)
    spiked = classical_decomposition(pd.Series(contaminated, index=WEEKS), 52)

    # Observation 60 has phase 60 % 52 == 8, shared with observations 8 and 112.
    assert abs(spiked["seasonal"][8] - clean["seasonal"][8]) > 1000


def test_weekday_and_weekend_indices_reflect_trading_patterns():
    days = pd.date_range("2024-01-01", periods=140, freq="D")
    revenue = [300 if day.dayofweek < 5 else 60 for day in days]

    indices = calendar_indices(pd.DataFrame({"period": days, "gross_revenue": revenue}))
    by_day = {row["label"]: row["index"] for row in indices["day_of_week"]}

    assert by_day["Monday"] > 1.1
    assert by_day["Sunday"] < 0.6


def test_an_empty_frame_returns_empty_indices():
    assert calendar_indices(pd.DataFrame())["day_of_week"] == []


def test_the_deseasonalised_series_is_the_data_with_the_season_removed():
    """Chu and Zhang (2003) found the best aggregate retail model was a neural
    network fitted to deseasonalised data, and that prior seasonal adjustment
    significantly improved accuracy. Phase 5 needs this series, so Phase 4
    produces it rather than leaving it to be re-derived."""
    result = weekly_seasonality(_weekly(SEASONAL_SIGNAL))
    adjusted = np.array([np.nan if v is None else v for v in result["deseasonalised"]])
    observed = np.array(result["observed"])
    usable = ~np.isnan(adjusted)

    # The underlying trend is 1000 + 5t; removing the season should leave the
    # adjusted series much closer to it than the raw series is.
    trend = 1000 + 5 * TIME
    assert np.std(adjusted[usable] - trend[usable]) < np.std(observed[usable] - trend[usable]) / 3
    assert np.std(adjusted[usable]) < np.std(observed[usable])
