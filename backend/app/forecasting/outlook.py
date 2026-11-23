"""The business outlook: what the next few weeks are likely to look like.

This module answers a manager's question, not a research question: "how much
will we sell over the next twelve weeks, and how far can I trust that number?"
The RQ1 experiment in `evaluate.py` is left exactly as it was; this sits beside
it and reuses nothing that would change its results.

Three things differ from the experiment, and each one is the reason the old
Forecasting page drew a flat line.

1. **Closure weeks are treated as missing, not as zero sales.** The shop does
   not trade over Christmas. The trend query fills those weeks with zero so the
   calendar is even, and a model whose training window ends on a zero then
   forecasts zero, or a flat low level, for the whole horizon. Here those weeks
   are filled from their neighbours before any model sees them, and they are
   left out of every error calculation.
2. **The model is chosen on the most recent periods.** Each candidate is
   back-tested from several recent starting points ("if we had forecast from
   here, how wrong would we have been?"), and the one with the lowest typical
   error wins. A model that was good two years ago but is poor now loses.
3. **It forecasts the future.** The experiment only replays a hold-out window
   that has already happened. The outlook projects past the last complete week.

Everything here is plain NumPy and pandas, like the rest of `app/forecasting`.
No web framework and no ORM, so it is testable in milliseconds and the service
layer only has to fetch the series.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.forecasting.fourier import FourierRegression

# Bumped whenever a change here would change a stored result. It is part of the
# cache key, so an old outlook is never served after the method changes.
OUTLOOK_VERSION = "outlook-2"

SEASON = 52                 # weeks in a year
GROWTH_WINDOW = 13          # one quarter: the window used to measure growth
GROWTH_CLIP = (0.5, 2.0)    # a quarter can halve or double sales, not more
INTERVAL_LEVEL = 0.80       # the band covers 80% of past back-test errors
SPIKE_WINDOW = 4            # weeks either side a spike is judged against
SPIKE_FACTOR = 5.0          # a week this many times its neighbours is a one-off


# ---------------------------------------------------------------------------
# The candidates. Each takes a gap-free history and returns `horizon` values.
# ---------------------------------------------------------------------------


def _seasonal_naive(y: np.ndarray, horizon: int) -> np.ndarray:
    """Each future week equals the same week one year earlier."""
    steps = np.arange(horizon)
    return y[len(y) - SEASON + (steps % SEASON)].astype("float64")


def growth_ratio(y: np.ndarray, window: int = GROWTH_WINDOW) -> float:
    """Recent weeks against the same weeks a year earlier, clipped.

    1.10 means the last quarter sold 10% more than the same quarter last year.
    Clipped because a single extreme quarter (a bulk order, a stock-out) should
    not double or halve a whole year's forecast.
    """
    if len(y) < SEASON + window:
        return 1.0
    recent = float(np.sum(y[-window:]))
    year_ago = float(np.sum(y[-SEASON - window:-SEASON]))
    if year_ago <= 0 or recent <= 0:
        return 1.0
    return float(np.clip(recent / year_ago, *GROWTH_CLIP))


def _seasonal_growth(y: np.ndarray, horizon: int) -> np.ndarray:
    """Same week last year, scaled by how much the last quarter grew."""
    return _seasonal_naive(y, horizon) * growth_ratio(y)


def _trend_and_season(y: np.ndarray, horizon: int) -> np.ndarray:
    """A straight-line trend plus a smooth yearly curve (three harmonics)."""
    model = FourierRegression(season_length=SEASON, harmonics=3)
    model.fit(pd.Series(y))
    return model.predict(horizon).point


def _blend(y: np.ndarray, horizon: int) -> np.ndarray:
    """The average of the two seasonal methods. Their errors partly cancel."""
    return 0.5 * (_seasonal_growth(y, horizon) + _trend_and_season(y, horizon))


def smoothing_level(y: np.ndarray) -> float:
    """Simple exponential smoothing: the level after the last week.

    The smoothing weight is chosen by one-step-ahead squared error over a small
    grid. A grid rather than an optimiser: nine evaluations of a loop over at
    most a hundred values is instant and always gives the same answer.
    """
    best_level, best_error = float(y[-1]), np.inf
    for alpha in (0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 0.9):
        level, error = float(y[0]), 0.0
        for value in y[1:]:
            error += (value - level) ** 2
            level = alpha * value + (1 - alpha) * level
        if error < best_error:
            best_error, best_level = error, level
    return best_level


def _recent_level(y: np.ndarray, horizon: int) -> np.ndarray:
    return np.full(horizon, smoothing_level(y), dtype="float64")


def _recent_average(y: np.ndarray, horizon: int) -> np.ndarray:
    return np.full(horizon, float(np.mean(y[-12:])), dtype="float64")


def _level_and_season(y: np.ndarray, horizon: int) -> np.ndarray:
    """The recent level, shaped by last year's pattern.

    Last year's weeks are divided by last year's average to give a seasonal
    index (1.3 = a week 30% busier than usual), then multiplied by the current
    smoothed level. For a product whose sales move around a lot this is steadier
    than copying last year's weeks outright, and unlike a flat level it still
    rises into the busy season.
    """
    last_year = y[-SEASON:]
    mean = float(np.mean(last_year))
    if mean <= 0:
        return _recent_level(y, horizon)
    index = _seasonal_naive(y, horizon) / mean
    # Shrink the index halfway towards 1: one year of one product is a noisy
    # estimate of its seasonal shape, and a full-strength copy overreacts.
    index = 1.0 + 0.5 * (index - 1.0)
    deseasonalised = y[-GROWTH_WINDOW:] / np.maximum(
        1.0 + 0.5 * (y[-SEASON - GROWTH_WINDOW:-SEASON] / mean - 1.0), 0.1
    )
    level = float(np.mean(deseasonalised))
    return np.maximum(index * level, 0.0)


@dataclass(frozen=True)
class Candidate:
    name: str
    label: str
    explanation: str
    min_history: int
    seasonal: bool
    fn: Callable[[np.ndarray, int], np.ndarray]


CANDIDATES: dict[str, Candidate] = {
    c.name: c
    for c in (
        Candidate(
            "seasonal_growth", "Last year, adjusted for growth",
            "Takes each week's figure from the same week last year and scales it by "
            "how much the most recent quarter grew compared with the same quarter "
            "a year earlier.",
            SEASON + GROWTH_WINDOW, True, _seasonal_growth,
        ),
        Candidate(
            "seasonal_naive", "Same week last year",
            "Repeats the figure from the same week one year earlier, unchanged.",
            SEASON, True, _seasonal_naive,
        ),
        Candidate(
            "trend_season", "Trend and yearly pattern",
            "Fits a smooth yearly shape and a straight-line trend through all of "
            "the history, then extends both forward.",
            SEASON + 8, True, _trend_and_season,
        ),
        Candidate(
            "seasonal_blend", "Blend of the two seasonal methods",
            "The average of 'last year, adjusted for growth' and 'trend and yearly "
            "pattern'. When one runs high and the other low, the average is "
            "closer than either.",
            SEASON + GROWTH_WINDOW, True, _blend,
        ),
        Candidate(
            "level_season", "Recent level with a softened yearly pattern",
            "Measures the current level of sales and applies a softened version "
            "of last year's busy and quiet weeks to it.",
            SEASON + GROWTH_WINDOW, True, _level_and_season,
        ),
        Candidate(
            "recent_level", "Recent level (exponential smoothing)",
            "Weights recent weeks most heavily and carries that level forward. It "
            "has no seasonal pattern, so its forecast is a flat line.",
            8, False, _recent_level,
        ),
        Candidate(
            "recent_average", "Average of the last 12 weeks",
            "Carries the average of the last twelve weeks forward as a flat line.",
            12, False, _recent_average,
        ),
    )
}

# Whole-business series have a strong yearly shape; the flat methods are kept
# in the comparison so the page can show how much worse they do.
TOTAL_CANDIDATES = (
    "seasonal_growth", "seasonal_naive", "trend_season", "seasonal_blend",
    "level_season", "recent_level", "recent_average",
)
# Single products are noisier. The pure copy-last-year and the trend fit
# overreact to one product's history, so the set leans on steadier methods.
PRODUCT_CANDIDATES = ("seasonal_growth", "level_season", "recent_level", "recent_average")


# ---------------------------------------------------------------------------
# Preparing the history
# ---------------------------------------------------------------------------


def fill_closures(values: np.ndarray, closed: np.ndarray) -> np.ndarray:
    """Replace closure weeks with a straight line between their neighbours.

    A closure is not a week of zero demand: the shop was shut. Leaving the zero
    in teaches every model a collapse that did not happen.
    """
    filled = values.astype("float64").copy()
    if not closed.any():
        return filled
    open_positions = np.flatnonzero(~closed)
    if open_positions.size == 0:
        return filled
    filled[closed] = np.interp(
        np.flatnonzero(closed), open_positions, filled[open_positions]
    )
    return filled


def trim_before_launch(series: pd.Series) -> pd.Series:
    """Drop the weeks before a product's first sale.

    A product launched in 2011 has a year of zeros before it. Left in, "the same
    week last year" is zero and a seasonal method forecasts nothing for a
    product that is selling thousands a week. Trimmed, the history is shorter
    than a year and only the methods that need no year-ago data compete.
    """
    selling = np.flatnonzero(series.to_numpy(dtype="float64") > 0)
    if selling.size == 0:
        return series.iloc[0:0]
    return series.iloc[int(selling[0]):]


def cap_spikes(
    values: np.ndarray, *, window: int = SPIKE_WINDOW, factor: float = SPIKE_FACTOR
) -> tuple[np.ndarray, int]:
    """Cap isolated one-off weeks, such as a single bulk order.

    A week is capped when it is more than `factor` times both every week within
    `window` weeks of it and the product's typical selling week. A busy season
    is never capped, because its neighbouring weeks are busy too. The capped
    week is set to the larger of those two references, so it still counts as
    a good week rather than vanishing. Returns the capped values and how many
    weeks were changed.
    """
    capped = values.astype("float64").copy()
    positive = values[values > 0]
    if positive.size == 0:
        return capped, 0
    typical = float(np.median(positive))
    changed = 0
    for t in range(len(values)):
        lo, hi = max(0, t - window), min(len(values), t + window + 1)
        neighbours = np.concatenate([values[lo:t], values[t + 1:hi]])
        reference = max(float(neighbours.max()) if neighbours.size else 0.0, typical)
        if values[t] > factor * reference:
            capped[t] = reference
            changed += 1
    return capped, changed


# ---------------------------------------------------------------------------
# Back-testing
# ---------------------------------------------------------------------------


def backtest_origins(
    length: int, horizon: int, min_history: int, *, count: int, step: int
) -> list[int]:
    """Recent starting points, newest last, each with a full horizon after it.

    An origin `t` means "train on weeks 0..t-1, forecast weeks t..t+horizon-1".
    """
    last = length - horizon
    origins = [last - i * step for i in range(count)]
    return sorted(t for t in origins if t >= min_history)


def wape(actual: np.ndarray, forecast: np.ndarray) -> float | None:
    """Total absolute error as a share of total actual sales, in percent."""
    denominator = float(np.sum(np.abs(actual)))
    if denominator <= 0:
        return None
    return 100.0 * float(np.sum(np.abs(actual - forecast))) / denominator


@dataclass
class Backtest:
    name: str
    wape: float | None
    origins: int
    # (step, actual, forecast) for every scored week, for the interval.
    errors: list[tuple[int, float, float]]
    latest: tuple[int, np.ndarray, np.ndarray] | None   # origin, actual, forecast


def backtest(
    filled: np.ndarray,
    closed: np.ndarray,
    candidate: Candidate,
    horizon: int,
    *,
    count: int,
    step: int,
) -> Backtest:
    origins = backtest_origins(
        len(filled), horizon, candidate.min_history, count=count, step=step
    )
    actual_all, forecast_all, errors = [], [], []
    latest = None
    for origin in origins:
        forecast = np.maximum(candidate.fn(filled[:origin], horizon), 0.0)
        actual = filled[origin:origin + horizon]
        scored = ~closed[origin:origin + horizon]     # closures are not scored
        actual_all.append(actual[scored])
        forecast_all.append(forecast[scored])
        errors.extend(
            (int(k), float(a), float(f))
            for k, a, f, s in zip(range(horizon), actual, forecast, scored, strict=False) if s
        )
        latest = (origin, actual, forecast)
    if not origins:
        return Backtest(candidate.name, None, 0, [], None)
    score = wape(np.concatenate(actual_all), np.concatenate(forecast_all))
    return Backtest(candidate.name, score, len(origins), errors, latest)


def interval_multipliers(
    errors: list[tuple[int, float, float]], level: float = INTERVAL_LEVEL
) -> tuple[float, float] | None:
    """How far off the chosen model was, as multipliers of its forecast.

    The ratio actual / forecast is collected over every back-tested week. The
    10th and 90th percentiles give a band that past errors fell inside 80% of
    the time. It is empirical, so it is as wide as the model's real mistakes
    rather than as narrow as a textbook assumption would make it.
    """
    ratios = np.array([a / f for _, a, f in errors if f > 0], dtype="float64")
    if ratios.size < 8:
        return None
    tail = (1.0 - level) / 2.0
    low, high = np.quantile(ratios, [tail, 1.0 - tail])
    return float(min(low, 1.0)), float(max(high, 1.0))


def confidence(score: float | None) -> str:
    """A plain-English grade for the typical back-test error."""
    if score is None:
        return "unknown"
    if score <= 15:
        return "high"
    if score <= 30:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# The outlook for one series
# ---------------------------------------------------------------------------


def forecast_series(
    series: pd.Series,
    *,
    closed_periods: set[pd.Timestamp] | None = None,
    horizon: int = 12,
    candidates: tuple[str, ...] = TOTAL_CANDIDATES,
    backtest_count: int = 8,
    backtest_step: int = 4,
    history_weeks: int = 52,
) -> dict:
    """Choose a model on recent back-tests, then forecast past the last week.

    `series` is weekly, evenly spaced and indexed by week start. `closed_periods`
    are the weeks the business did not trade at all.
    """
    closed_periods = closed_periods or set()
    index = pd.DatetimeIndex(series.index)
    values = series.to_numpy(dtype="float64")
    closed = np.array([p in closed_periods for p in index], dtype=bool)
    filled = fill_closures(values, closed)

    pool = [CANDIDATES[name] for name in candidates]
    usable = [c for c in pool if len(filled) >= c.min_history + horizon]
    if not usable:
        return {
            "available": False,
            "reason": (
                f"There are {len(filled)} weeks of history. Even the simplest method "
                f"needs {min(c.min_history for c in pool) + horizon} to be checked "
                f"against what actually happened."
            ),
        }

    results = [
        backtest(filled, closed, c, horizon, count=backtest_count, step=backtest_step)
        for c in usable
    ]
    scored = [r for r in results if r.wape is not None]
    if not scored:
        return {"available": False, "reason": "No method could be back-tested."}

    # Lowest error first. A method that forecasts nothing at all for a series
    # that sold in its most recent weeks is passed over: a back-test can make a
    # zero look accurate when every other method overshot one freak week, but
    # nobody would plan stock against a forecast of nothing.
    sold_recently = float(np.sum(filled[-horizon:])) > 0
    best = point = None
    for result in sorted(scored, key=lambda r: r.wape):
        attempt = np.maximum(CANDIDATES[result.name].fn(filled, horizon), 0.0)
        if attempt.sum() > 0 or not sold_recently:
            best, point = result, attempt
            break
    if best is None:
        best = min(scored, key=lambda r: r.wape)
        point = np.maximum(CANDIDATES[best.name].fn(filled, horizon), 0.0)
    chosen = CANDIDATES[best.name]
    future = pd.date_range(index[-1] + pd.Timedelta(weeks=1), periods=horizon, freq="W-MON")

    # A week the business did not trade a year ago is very likely another
    # closure. It is forecast as zero and flagged, rather than given a number a
    # manager would plan staff and stock against.
    year_ago = [p - pd.Timedelta(weeks=SEASON) for p in future]
    likely_closed = [p in closed_periods for p in year_ago]
    point = np.where(likely_closed, 0.0, point)

    multipliers = interval_multipliers(best.errors)
    if multipliers:
        lower, upper = point * multipliers[0], point * multipliers[1]
    else:
        lower, upper = point.copy(), point.copy()

    history_start = max(0, len(values) - history_weeks)
    recent = None
    if best.latest is not None:
        origin, actual, fcast = best.latest
        recent = {
            "periods": _dates(index[origin:origin + horizon]),
            "actual": _floats(np.where(closed[origin:origin + horizon], np.nan, actual)),
            "forecast": _floats(fcast),
            "wape": wape(
                actual[~closed[origin:origin + horizon]],
                fcast[~closed[origin:origin + horizon]],
            ),
        }

    last_year_same = _same_weeks_last_year(values, closed, horizon)
    next_total = float(np.sum(point))

    return {
        "available": True,
        "model": {
            "name": chosen.name,
            "label": chosen.label,
            "explanation": chosen.explanation,
            "seasonal": chosen.seasonal,
        },
        "accuracy": {
            "wape": best.wape,
            "confidence": confidence(best.wape),
            "backtests": best.origins,
            "horizon": horizon,
            "step": backtest_step,
        },
        "history": {
            "periods": _dates(index[history_start:]),
            "values": _floats(np.where(closed, np.nan, values)[history_start:]),
        },
        "forecast": {
            "periods": _dates(future),
            "point": _floats(point),
            "lower": _floats(lower),
            "upper": _floats(upper),
            "likely_closed": likely_closed,
            "level": INTERVAL_LEVEL if multipliers else None,
        },
        "recent_check": recent,
        "totals": {
            "next_4": float(np.sum(point[:4])),
            "next_horizon": next_total,
            "same_weeks_last_year": last_year_same,
            "change_vs_last_year": (
                None if not last_year_same else 100.0 * (next_total / last_year_same - 1.0)
            ),
            "last_horizon": float(np.sum(values[-horizon:][~closed[-horizon:]])),
        },
        "candidates": sorted(
            (
                {
                    "name": r.name,
                    "label": CANDIDATES[r.name].label,
                    "wape": r.wape,
                    "backtests": r.origins,
                    "chosen": r.name == best.name,
                    "flat": not CANDIDATES[r.name].seasonal,
                }
                for r in results
            ),
            key=lambda row: (row["wape"] is None, row["wape"] or 0.0),
        ),
        "closures_filled": int(closed.sum()),
    }


def _same_weeks_last_year(values: np.ndarray, closed: np.ndarray, horizon: int) -> float | None:
    """The actual total for the weeks one year before the forecast weeks."""
    start = len(values) - SEASON
    if start < 0:
        return None
    window = slice(start, min(start + horizon, len(values)))
    if window.stop - window.start < horizon:
        return None
    return float(np.sum(values[window]))


def _dates(index) -> list[str]:
    return [str(pd.Timestamp(p).date()) for p in index]


def _floats(array) -> list[float | None]:
    return [None if not np.isfinite(v) else round(float(v), 2) for v in array]


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def product_outlook(
    panel: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    closed_periods: set[pd.Timestamp] | None = None,
    horizon: int = 12,
    labels: dict[str, str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Forecast weekly units for each product in a long panel.

    `panel` has columns `series_id`, `period` and `value`. Each product is put
    on the shared `calendar` (a week with no row really did sell nothing),
    trimmed to start at its first sale, and has isolated one-off weeks capped.
    It then gets its own back-test from fewer, closer starting points and
    keeps the method that suited it best.

    Returns the rows, in the panel's order of revenue, and the codes of
    products that had too little history to forecast.
    """
    labels = labels or {}
    rows, skipped = [], []
    for code, group in panel.groupby("series_id", sort=False):
        raw = (
            group.set_index("period")["value"].reindex(calendar).fillna(0.0)
            # More returned than sold in a week is a refund, not negative demand.
            .clip(lower=0.0)
        )
        raw = trim_before_launch(raw)
        capped, spikes = cap_spikes(raw.to_numpy(dtype="float64"))
        outcome = forecast_series(
            pd.Series(capped, index=raw.index),
            closed_periods=closed_periods,
            horizon=horizon,
            candidates=PRODUCT_CANDIDATES,
            backtest_count=6,
            backtest_step=3,
            history_weeks=26,
        )
        if not outcome["available"]:
            skipped.append(str(code))
            continue
        # The chart and "last 12 weeks" show what really sold, spikes included;
        # only the fitting used the capped series.
        shown = raw.iloc[-26:]
        outcome["history"]["values"] = _floats(
            np.where([p in (closed_periods or set()) for p in shown.index], np.nan, shown)
        )
        totals = outcome["totals"]
        last = float(raw.iloc[-horizon:].sum())
        rows.append({
            "product_code": str(code),
            "description": labels.get(str(code)),
            "model": outcome["model"],
            "accuracy": outcome["accuracy"],
            "weeks_of_history": int(len(raw)),
            "spikes_capped": spikes,
            "last_horizon_units": last,
            "next_4_units": totals["next_4"],
            "next_horizon_units": totals["next_horizon"],
            "same_weeks_last_year": totals["same_weeks_last_year"],
            "change_vs_last_year": totals["change_vs_last_year"],
            "change_vs_recent": (
                None if not last else 100.0 * (totals["next_horizon"] / last - 1.0)
            ),
            "history": outcome["history"],
            "forecast": outcome["forecast"],
        })
    return rows, skipped
