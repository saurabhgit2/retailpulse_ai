"""Dates are the column most often read wrongly, so they get the most tests."""

from __future__ import annotations

import pandas as pd
import pytest

from app.preprocessing.dates import (
    detect_date_formats,
    last_complete_period,
    parse_dates,
    parse_rate,
)


def test_same_text_reads_differently_under_each_style():
    values = pd.Series(["03/04/2010"])
    assert parse_dates(values, "dmy").iloc[0] == pd.Timestamp("2010-04-03")
    assert parse_dates(values, "mdy").iloc[0] == pd.Timestamp("2010-03-04")


def test_impossible_dates_become_nat_rather_than_rolling_over():
    values = pd.Series(["31/02/2010", "2024-13-45 10:00:00"])
    assert parse_dates(values, "dmy").isna().all()
    assert parse_dates(values, "iso").isna().all()


def test_iso_timestamps_keep_their_time():
    parsed = parse_dates(pd.Series(["2009-12-01 07:45:00"]), "iso")
    assert parsed.iloc[0] == pd.Timestamp("2009-12-01 07:45:00")


def test_day_first_and_month_first_are_reported_as_ambiguous():
    result = detect_date_formats(["01/02/2010 08:26", "03/04/2010 09:00"])
    assert result["ambiguous"] is True
    assert set(result["candidates"]) == {"dmy", "mdy"}


def test_a_day_over_twelve_settles_the_ambiguity():
    result = detect_date_formats(["12/13/2010 08:26", "12/01/2010 09:00"])
    assert result["candidates"] == ["mdy"]
    assert result["ambiguous"] is False


def test_parse_rate_ignores_empty_values():
    assert parse_rate(pd.Series(["2010-01-01", "", None]), "iso") == 1.0


def test_unknown_style_is_rejected():
    with pytest.raises(ValueError):
        parse_dates(pd.Series(["2010-01-01"]), "yolo")


@pytest.mark.parametrize(
    ("latest", "expected_week"),
    [
        ("2011-12-09", "2011-11-28"),  # Friday: its week is incomplete
        ("2011-12-11", "2011-12-05"),  # Sunday: its week is complete
    ],
)
def test_last_complete_week(latest, expected_week):
    assert last_complete_period(pd.Timestamp(latest), "week") == pd.Timestamp(expected_week)


def test_last_complete_month():
    # Online Retail II stops on 9 December, so November is the last whole month.
    assert last_complete_period(pd.Timestamp("2011-12-09"), "month") == pd.Timestamp("2011-11-01")
    assert last_complete_period(pd.Timestamp("2011-11-30"), "month") == pd.Timestamp("2011-11-01")
