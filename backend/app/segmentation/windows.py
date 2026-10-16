"""Time windows: the same customers, measured from several as-of dates.

RQ2 asks whether segments are stable. Stability is only measurable if there is
more than one segmentation to compare, so the first thing this package needs is
a set of as-of dates and the rule that produced them.

**Why the windows end at different dates rather than covering different
periods.** RFM is defined relative to an as-of date: recency is "days since the
last purchase, measured from here". Two windows that *end* at different points
therefore give two different RFM snapshots of overlapping customer populations
- which is exactly the comparison that matters, because it asks whether a
customer's segment changes as time passes rather than whether two disjoint
groups of customers differ.

Two shapes are offered and the choice must be declared in the config:

* **expanding** - every window starts at the beginning of the data and ends at
  a later date. A customer's history accumulates. This is what a business
  actually sees: on any given Monday you know everything up to that Monday.
* **rolling** - every window is the same length and slides forward. A customer
  who stopped buying eventually leaves the window entirely. This measures
  stability of *recent* behaviour and is harsher.

They answer different questions and will give different stability numbers.
Report which one produced the figures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

WindowStyle = Literal["expanding", "rolling"]

# Fewer than two windows makes stability undefined; there is nothing to compare.
MIN_WINDOWS = 2

# A window shorter than this cannot produce a meaningful frequency count: most
# customers in a retail dataset buy a handful of times a year.
MIN_WINDOW_DAYS = 90


class WindowError(ValueError):
    """The requested windows do not fit the data. Raised, never silently adjusted."""


@dataclass(frozen=True)
class Window:
    """One as-of snapshot. `start` is None for an expanding window."""

    index: int
    start: pd.Timestamp | None
    end: pd.Timestamp
    style: WindowStyle

    @property
    def label(self) -> str:
        return str(self.end.date())

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "style": self.style,
            "start": None if self.start is None else str(self.start.date()),
            "end": str(self.end.date()),
            "days": None if self.start is None else int((self.end - self.start).days),
        }


def make_windows(
    date_min: pd.Timestamp | str,
    date_max: pd.Timestamp | str,
    *,
    count: int = 4,
    style: WindowStyle = "expanding",
    window_days: int | None = None,
    min_history_days: int = 365,
) -> list[Window]:
    """As-of dates spread evenly across the data, oldest first.

    `min_history_days` is the history the *first* window must have. With two
    years of data and the default, the first snapshot is taken a year in, so
    every window has at least one full annual cycle behind it - otherwise the
    earliest segmentation describes a different kind of business from the
    latest one and the stability number measures that rather than drift.
    """
    start = pd.Timestamp(date_min).normalize()
    finish = pd.Timestamp(date_max).normalize()

    if finish <= start:
        raise WindowError(f"date_max ({finish.date()}) must be after date_min ({start.date()}).")
    if count < MIN_WINDOWS:
        raise WindowError(
            f"Stability needs at least {MIN_WINDOWS} windows to compare; got {count}."
        )

    span_days = int((finish - start).days)
    first_end = start + pd.Timedelta(days=min_history_days)
    if first_end >= finish:
        raise WindowError(
            f"The data spans {span_days} days, which leaves no room for a first "
            f"window with {min_history_days} days of history followed by later "
            f"ones. Reduce min_history_days or widen the date range."
        )

    # Evenly spaced as-of dates from the first usable one to the end of the data.
    step = (finish - first_end) / (count - 1)
    ends = [first_end + step * position for position in range(count)]

    windows: list[Window] = []
    for position, end in enumerate(ends):
        end = pd.Timestamp(end).normalize()
        if style == "expanding":
            window_start = None
        else:
            length = window_days or min_history_days
            if length < MIN_WINDOW_DAYS:
                raise WindowError(
                    f"A rolling window of {length} days is too short to count "
                    f"purchase frequency meaningfully; {MIN_WINDOW_DAYS} is the floor."
                )
            window_start = end - pd.Timedelta(days=length)
            if window_start < start:
                raise WindowError(
                    f"A rolling window of {length} days ending {end.date()} starts "
                    f"before the data does ({start.date()}). Shorten the window, "
                    f"reduce the count, or use the expanding style."
                )
        windows.append(Window(index=position + 1, start=window_start, end=end, style=style))

    return windows


def describe_windows(windows: list[Window]) -> dict[str, object]:
    """The window set as a record for the run log."""
    if not windows:
        return {"available": False, "reason": "No windows."}

    style = windows[0].style
    return {
        "available": True,
        "count": len(windows),
        "style": style,
        "windows": [window.as_dict() for window in windows],
        "note": (
            "Expanding windows accumulate history, which is what a business "
            "actually sees on any given date. Rolling windows are the same "
            "length and slide forward, so a lapsed customer eventually leaves "
            "the window; that measures stability of recent behaviour and is a "
            "harsher test. They answer different questions."
            if style == "expanding" else
            "Rolling windows are a fixed length and slide forward, so a customer "
            "who stops buying eventually drops out entirely. This measures the "
            "stability of recent behaviour and is harsher than expanding windows."
        ),
    }


def common_customers(snapshots: dict[str, pd.DataFrame], key: str = "customer") -> list[str]:
    """Customers present in every snapshot.

    Stability can only be measured on customers that both partitions actually
    contain. A customer who appears late cannot have "moved" between the first
    two windows, and counting them as a change would make stability look worse
    the faster the business grows.
    """
    if not snapshots:
        return []
    sets = [set(frame[key].astype(str)) for frame in snapshots.values() if not frame.empty]
    if not sets:
        return []
    shared = set.intersection(*sets)
    return sorted(shared)
