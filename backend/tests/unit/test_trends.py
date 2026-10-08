"""Time series assembly, partial periods, and the week-alignment trap."""

from __future__ import annotations

import pandas as pd
import pytest

from app.analytics.trends import build_trend, period_end, week_start

WEEKS = pd.date_range("2024-01-01", periods=10, freq="W-MON")  # Mondays
FRAME = pd.DataFrame({
    "period": WEEKS,
    "gross_revenue": [100, 110, 120, 130, 140, 150, 160, 170, 180, 90],
    "net_revenue": [95] * 10,
    "units": [10] * 10,
    "orders": [5] * 10,
})


def test_week_start_returns_mondays():
    """pandas' weekly aliases name the day a week ENDS on.

    `to_period("W-MON")` is the week *ending* Monday, so its start_time is a
    Tuesday - which silently misaligns against PostgreSQL's date_trunc('week')
    and against a date_range(freq="W-MON") reindex. This helper exists so that
    trap is in one place.
    """
    stamps = pd.Series(pd.to_datetime(["2024-01-03 10:00", "2024-01-08 10:00"]))
    starts = week_start(stamps)

    assert list(starts.dt.day_name()) == ["Monday", "Monday"]
    assert starts.iloc[0] == pd.Timestamp("2024-01-01")
    assert starts.iloc[1] == pd.Timestamp("2024-01-08")
    # The alias that *looks* right is the one that is wrong:
    assert stamps.dt.to_period("W-MON").dt.start_time.iloc[0].day_name() == "Tuesday"


def test_every_period_becomes_a_point():
    assert len(build_trend(FRAME, "week")["points"]) == 10


def test_a_bucket_extending_past_the_data_is_marked_partial():
    trend = build_trend(FRAME, "week", data_max=pd.Timestamp("2024-03-06 12:00"))
    partial = [point for point in trend["points"] if point["is_partial"]]

    assert partial, "the final week should be partial"
    assert partial[-1]["period"] == "2024-03-04"
    assert trend["partial_points"] == len(partial)


def test_growth_is_not_computed_across_a_partial_period():
    trend = build_trend(FRAME, "week", data_max=pd.Timestamp("2024-03-06 12:00"))
    partial = [point for point in trend["points"] if point["is_partial"]]
    assert all(point["growth"] is None for point in partial)


def test_moving_average_needs_a_full_window():
    trend = build_trend(FRAME, "week", ma_window=4)
    assert trend["points"][0]["moving_average"] is None
    assert trend["points"][3]["moving_average"] == pytest.approx(115.0)  # (100+110+120+130)/4


def test_growth_is_the_change_against_the_previous_period():
    trend = build_trend(FRAME, "week")
    assert trend["points"][1]["growth"] == pytest.approx(0.10)  # 110 vs 100


def test_missing_periods_are_filled_with_zero_rather_than_skipped():
    """A week with no sales is information, and a gap would make the moving
    average span unequal amounts of time."""
    gappy = pd.DataFrame({
        "period": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-15")],
        "gross_revenue": [100, 200],
    })
    points = build_trend(gappy, "week")["points"]

    assert len(points) == 3
    assert points[1]["gross_revenue"] == 0.0


def test_an_empty_frame_returns_an_empty_series_not_an_error():
    assert build_trend(pd.DataFrame(), "week")["points"] == []


def test_period_end_handles_month_lengths():
    assert period_end(pd.Timestamp("2024-02-01"), "month").date().isoformat() == "2024-02-29"


def test_an_unknown_granularity_is_rejected():
    with pytest.raises(ValueError):
        build_trend(FRAME, "fortnight")
