"""Reading dates without guessing.

03/04/2010 is 3 April in the UK and 4 March in the US. Guessing silently is the
single most damaging thing a data pipeline can do, because every later result
is wrong and nothing looks broken. So RetailPulse detects which formats *could*
be right, and if more than one fits, the user must choose (architecture §12.1).

Only explicit formats are tried - never pandas' free inference, which can parse
different rows with different rules inside the same column.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

# Each style is a list of concrete strptime patterns, tried in order.
DATE_FORMATS: dict[str, dict[str, object]] = {
    "iso": {
        "label": "Year-month-day (2010-04-03 14:30)",
        "example": "2010-04-03 14:30:00",
        "patterns": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"],
    },
    "dmy": {
        "label": "Day/month/year (03/04/2010 14:30)",
        "example": "03/04/2010 14:30",
        "patterns": ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                     "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y"],
    },
    "mdy": {
        "label": "Month/day/year (04/03/2010 14:30)",
        "example": "04/03/2010 14:30",
        "patterns": ["%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
                     "%m-%d-%Y %H:%M:%S", "%m-%d-%Y %H:%M", "%m-%d-%Y"],
    },
}

DATE_STYLES = list(DATE_FORMATS)


def parse_dates(values: pd.Series, style: str) -> pd.Series:
    """Parse a text column with one date style.

    Values that do not match any pattern of that style become NaT (not a time),
    which the cleaning pipeline then excludes and counts.
    """
    if style not in DATE_FORMATS:
        raise ValueError(f"Unknown date style: {style!r}. Expected one of {DATE_STYLES}.")

    text = values.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")

    for pattern in DATE_FORMATS[style]["patterns"]:
        remaining = parsed.isna() & text.notna()
        if not remaining.any():
            break
        attempt = pd.to_datetime(text[remaining], format=pattern, errors="coerce")
        parsed.loc[remaining] = attempt

    return parsed


def parse_rate(values: pd.Series, style: str) -> float:
    """Share of non-empty values this style can read (0.0 - 1.0)."""
    text = values.astype("string").str.strip()
    non_empty = text[text.notna() & (text != "")]
    if non_empty.empty:
        return 0.0
    return float(parse_dates(non_empty, style).notna().mean())


def detect_date_formats(
    values: Iterable, threshold: float = 0.95, sample_size: int = 1000
) -> dict[str, object]:
    """Which styles fit this column, and is the answer ambiguous?

    Ambiguous means day-first and month-first both parse the sample, e.g. a
    column whose days never exceed 12. The user has to decide.
    """
    series = pd.Series(list(values)[:sample_size], dtype="object")
    candidates = [style for style in DATE_STYLES if parse_rate(series, style) >= threshold]
    return {
        "candidates": candidates,
        "ambiguous": "dmy" in candidates and "mdy" in candidates,
    }


def last_complete_period(latest: pd.Timestamp, freq: str) -> pd.Timestamp:
    """Start of the last *complete* week (Monday) or month before `latest`.

    Online Retail II stops on Tuesday 9 December 2011, so its final week and
    month are partial. Counting them as whole periods makes the last point of
    every trend look like a collapse (architecture finding F9).
    """
    if freq == "week":
        week_start = latest.normalize() - pd.Timedelta(days=latest.weekday())
        # The week containing `latest` is complete only if it ends on or before it.
        return week_start if latest >= week_start + pd.Timedelta(days=6) else (
            week_start - pd.Timedelta(days=7)
        )
    if freq == "month":
        month_start = latest.normalize().replace(day=1)
        month_end = month_start + pd.offsets.MonthEnd(1)
        return month_start if latest >= month_end else (month_start - pd.offsets.MonthBegin(1))
    raise ValueError("freq must be 'week' or 'month'")
