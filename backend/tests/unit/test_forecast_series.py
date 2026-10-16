"""Shaping a stored trend into a series a model can be fitted to.

Two things go wrong here and both are silent. A missing week shifts every lag
by one if it is simply absent. A partial final week looks like a collapse in
demand and is learned as one (finding F9). Neither raises; both change the
numbers.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.db.repositories.forecasts import (
    _drop_incomplete_final,
    _fill_period_gaps,
    _period_end,
)

WEEKS = pd.date_range("2010-01-04", periods=10, freq="W-MON")


def test_a_missing_week_is_filled_with_zero_and_counted():
    """Left absent, every lag after the gap would be off by one week."""
    with_gap = pd.Series(
        [100.0, 110.0, 130.0], index=[WEEKS[0], WEEKS[1], WEEKS[3]]
    )

    filled, added = _fill_period_gaps(with_gap, "week")

    assert added == 1
    assert len(filled) == 4
    assert filled.loc[WEEKS[2]] == 0.0
    assert list(filled.index) == list(WEEKS[:4])


def test_an_evenly_spaced_series_is_left_alone():
    series = pd.Series(range(10), index=WEEKS, dtype="float64")
    filled, added = _fill_period_gaps(series, "week")
    assert added == 0
    assert filled.equals(series)


def test_a_complete_final_week_is_kept():
    """Data running to the end of the last bucket means nothing is partial, and
    dropping it would throw away a real week."""
    series = pd.Series(range(10), index=WEEKS, dtype="float64")
    # The last bucket starts on WEEKS[-1] and ends seven days later.
    date_max = WEEKS[-1] + pd.Timedelta(days=6, hours=23)

    kept, dropped = _drop_incomplete_final(series, "week", date_max)

    assert dropped == 0
    assert len(kept) == 10


def test_a_partial_final_week_is_dropped():
    series = pd.Series(range(10), index=WEEKS, dtype="float64")
    date_max = WEEKS[-1] + pd.Timedelta(days=2)      # data stops mid-week

    kept, dropped = _drop_incomplete_final(series, "week", date_max)

    assert dropped == 1
    assert kept.index[-1] == WEEKS[-2]


def test_without_a_known_end_date_the_last_period_is_dropped_conservatively():
    """Keeping it would risk training on a partial week; the metadata records
    that the rule was applied without an end date."""
    series = pd.Series(range(10), index=WEEKS, dtype="float64")
    kept, dropped = _drop_incomplete_final(series, "week", None)
    assert dropped == 1


def test_a_series_too_short_to_trim_is_left_alone():
    series = pd.Series([1.0], index=WEEKS[:1])
    kept, dropped = _drop_incomplete_final(series, "week", None)
    assert dropped == 0
    assert len(kept) == 1


def test_month_ends_use_a_calendar_offset_not_thirty_one_days():
    """A fixed 31 days would mark February complete early and every other short
    month late."""
    assert _period_end(pd.Timestamp("2011-02-01"), "month") == pd.Timestamp("2011-03-01")
    assert _period_end(pd.Timestamp("2011-01-01"), "month") == pd.Timestamp("2011-02-01")


def test_a_february_month_is_complete_on_the_twenty_eighth():
    """The case a fixed 31-day period would get wrong: February 2011 ends on
    the 28th, so data to the 28th covers it."""
    series = pd.Series(
        [1.0, 2.0], index=pd.to_datetime(["2011-01-01", "2011-02-01"])
    )
    kept, dropped = _drop_incomplete_final(series, "month", pd.Timestamp("2011-02-28 17:30"))
    assert dropped == 0
    assert len(kept) == 2


def test_a_month_abandoned_mid_way_is_dropped():
    series = pd.Series(
        [1.0, 2.0], index=pd.to_datetime(["2011-01-01", "2011-02-01"])
    )
    kept, dropped = _drop_incomplete_final(series, "month", pd.Timestamp("2011-02-14"))
    assert dropped == 1


def test_a_retailer_closed_on_the_last_day_loses_its_final_period():
    """A documented, deliberate conservatism: Online Retail II does not trade
    on Saturdays, so a week whose last trading day is Friday reads as
    incomplete. It costs one period out of about a hundred, and the count is
    reported rather than hidden."""
    series = pd.Series(range(10), index=WEEKS, dtype="float64")
    friday = WEEKS[-1] + pd.Timedelta(days=4)

    _, dropped = _drop_incomplete_final(series, "week", friday)
    assert dropped == 1


@pytest.mark.parametrize("granularity", ["day", "week", "month", "year"])
def test_every_granularity_has_a_period_end(granularity):
    end = _period_end(pd.Timestamp("2011-06-06"), granularity)
    assert end > pd.Timestamp("2011-06-06")
