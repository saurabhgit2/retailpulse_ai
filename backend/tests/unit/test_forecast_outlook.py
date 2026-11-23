"""The business outlook core: closures, back-testing, selection and the forecast.

Each test fixes one behaviour that the old page got wrong or that a manager
would be misled by if it broke. The series are synthetic and built so the right
answer is known before the code runs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.forecasting import outlook as o

WEEKS = 106
START = "2009-11-30"


def _calendar(n: int = WEEKS) -> pd.DatetimeIndex:
    return pd.date_range(START, periods=n, freq="W-MON")


def _seasonal(n: int = WEEKS, *, noise: float = 0.0, growth: float = 0.0, seed: int = 0):
    """A retail-shaped year: a steady base and an autumn peak, optionally growing."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    base = 1000.0 * (1.0 + growth) ** (t / 52.0)
    peak = 600.0 * np.exp(-(((t % 52) - 46) / 4.0) ** 2)
    values = base + peak + rng.normal(0.0, noise, n)
    return pd.Series(values, index=_calendar(n))


# ---------------------------------------------------------------------------
# preparing the history
# ---------------------------------------------------------------------------

def test_closure_weeks_are_filled_from_their_neighbours_not_left_at_zero():
    values = np.array([100.0, 120.0, 0.0, 0.0, 180.0])
    closed = np.array([False, False, True, True, False])
    filled = o.fill_closures(values, closed)
    assert filled.tolist() == pytest.approx([100.0, 120.0, 140.0, 160.0, 180.0])


def test_open_weeks_are_never_changed_by_the_closure_fill():
    values = np.array([5.0, 0.0, 7.0])           # a real zero in an open week
    filled = o.fill_closures(values, np.zeros(3, dtype=bool))
    assert filled.tolist() == [5.0, 0.0, 7.0]


# ---------------------------------------------------------------------------
# the methods
# ---------------------------------------------------------------------------

def test_growth_ratio_compares_the_last_quarter_with_the_same_quarter_last_year():
    y = np.concatenate(
        [np.full(52, 100.0), np.full(13, 100.0), np.full(39, 100.0), np.full(13, 110.0)]
    )
    assert o.growth_ratio(y) == pytest.approx(1.10)


def test_growth_ratio_is_clipped_so_one_odd_quarter_cannot_double_a_year():
    y = np.concatenate([np.full(65, 10.0), np.full(39, 10.0), np.full(13, 1000.0)])
    assert o.growth_ratio(y) == o.GROWTH_CLIP[1]


# Ends in week 40 of the second year, so the next twelve weeks run through
# the autumn peak and a seasonal forecast has a shape to show.
INTO_PEAK = 92


def test_the_seasonal_methods_repeat_the_yearly_shape_rather_than_a_flat_line():
    y = _seasonal(INTO_PEAK).to_numpy()
    for name in ("seasonal_growth", "seasonal_naive", "trend_season", "seasonal_blend"):
        forecast = o.CANDIDATES[name].fn(y, 12)
        assert np.ptp(forecast) > 100, f"{name} came out flat"


def test_the_flat_methods_are_marked_as_flat():
    assert not o.CANDIDATES["recent_level"].seasonal
    assert not o.CANDIDATES["recent_average"].seasonal
    forecast = o.CANDIDATES["recent_level"].fn(_seasonal().to_numpy(), 6)
    assert np.ptp(forecast) == 0


# ---------------------------------------------------------------------------
# back-testing
# ---------------------------------------------------------------------------

def test_backtest_origins_are_recent_and_leave_a_full_horizon_after_each():
    origins = o.backtest_origins(106, 12, 65, count=8, step=4)
    assert origins[-1] == 94                          # 106 - 12: the newest
    assert origins == sorted(origins)
    assert all(t + 12 <= 106 and t >= 65 for t in origins)


def test_backtest_never_lets_a_method_see_the_weeks_it_is_scored_on():
    """Plant a spike in a scored window. A method that peeked would forecast it."""
    y = np.full(WEEKS, 100.0)
    y[96] = 10_000.0
    seen = []

    def spy(history, horizon):
        seen.append(len(history))
        return np.full(horizon, float(history.max()))

    probe = o.Candidate("spy", "spy", "", 8, False, spy)
    o.backtest(y, np.zeros(WEEKS, dtype=bool), probe, 12, count=8, step=4)
    for length in seen:
        assert length <= 96 or y[:length].max() == 10_000.0
    # The origin at 94 forecasts weeks 94-105 from weeks 0-93: no spike visible.
    assert 94 in seen


def test_closure_weeks_are_not_scored():
    y = _seasonal().to_numpy()
    closed = np.zeros(WEEKS, dtype=bool)
    closed[100] = True
    result = o.backtest(y, closed, o.CANDIDATES["seasonal_naive"], 12, count=1, step=4)
    assert all(step != 100 - 94 for step, _, _ in result.errors)


def test_wape_is_total_absolute_error_over_total_actual():
    assert o.wape(np.array([100.0, 100.0]), np.array([90.0, 120.0])) == pytest.approx(15.0)
    assert o.wape(np.zeros(3), np.ones(3)) is None


def test_the_interval_spans_the_middle_eighty_percent_of_past_errors():
    errors = [(0, a, 100.0) for a in range(50, 151)]          # ratios 0.5 .. 1.5
    low, high = o.interval_multipliers(errors)
    assert low == pytest.approx(0.6, abs=0.01) and high == pytest.approx(1.4, abs=0.01)


def test_too_few_errors_give_no_interval_rather_than_a_misleading_one():
    assert o.interval_multipliers([(0, 1.0, 1.0)] * 3) is None


# ---------------------------------------------------------------------------
# the whole outlook
# ---------------------------------------------------------------------------

def test_a_seasonal_series_gets_a_seasonal_model_and_a_forecast_that_is_not_flat():
    """The original complaint: the page drew a flat line on a seasonal business."""
    result = o.forecast_series(_seasonal(INTO_PEAK, noise=20.0, growth=0.1))
    assert result["available"]
    assert result["model"]["seasonal"]
    assert np.ptp(result["forecast"]["point"]) > 100


def test_the_chosen_model_has_the_lowest_backtest_error():
    result = o.forecast_series(_seasonal(noise=40.0, seed=3))
    scored = [c for c in result["candidates"] if c["wape"] is not None]
    chosen = next(c for c in scored if c["chosen"])
    assert chosen["wape"] == min(c["wape"] for c in scored)
    assert result["model"]["name"] == chosen["name"]


def test_a_closure_at_the_end_of_history_does_not_drag_the_forecast_to_zero():
    """Exactly what happened before: a zero-filled Christmas week ended a
    training window and every last-value model forecast zero."""
    series = _seasonal(noise=10.0)
    last = series.index[-1]
    series[last] = 0.0
    result = o.forecast_series(series, closed_periods={last})
    assert min(result["forecast"]["point"]) > 500
    assert result["closures_filled"] == 1


def test_a_week_closed_last_year_is_forecast_as_closed_and_flagged():
    series = _seasonal(noise=10.0)
    closed_week = series.index[-52 + 2]          # one year before forecast week 3
    series[closed_week] = 0.0
    result = o.forecast_series(series, closed_periods={closed_week})
    assert result["forecast"]["likely_closed"][2] is True
    assert result["forecast"]["point"][2] == 0.0
    assert sum(result["forecast"]["likely_closed"]) == 1


def test_the_forecast_starts_the_week_after_the_last_complete_week():
    series = _seasonal()
    result = o.forecast_series(series, horizon=8)
    first = pd.Timestamp(result["forecast"]["periods"][0])
    assert first == series.index[-1] + pd.Timedelta(weeks=1)
    assert len(result["forecast"]["point"]) == 8


def test_the_band_contains_the_forecast_and_forecasts_are_never_negative():
    result = o.forecast_series(_seasonal(noise=150.0, seed=7))
    f = result["forecast"]
    assert all(lo <= p <= hi for lo, p, hi in zip(f["lower"], f["point"], f["upper"], strict=False))
    assert min(f["point"]) >= 0


def test_the_recent_check_compares_the_newest_backtest_with_what_happened():
    series = _seasonal(noise=20.0)
    result = o.forecast_series(series)
    check = result["recent_check"]
    assert check["periods"][-1] == str(series.index[-1].date())
    assert check["actual"] == pytest.approx(series.to_numpy()[-12:].round(2).tolist())


def test_a_short_history_is_refused_with_a_reason_not_a_crash():
    result = o.forecast_series(_seasonal(15))
    assert result["available"] is False
    assert "weeks of history" in result["reason"]


def test_without_a_full_year_only_the_flat_methods_compete():
    result = o.forecast_series(_seasonal(40))
    assert result["available"]
    assert all(c["flat"] for c in result["candidates"])


def test_products_come_back_in_revenue_order_with_their_descriptions():
    calendar = _calendar()
    frames = []
    for code, scale in (("B", 50.0), ("A", 10.0)):
        values = _seasonal(seed=1).to_numpy() / 1000.0 * scale
        frames.append(pd.DataFrame({"series_id": code, "period": calendar, "value": values}))
    panel = pd.concat(frames, ignore_index=True)
    rows, skipped = o.product_outlook(panel, calendar, labels={"A": "Alpha", "B": "Bravo"})
    assert skipped == []
    assert [r["product_code"] for r in rows] == ["B", "A"]
    assert rows[0]["description"] == "Bravo"
    assert rows[0]["next_horizon_units"] > rows[1]["next_horizon_units"]
    assert rows[0]["model"]["name"] in o.PRODUCT_CANDIDATES


def test_a_product_missing_weeks_is_treated_as_selling_nothing_in_them():
    calendar = _calendar()
    sold = calendar[::2]                       # sells every other week only
    panel = pd.DataFrame({"series_id": "X", "period": sold, "value": 10.0})
    rows, _ = o.product_outlook(panel, calendar)
    assert rows[0]["last_horizon_units"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# what the real Online Retail II products exposed
# ---------------------------------------------------------------------------

def test_weeks_before_a_product_launched_are_dropped():
    series = pd.Series([0.0, 0.0, 5.0, 0.0, 7.0], index=_calendar(5))
    trimmed = o.trim_before_launch(series)
    assert trimmed.tolist() == [5.0, 0.0, 7.0]
    assert o.trim_before_launch(pd.Series([0.0, 0.0], index=_calendar(2))).empty


def test_a_product_launched_this_year_is_not_forecast_from_last_years_zeros():
    """Rabbit Night Light: a year of nothing, then thousands a week. Copying
    'the same week last year' forecast zero for the next twelve weeks."""
    calendar = _calendar()
    values = np.zeros(WEEKS)
    values[60:] = 1000.0 + 50.0 * np.arange(WEEKS - 60)
    panel = pd.DataFrame({"series_id": "NEW", "period": calendar, "value": values})
    rows, _ = o.product_outlook(panel, calendar)
    row = rows[0]
    assert row["weeks_of_history"] == WEEKS - 60
    assert not row["model"]["seasonal"]
    assert row["next_horizon_units"] > 10_000


def test_a_one_off_bulk_week_is_capped_but_a_busy_season_is_not():
    steady = np.full(30, 100.0)
    steady[15] = 74_215.0                                   # the bulk order
    capped, changed = o.cap_spikes(steady)
    assert changed == 1 and capped[15] == pytest.approx(100.0)

    season = np.full(30, 100.0)
    season[12:18] = [400.0, 900.0, 1500.0, 1400.0, 800.0, 300.0]   # a real peak
    capped, changed = o.cap_spikes(season)
    assert changed == 0 and capped.tolist() == season.tolist()


def test_a_bulk_week_last_year_does_not_inflate_this_years_forecast():
    """Medium Ceramic Top Storage Jar: one January week of 74,215 units."""
    calendar = _calendar()
    values = _seasonal(seed=2).to_numpy() / 10.0
    values[60] = 74_215.0
    panel = pd.DataFrame({"series_id": "JAR", "period": calendar, "value": values})
    rows, _ = o.product_outlook(panel, calendar)
    row = rows[0]
    assert row["spikes_capped"] == 1
    assert max(row["forecast"]["point"]) < 1_000


def test_the_product_chart_shows_what_really_sold_including_a_spike():
    calendar = _calendar()
    values = np.full(WEEKS, 100.0)
    values[-5] = 9_000.0
    panel = pd.DataFrame({"series_id": "S", "period": calendar, "value": values})
    rows, _ = o.product_outlook(panel, calendar)
    assert 9_000.0 in rows[0]["history"]["values"]
    assert rows[0]["last_horizon_units"] == pytest.approx(100.0 * 11 + 9_000.0)


def test_a_forecast_of_nothing_is_passed_over_when_the_series_is_still_selling():
    zero = o.Candidate("zero", "zero", "", 8, False, lambda y, h: np.zeros(h))
    o.CANDIDATES["zero"] = zero
    try:
        series = pd.Series(np.full(60, 50.0), index=_calendar(60))
        series.iloc[-20:] = 0.0
        series.iloc[-2:] = 500.0                  # selling again at the end
        result = o.forecast_series(series, candidates=("zero", "recent_average"))
        assert result["model"]["name"] == "recent_average"
        assert sum(result["forecast"]["point"]) > 0
    finally:
        del o.CANDIDATES["zero"]


def test_more_returned_than_sold_in_a_week_counts_as_no_sales_not_negative():
    calendar = _calendar()
    values = np.full(WEEKS, 20.0)
    values[-3] = -40.0
    panel = pd.DataFrame({"series_id": "R", "period": calendar, "value": values})
    rows, _ = o.product_outlook(panel, calendar)
    assert rows[0]["last_horizon_units"] == pytest.approx(20.0 * 11)


def test_the_outlook_module_stays_pure():
    banned = ("fastapi", "sqlalchemy", "pydantic", "starlette", "psycopg",
              "alembic", "app.db", "app.api", "app.services")
    source = Path(o.__file__).read_text(encoding="utf-8")
    offences = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        else:
            continue
        offences += [m for m in modules if any(m == b or m.startswith(b + ".") for b in banned)]
    assert not offences
