"""Model 9: combining the members of the ladder.

This module is the most directly literature-driven part of Phase 5, so the
grounding is worth stating precisely.

Aras, Deveci Kocakoç & Polat (2017) forecast ten weekly product series for a
furniture retailer with five single models (ETS, ARIMA, ARFIMA, a neural
network and ANFIS) and six combination rules, and reported:

* **no single model beat the others across all the series** - "it is almost
  impossible to know in advance which forecasting model will perform best for
  a given data set";
* **most combinations produced statistically significant accuracy gains** over
  the individual models and over the company's existing forecasts;
* **the simple rules matched or beat the elaborate ones.** They compared three
  simple (mean, 20% trimmed mean, median) against three weighted (least-squares
  weights, MSE weights, MSE ranks). LS weights "had the worst overall
  performance among the combining methods examined, and even performed worse
  than the single methods", which they attribute to its needing many estimated
  parameters;
* **combining is less risky than selecting.** "making use of only a single
  model involves more risk of producing inaccurate forecasts than is associated
  with the use of combining methods".

So this module implements mean, trimmed mean and median, and deliberately does
**not** implement least-squares weights. That is not a shortcut: fitting
combination weights on this data would need its own inner validation split to
avoid leakage, would consume folds the ladder needs, and the one paper in the
supplied set that tested it found it worse than doing nothing. If a reviewer
asks why there are no optimal weights, that is the answer.

The default is the **median**, which Aras et al. describe as "less prone to be
affected by extreme values than the simple mean combination". With a ladder
that includes a model capable of producing an occasional wild forecast, that
property matters more than the small efficiency loss.
"""

from __future__ import annotations

from typing import Literal, Mapping

import numpy as np
import pandas as pd

Rule = Literal["median", "mean", "trimmed_mean"]

# Aras et al. cite the 20% trimmed mean as the one with extensive support.
DEFAULT_TRIM = 0.20

# Below three members a trimmed mean has nothing to trim and a median is just
# the middle of two numbers; the combination is reported but flagged.
MIN_MEMBERS_FOR_TRIM = 5


def combine(
    forecasts: Mapping[str, np.ndarray],
    rule: Rule = "median",
    *,
    trim: float = DEFAULT_TRIM,
) -> dict[str, object]:
    """Combine member forecasts point by point.

    `forecasts` maps model name to an array of the same length. Returns the
    combined forecast plus the spread between members, which is useful in its
    own right: wide disagreement at a given horizon step is a signal the point
    forecast should not be trusted far, and it feeds the method card.
    """
    if not forecasts:
        raise ValueError("Combination needs at least one member forecast.")

    names = sorted(forecasts)
    # Checked before stacking: numpy raises its own ragged-array error first
    # otherwise, and that message says nothing about horizons.
    lengths = {len(forecasts[name]) for name in names}
    if len(lengths) != 1:
        raise ValueError(
            f"Member forecasts have different lengths ({sorted(lengths)}). They must "
            f"all cover the same horizon, or the combination is averaging different "
            f"weeks against each other."
        )
    matrix = np.vstack([np.asarray(forecasts[name], dtype="float64") for name in names])

    usable = ~np.isnan(matrix)
    if not usable.any():
        raise ValueError("Every member forecast is missing.")

    notes: list[str] = []
    if rule == "median":
        combined = np.nanmedian(matrix, axis=0)
    elif rule == "mean":
        combined = np.nanmean(matrix, axis=0)
    elif rule == "trimmed_mean":
        if len(names) < MIN_MEMBERS_FOR_TRIM:
            notes.append(
                f"A {trim:.0%} trim on {len(names)} members removes nothing at most "
                f"horizon steps; the result is effectively the mean. Reported as "
                f"requested, but the median is the more useful robust rule here."
            )
        combined = _trimmed_mean(matrix, trim)
    else:
        raise ValueError(
            f"Unknown combination rule '{rule}'. Supported: median, mean, "
            f"trimmed_mean. Least-squares weights are deliberately not "
            f"implemented - see the module docstring."
        )

    spread = np.nanmax(matrix, axis=0) - np.nanmin(matrix, axis=0)
    missing = int((~usable).sum())
    if missing:
        notes.append(
            f"{missing} member values were missing and were skipped point by point; "
            f"the combination at those steps averages fewer members."
        )

    return {
        "rule": rule,
        "members": names,
        "point": combined,
        "member_spread": spread,
        "mean_disagreement": float(np.nanmean(spread)),
        "notes": notes,
        "grounding": (
            "Aras, Deveci Kocakoç & Polat (2017) found simple combination rules "
            "matched or beat weighted ones on ten weekly retail series, with "
            "least-squares weights worst of all."
        ),
    }


def _trimmed_mean(matrix: np.ndarray, trim: float) -> np.ndarray:
    """Mean after discarding the highest and lowest `trim` share at each step."""
    if not 0 <= trim < 0.5:
        raise ValueError(f"trim must be in [0, 0.5); got {trim}.")

    horizon = matrix.shape[1]
    result = np.full(horizon, np.nan, dtype="float64")
    for step in range(horizon):
        column = matrix[:, step]
        values = np.sort(column[~np.isnan(column)])
        if values.size == 0:
            continue
        cut = int(np.floor(values.size * trim))
        kept = values[cut: values.size - cut] if values.size - 2 * cut > 0 else values
        result[step] = float(np.mean(kept))
    return result


def combination_table(
    member_errors: pd.DataFrame, combined_errors: pd.Series
) -> pd.DataFrame:
    """Does the combination beat its own members, fold by fold?

    `member_errors` has one column per member and one row per fold; the series
    holds the combination's error on the same folds. The answer that matters
    for RQ1 is not "did the combination win on average" - that can happen while
    it loses on most folds - but on how many folds it beat each member, which
    is what the Friedman test in `significance.py` then formalises.
    """
    rows = []
    for member in member_errors.columns:
        difference = member_errors[member] - combined_errors
        rows.append({
            "member": member,
            "member_mean_error": float(member_errors[member].mean()),
            "combination_mean_error": float(combined_errors.mean()),
            "folds_combination_better": int((difference > 0).sum()),
            "folds": int(len(combined_errors)),
            "mean_improvement": float(difference.mean()),
        })
    return pd.DataFrame(rows).sort_values("mean_improvement", ascending=False)
