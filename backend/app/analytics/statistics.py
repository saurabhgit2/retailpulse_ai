"""Descriptive statistics and group comparisons (architecture §12.6).

Two principles the report should state:

* **Non-parametric by default.** Retail distributions are nowhere near normal,
  so Mann-Whitney U (two groups) and Kruskal-Wallis (more than two) are used
  instead of t-tests and ANOVA. They assume no particular distribution.
* **Effect size beside every p-value.** At a million rows, a trivial difference
  is "significant". The p-value says the difference is unlikely to be chance;
  the effect size says whether it is big enough to care about. Reporting one
  without the other is how large datasets produce confident nonsense.

Every result carries a `method` block naming the test, its assumptions and what
it actually tests, so a chart can show its own method card (§12.9).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

MIN_GROUP_SIZE = 5
ALPHA = 0.05


def describe(values: pd.Series) -> dict[str, object]:
    """Mean *and* median, robust and classical spread, shape."""
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    numeric = numeric[np.isfinite(numeric)]
    if numeric.empty:
        return {"n": 0}

    array = numeric.to_numpy(dtype=float)
    mean = float(array.mean())
    sd = float(array.std(ddof=1)) if array.size > 1 else 0.0
    quartile_1, median, quartile_3 = (float(x) for x in np.percentile(array, [25, 50, 75]))

    return {
        "n": int(array.size),
        "mean": mean,
        "median": median,
        "std_dev": sd,
        "coefficient_of_variation": float(sd / mean) if abs(mean) > 1e-9 else None,
        "min": float(array.min()),
        "max": float(array.max()),
        "q1": quartile_1,
        "q3": quartile_3,
        "iqr": quartile_3 - quartile_1,
        "skewness": float(stats.skew(array)) if array.size > 2 else 0.0,
        "kurtosis_excess": float(stats.kurtosis(array)) if array.size > 3 else 0.0,
        "mean_over_median": float(mean / median) if median else None,
    }


def rank_biserial(first: np.ndarray, second: np.ndarray, u_statistic: float) -> float:
    """Effect size for Mann-Whitney U, in [-1, 1].

    It is the probability that a random value from `first` exceeds a random one
    from `second`, rescaled: 0 means complete overlap, ±1 means no overlap.
    """
    denominator = first.size * second.size
    if denominator == 0:
        return 0.0
    return float(2.0 * u_statistic / denominator - 1.0)


def epsilon_squared(h_statistic: float, total: int, groups: int) -> float | None:
    """Effect size for Kruskal-Wallis: the share of rank variance explained."""
    if total <= groups:
        return None
    return float(max(0.0, (h_statistic - groups + 1) / (total - groups)))


def _magnitude(value: float, small: float, medium: float, large: float) -> str:
    size = abs(value)
    if size < small:
        return "negligible"
    if size < medium:
        return "small"
    if size < large:
        return "medium"
    return "large"


def compare_groups(
    values: pd.Series, groups: pd.Series, *, label: str = "value", alpha: float = ALPHA
) -> dict[str, object]:
    """Compare a numeric variable across groups without assuming normality."""
    frame = pd.DataFrame({"value": pd.to_numeric(values, errors="coerce"), "group": groups}).dropna()
    frame = frame[np.isfinite(frame["value"])]

    sizes = frame.groupby("group", observed=True)["value"].size()
    usable = sizes[sizes >= MIN_GROUP_SIZE].index.tolist()
    frame = frame[frame["group"].isin(usable)]
    group_count = len(usable)

    summary = [
        {"group": str(name), **describe(group["value"])}
        for name, group in frame.groupby("group", observed=True)
    ]

    if group_count < 2:
        return {
            "label": label,
            "groups": summary,
            "test": None,
            "reason": (
                f"At least two groups with {MIN_GROUP_SIZE} or more observations "
                f"are needed; found {group_count}."
            ),
        }

    samples = [frame.loc[frame["group"] == name, "value"].to_numpy(dtype=float)
               for name in usable]

    if group_count == 2:
        result = stats.mannwhitneyu(samples[0], samples[1], alternative="two-sided")
        effect = rank_biserial(samples[0], samples[1], float(result.statistic))
        test = {
            "name": "Mann-Whitney U",
            "statistic": float(result.statistic),
            "p_value": float(result.pvalue),
            "significant": bool(result.pvalue < alpha),
            "effect_size": {
                "name": "rank-biserial correlation",
                "value": effect,
                "magnitude": _magnitude(effect, 0.1, 0.3, 0.5),
            },
            "tests": "whether one group's values tend to be larger than the other's",
            "assumes": "independent observations; no distributional assumption",
        }
    else:
        result = stats.kruskal(*samples)
        effect = epsilon_squared(float(result.statistic), int(len(frame)), group_count)
        test = {
            "name": "Kruskal-Wallis H",
            "statistic": float(result.statistic),
            "p_value": float(result.pvalue),
            "significant": bool(result.pvalue < alpha),
            "degrees_of_freedom": group_count - 1,
            "effect_size": {
                "name": "epsilon squared",
                "value": effect,
                "magnitude": None if effect is None else _magnitude(effect, 0.01, 0.06, 0.14),
            },
            "tests": "whether at least one group differs from the others",
            "assumes": "independent observations; no distributional assumption",
            "note": (
                "A significant result does not say which groups differ; that "
                "needs pairwise tests with a multiplicity correction."
            ),
        }

    test["alpha"] = alpha
    test["large_sample_warning"] = bool(len(frame) > 10_000)
    if test["large_sample_warning"]:
        test["interpretation_note"] = (
            "With this many observations almost any difference is statistically "
            "significant. Read the effect size, not the p-value."
        )

    return {
        "label": label,
        "groups": summary,
        "excluded_small_groups": [str(name) for name in sizes[sizes < MIN_GROUP_SIZE].index],
        "test": test,
    }


def normality_check(values: pd.Series) -> dict[str, object]:
    """Shape evidence instead of a normality test.

    With a million rows Shapiro-Wilk rejects normality for trivial deviations,
    so the honest answer is the shape itself: skewness, excess kurtosis and the
    gap between mean and median. The report says *how* non-normal the data is
    rather than reporting a foregone p-value (§12.6).
    """
    summary = describe(values)
    if summary.get("n", 0) < 8:
        return {"available": False, "reason": "Too few observations."}

    skewness = summary["skewness"]
    kurtosis = summary["kurtosis_excess"]
    return {
        "available": True,
        "n": summary["n"],
        "skewness": skewness,
        "kurtosis_excess": kurtosis,
        "mean_over_median": summary["mean_over_median"],
        "verdict": (
            "approximately symmetric" if abs(skewness) < 0.5
            else "moderately skewed" if abs(skewness) < 1.0
            else "strongly right-skewed" if skewness > 0
            else "strongly left-skewed"
        ),
        "note": (
            "A normality hypothesis test is deliberately not reported: at this "
            "sample size it rejects for deviations too small to matter. The "
            "shape statistics and a Q-Q plot are more informative."
        ),
    }
