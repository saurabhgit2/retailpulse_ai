"""Prediction intervals from observed errors, and whether they hold up.

A point forecast with no interval invites a manager to treat it as a fact. The
honest version says how wrong it has usually been.

**Empirical, not parametric.** The obvious approach is a normal interval,
point +/- 1.96 * sigma. It is wrong here in two ways: retail forecast errors
are skewed (you can sell unexpectedly many, you cannot sell fewer than none),
and the width must grow with the horizon, because a forecast twelve weeks out
is not as reliable as one week out. So the intervals are quantiles of the
errors the model actually made **at each horizon step** during
cross-validation. Step 1's interval comes from step-1 errors, step 12's from
step-12 errors.

That requires the CV folds to have been run first, which is why
`from_backtest` takes the fold results rather than the fitted model.

**Coverage is reported, not assumed.** A nominal 80% interval that contains
the actual 55% of the time is worse than no interval, because it looks like
information. `coverage` measures what fraction of hold-out actuals fell inside,
and the method card prints nominal and observed side by side. With the number
of folds available here, observed coverage is itself a noisy estimate - that
caveat travels with the number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_LEVEL = 0.80

# Below this many errors per horizon step, a quantile is being read off a
# handful of points and the interval is theatre.
MIN_ERRORS_PER_STEP = 5


def from_backtest(
    errors_by_step: dict[int, list[float]],
    point: np.ndarray,
    level: float = DEFAULT_LEVEL,
    *,
    non_negative: bool = True,
) -> dict[str, object]:
    """Interval around `point` from the model's own backtest errors.

    `errors_by_step` maps horizon step (1-based) to the actual-minus-forecast
    errors observed at that step across CV folds. Signed, deliberately: a model
    that is usually low should get an interval shifted upwards rather than a
    symmetric one centred on a biased point.
    """
    if not 0 < level < 1:
        raise ValueError(f"level must be between 0 and 1; got {level}.")

    horizon = len(point)
    lower_q, upper_q = (1 - level) / 2, 1 - (1 - level) / 2
    lower = np.full(horizon, np.nan)
    upper = np.full(horizon, np.nan)
    thin_steps: list[int] = []

    # Pooling fallback: if a step has too few errors of its own, borrow the
    # whole distribution. Wider than it should be at short horizons, which is
    # the right direction to be wrong in.
    pooled = np.array([e for values in errors_by_step.values() for e in values], dtype="float64")
    pooled = pooled[~np.isnan(pooled)]

    for step in range(1, horizon + 1):
        values = np.asarray(errors_by_step.get(step, []), dtype="float64")
        values = values[~np.isnan(values)]
        if values.size < MIN_ERRORS_PER_STEP:
            thin_steps.append(step)
            values = pooled
        if values.size == 0:
            continue
        lower[step - 1] = point[step - 1] + float(np.quantile(values, lower_q))
        upper[step - 1] = point[step - 1] + float(np.quantile(values, upper_q))

    if non_negative:
        # Sales cannot be negative. Clipping the lower bound is a statement
        # about the domain, not about the model, and it is recorded as one.
        lower = np.maximum(lower, 0.0)

    notes: list[str] = []
    if thin_steps:
        notes.append(
            f"Horizon steps {thin_steps} had fewer than {MIN_ERRORS_PER_STEP} "
            f"backtest errors of their own, so their intervals use the pooled "
            f"error distribution across all steps. They are wider at short "
            f"horizons than the data strictly implies."
        )
    if pooled.size == 0:
        notes.append("No backtest errors were supplied, so no interval could be formed.")

    return {
        "level": level,
        "lower": lower,
        "upper": upper,
        "method": "empirical quantiles of backtest errors, by horizon step",
        "errors_used": int(pooled.size),
        "notes": notes,
    }


def coverage(actual, lower, upper, level: float = DEFAULT_LEVEL) -> dict[str, object]:
    """What share of actuals fell inside the interval, against what was promised."""
    y = np.asarray(pd.Series(actual).to_numpy(), dtype="float64")
    low = np.asarray(pd.Series(lower).to_numpy(), dtype="float64")
    high = np.asarray(pd.Series(upper).to_numpy(), dtype="float64")

    usable = ~(np.isnan(y) | np.isnan(low) | np.isnan(high))
    if not usable.any():
        return {"available": False, "reason": "No comparable points."}

    inside = (y[usable] >= low[usable]) & (y[usable] <= high[usable])
    observed = float(inside.mean())
    width = float(np.mean(high[usable] - low[usable]))

    verdict = (
        "about right" if abs(observed - level) <= 0.10
        else "too narrow - the interval understates the uncertainty"
        if observed < level else
        "too wide - the interval is conservative"
    )

    return {
        "available": True,
        "nominal": level,
        "observed": observed,
        "points": int(usable.sum()),
        "mean_width": width,
        "verdict": verdict,
        "caveat": (
            f"Observed coverage is itself estimated from {int(usable.sum())} points, "
            f"so it carries its own uncertainty; do not read a gap of a few "
            f"percentage points as a finding."
        ),
    }
