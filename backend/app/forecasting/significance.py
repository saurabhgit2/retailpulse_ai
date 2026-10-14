"""Is the ranking in the results table real, or is it noise?

The procedure here is the one Aras et al. (2017) used, reproduced step for
step because it is the right shape for this comparison and because following a
published protocol is easier to defend than inventing one:

1. **Friedman's test** across all models on all series (or all folds) -
   "a non-parametric alternative to one-way ANOVA with repeated measures". The
   null hypothesis is that the forecasting performances do not differ with
   respect to the chosen error measure. They ran it separately for RMSE, MAE,
   MAPE, sMAPE and Theil's U, and rejected the null for all five.
2. **Multiple comparison** between the mean ranks, to find *which* models
   differ - "identifying the source of these differences is of importance...
   to determine specifically which forecasting methods exhibit which specific
   differences".
3. **Bonferroni correction**, because "when multiple-comparison tests are
   performed, the risk of making type-I error increases".

Why a rank test rather than a paired t-test on the errors: the error
distributions are skewed, the folds are few, and the series are on different
scales. Friedman compares each model's *rank within each block*, which is
scale-free and makes no normality assumption. The cost is power, which is the
right trade when the alternative is a confident claim resting on four numbers.

**Blocks must be independent.** Friedman treats the rows as repeated measures
on the same subjects. `splits.rolling_origin_splits` produces non-overlapping
test windows for exactly this reason - overlapping windows would share actuals
between rows and inflate the evidence.

**What it cannot tell you.** A rejected null says the models differ, not that
the best one is best by a useful margin. Report the effect size alongside: on
Auppakorn & Phumchusri's data XGBoost beat stepwise regression 16.7 to 17.35,
a difference that is probably real and almost certainly not worth a change of
system. `compare_models` returns the mean difference next to the p-value so
that distinction is visible.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

# Friedman needs at least three groups; with two it reduces to a sign test,
# which is what `compare_models` falls back to.
MIN_MODELS_FOR_FRIEDMAN = 3
# With very few blocks the chi-square approximation is poor. Reported anyway,
# with the caveat attached, because hiding it would be worse.
MIN_BLOCKS_FOR_RELIABLE_CHI2 = 10


def friedman_test(errors: pd.DataFrame) -> dict[str, object]:
    """Friedman's test on a blocks x models table of errors.

    Each row is a block (a fold, or a series) and each column a model. Lower
    is better, so ranks are assigned ascending within each row.
    """
    frame = errors.dropna(axis=0, how="any")
    blocks, models = frame.shape

    if models < MIN_MODELS_FOR_FRIEDMAN:
        return {
            "available": False,
            "reason": (
                f"Friedman's test needs at least {MIN_MODELS_FOR_FRIEDMAN} models; "
                f"this table has {models}. Use a paired sign test for two."
            ),
            "models": models,
            "blocks": blocks,
        }
    if blocks < 2:
        return {
            "available": False,
            "reason": (
                f"Only {blocks} complete block(s) after dropping rows with a "
                f"missing result. A model that failed on some folds cannot be "
                f"ranked against ones that did not."
            ),
            "models": models,
            "blocks": blocks,
        }

    statistic, p_value = stats.friedmanchisquare(*[frame[c].to_numpy() for c in frame.columns])
    ranks = frame.rank(axis=1, ascending=True)
    mean_ranks = ranks.mean(axis=0).sort_values()

    dropped = int(len(errors) - blocks)
    caveats: list[str] = []
    if blocks < MIN_BLOCKS_FOR_RELIABLE_CHI2:
        caveats.append(
            f"With {blocks} blocks the chi-square approximation behind the p-value "
            f"is approximate. Treat the result as indicative and report the number "
            f"of blocks alongside it."
        )
    if dropped:
        caveats.append(
            f"{dropped} block(s) were dropped because at least one model had no "
            f"result there. The test compares models only where all of them ran."
        )

    return {
        "available": True,
        "test": "Friedman (non-parametric repeated measures)",
        "statistic": float(statistic),
        "p_value": float(p_value),
        "models": models,
        "blocks": blocks,
        "blocks_dropped": dropped,
        "mean_ranks": {name: float(value) for name, value in mean_ranks.items()},
        "best_by_mean_rank": str(mean_ranks.index[0]),
        "reject_null_at_05": bool(p_value < 0.05),
        "interpretation": (
            "The models do not all perform the same on this measure."
            if p_value < 0.05 else
            "No detectable difference between the models on this measure. With "
            "this many blocks that is as likely to mean too little evidence as "
            "genuine equivalence."
        ),
        "caveats": caveats,
        "grounding": (
            "Procedure follows Aras, Deveci Kocakoç & Polat (2017), who used "
            "Friedman's test on each error measure and then Bonferroni-corrected "
            "multiple comparisons to locate the differences."
        ),
    }


def pairwise_comparisons(errors: pd.DataFrame, alpha: float = 0.05) -> pd.DataFrame:
    """Every pair of models, Wilcoxon signed-rank, Bonferroni-corrected.

    The Wilcoxon signed-rank test is the paired non-parametric companion to
    Friedman: it asks whether one model's per-block errors are systematically
    lower than another's, without assuming a distribution. The Bonferroni
    correction multiplies each p-value by the number of comparisons, which with
    seven models is 21 - a correction severe enough that only a real difference
    survives it, which is the point.

    The mean difference is reported next to the p-value so a statistically
    detectable but practically irrelevant gap is visible as such.
    """
    frame = errors.dropna(axis=0, how="any")
    models = list(frame.columns)
    pairs = list(combinations(models, 2))
    if not pairs:
        return pd.DataFrame()

    correction = len(pairs)
    rows = []
    for left, right in pairs:
        a = frame[left].to_numpy(dtype="float64")
        b = frame[right].to_numpy(dtype="float64")
        difference = a - b

        if np.allclose(difference, 0):
            p_value = 1.0
            statistic = 0.0
        else:
            try:
                statistic, p_value = stats.wilcoxon(a, b)
            except ValueError:
                # Too few non-tied pairs for the test to run.
                statistic, p_value = float("nan"), float("nan")

        adjusted = min(1.0, float(p_value) * correction) if p_value == p_value else float("nan")
        rows.append({
            "model_a": left,
            "model_b": right,
            "mean_error_a": float(np.mean(a)),
            "mean_error_b": float(np.mean(b)),
            "mean_difference": float(np.mean(difference)),
            "blocks_a_better": int((difference < 0).sum()),
            "blocks": int(len(difference)),
            "statistic": float(statistic),
            "p_value": float(p_value),
            "p_value_bonferroni": adjusted,
            "significant": bool(adjusted == adjusted and adjusted < alpha),
            "better": left if np.mean(difference) < 0 else right,
        })

    table = pd.DataFrame(rows)
    table.attrs["correction"] = f"Bonferroni, {correction} comparisons"
    table.attrs["alpha"] = alpha
    return table.sort_values("p_value_bonferroni")


def compare_models(errors: pd.DataFrame, alpha: float = 0.05) -> dict[str, object]:
    """The whole procedure: omnibus test, then pairwise, then a plain summary.

    This is what the research CLI calls and what the results chapter quotes.
    It deliberately returns the sentence to write as well as the numbers, so
    the chapter cannot accidentally claim more than the test supports.
    """
    omnibus = friedman_test(errors)
    if not omnibus.get("available"):
        return {"omnibus": omnibus, "pairwise": [], "summary": omnibus.get("reason")}

    pairwise = pairwise_comparisons(errors, alpha=alpha)
    significant = pairwise[pairwise["significant"]] if not pairwise.empty else pairwise

    best = omnibus["best_by_mean_rank"]
    if not omnibus["reject_null_at_05"]:
        summary = (
            f"Friedman's test does not reject the null (p = {omnibus['p_value']:.3f}) "
            f"across {omnibus['blocks']} blocks, so the differences between these "
            f"{omnibus['models']} models are not distinguishable from noise. "
            f"'{best}' has the best mean rank, but that ranking should not be "
            f"presented as a finding."
        )
    elif significant.empty:
        summary = (
            f"Friedman's test rejects the null (p = {omnibus['p_value']:.4f}), so the "
            f"models are not all equivalent, but no individual pair survives the "
            f"Bonferroni correction over {len(pairwise)} comparisons. The honest "
            f"statement is that performance differs overall without the evidence to "
            f"name which pair differs."
        )
    else:
        wins = significant[
            (significant["model_a"] == best) | (significant["model_b"] == best)
        ]
        summary = (
            f"Friedman's test rejects the null (p = {omnibus['p_value']:.4f}). "
            f"'{best}' has the best mean rank ({omnibus['mean_ranks'][best]:.2f}) and "
            f"is significantly better than {len(wins)} of {omnibus['models'] - 1} "
            f"other models after Bonferroni correction. Report the effect sizes: a "
            f"detectable difference is not necessarily a useful one."
        )

    return {
        "omnibus": omnibus,
        "pairwise": pairwise.to_dict(orient="records") if not pairwise.empty else [],
        "significant_pairs": int(len(significant)),
        "comparisons": int(len(pairwise)),
        "alpha": alpha,
        "correction": "Bonferroni",
        "summary": summary,
    }
