"""Model-based feature importance, and whether it agrees with entropy and MI.

This completes §12.7. Phase 4 ranked features by **mutual information** with
the target - an information-theoretic measure computed without fitting any
model. This module ranks the same features by **permutation importance** from
the fitted gradient-boosted model, and then asks whether the two rankings
agree.

**Why that comparison is the interesting part.** The architecture review found
that entropy and mutual information for feature analysis have *no support in
the seventeen supplied papers* - "the only occurrence of 'entropy' in any
retail-relevant paper in that set is classification entropy as a fuzzy
clustering validity index, a different concept". So the honest framing is that
the entropy/MI approach is the author's own proposal. A proposal like that is
strengthened enormously by showing, empirically, how it relates to a standard
method: if MI picks out broadly the features the model actually relies on, the
cheap model-free ranking is a defensible screening tool; if it does not, that
is a finding worth reporting and a limitation worth stating. Either answer is
publishable; only the absence of the comparison is weak.

**Permutation importance, measured out of sample.** A feature's importance is
the *loss in accuracy* when its column is shuffled, breaking its relationship
with the target while leaving its distribution intact. Computed on training
data it reports what the model memorised; computed on held-out data it reports
what the model actually relies on to generalise. This module insists on the
second, which is why it takes a validation frame rather than the training one.

**What it cannot tell you.** Permutation importance is unreliable when features
are strongly correlated: shuffling `lag_1` while `lag_2` remains lets the model
recover most of the signal, so both look unimportant. Retail lag features are
exactly that correlated. The function therefore reports the correlation
structure alongside the scores, and the report should not read a low score for
one of a correlated pair as "this feature does not matter".
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd
from scipy import stats

# Ten shuffles per feature is enough for a stable ordering without making the
# calculation cost more than the fit did.
DEFAULT_REPEATS = 10

# Above this absolute Pearson correlation, two features are near-substitutes
# and permutation importance understates both.
CORRELATION_WARNING = 0.9

# Rankings are compared on the leading features, because the tail of an
# importance ranking is mostly noise in both methods.
DEFAULT_TOP_K = 10


def permutation_importance(
    estimator: Any,
    features: pd.DataFrame,
    target: pd.Series | np.ndarray,
    *,
    n_repeats: int = DEFAULT_REPEATS,
    random_state: int = 20260101,
    scoring: str = "mae",
) -> dict[str, Any]:
    """How much worse the model gets when each feature is shuffled.

    `features` and `target` must be **held out of training**. Passing the
    training frame is the usual mistake and it silently measures the wrong
    thing, so the result records which was used only if the caller says.
    """
    if features.empty:
        return {"available": False, "reason": "No validation rows to permute."}
    if n_repeats < 1:
        raise ValueError(f"n_repeats must be at least 1; got {n_repeats}.")

    matrix = features.to_numpy(dtype="float64")
    truth = np.asarray(pd.Series(target).to_numpy(), dtype="float64")
    score = _scorer(scoring)

    baseline = score(truth, estimator.predict(matrix))
    rng = np.random.default_rng(random_state)

    rows = []
    for position, name in enumerate(features.columns):
        losses = np.empty(n_repeats, dtype="float64")
        for repeat in range(n_repeats):
            shuffled = matrix.copy()
            rng.shuffle(shuffled[:, position])
            # Higher loss after shuffling means the feature was carrying
            # signal. A negative value means the model did *better* without
            # it, which happens for pure noise features and is reported as-is
            # rather than clipped to zero - clipping would hide the fact that
            # a feature is doing nothing.
            losses[repeat] = score(truth, estimator.predict(shuffled)) - baseline
        rows.append({
            "feature": str(name),
            "importance": float(np.mean(losses)),
            "std_dev": float(np.std(losses, ddof=1)) if n_repeats > 1 else 0.0,
            "relative": float(np.mean(losses) / baseline) if baseline else None,
        })

    rows.sort(key=lambda row: row["importance"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    return {
        "available": True,
        "method": f"permutation importance, {n_repeats} shuffles per feature",
        "scoring": scoring,
        "baseline_score": float(baseline),
        "rows": rows,
        "correlated_features": correlated_pairs(features),
        "caveats": [
            "Measured on held-out rows, not training rows: training-set "
            "permutation importance reports what the model memorised.",
            "Permutation importance understates both members of a correlated "
            "pair, because shuffling one leaves the other to carry the signal. "
            "Lag features are strongly correlated by construction - see "
            "`correlated_features` before reading a low score as 'irrelevant'.",
        ],
    }


def _scorer(name: str):
    """Loss functions, all oriented so that lower is better."""
    if name == "mae":
        return lambda y, f: float(np.mean(np.abs(y - f)))
    if name == "rmse":
        return lambda y, f: float(np.sqrt(np.mean((y - f) ** 2)))
    raise ValueError(f"Unknown scoring '{name}'. Use 'mae' or 'rmse'.")


def correlated_pairs(
    features: pd.DataFrame, threshold: float = CORRELATION_WARNING
) -> list[dict[str, Any]]:
    """Feature pairs correlated strongly enough to confound the attribution."""
    numeric = features.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        return []

    correlation = numeric.corr().abs()
    pairs = []
    columns = list(correlation.columns)
    for i, left in enumerate(columns):
        for right in columns[i + 1:]:
            value = correlation.loc[left, right]
            if pd.notna(value) and value >= threshold:
                pairs.append({
                    "features": [str(left), str(right)],
                    "correlation": float(value),
                })
    return sorted(pairs, key=lambda row: row["correlation"], reverse=True)


def rank_agreement(
    model_scores: dict[str, float],
    information_scores: dict[str, float],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    """Do the model's priorities match the information-theoretic ones?

    This is the §12.7 question. `model_scores` is permutation importance;
    `information_scores` is the mutual-information ranking from Phase 4. Both
    map feature name to a score where higher means more important.

    Returns Spearman's rank correlation over the features both methods scored,
    the overlap among the top `k`, and a sentence that does not overclaim -
    with four or five shared features, a correlation of 0.7 is not evidence of
    anything much, and the summary says so.
    """
    shared = sorted(set(model_scores) & set(information_scores))
    if len(shared) < 3:
        return {
            "available": False,
            "reason": (
                f"Only {len(shared)} feature(s) were scored by both methods; "
                f"a rank comparison needs at least 3."
            ),
            "shared_features": shared,
        }

    model_values = [model_scores[name] for name in shared]
    information_values = [information_scores[name] for name in shared]

    correlation, p_value = stats.spearmanr(model_values, information_values)

    k = min(top_k, len(shared))
    model_top = {name for name, _ in sorted(
        model_scores.items(), key=lambda kv: kv[1], reverse=True)[:k]}
    information_top = {name for name, _ in sorted(
        information_scores.items(), key=lambda kv: kv[1], reverse=True)[:k]}
    overlap = model_top & information_top

    thin = len(shared) < 8
    if np.isnan(correlation):
        verdict = "Not computable: one of the rankings has no variation."
    elif correlation >= 0.6:
        verdict = (
            "The two rankings broadly agree, which supports using the "
            "model-free mutual-information screen as a cheap first pass."
        )
    elif correlation <= 0.2:
        verdict = (
            "The two rankings disagree. The model relies on features that "
            "mutual information does not favour, which is a limitation of the "
            "information-theoretic screen worth reporting rather than hiding."
        )
    else:
        verdict = (
            "The rankings agree only weakly. Neither 'MI works' nor 'MI fails' "
            "is supportable from this; report the number and move on."
        )

    return {
        "available": True,
        "features_compared": len(shared),
        "spearman_rho": None if np.isnan(correlation) else float(correlation),
        "p_value": None if np.isnan(p_value) else float(p_value),
        "top_k": k,
        "top_k_overlap": sorted(overlap),
        "top_k_overlap_count": len(overlap),
        "model_top": sorted(model_top),
        "information_top": sorted(information_top),
        "verdict": verdict,
        "caveats": (
            [f"Only {len(shared)} features were compared, so the correlation "
             f"is a weak estimate; do not report it without the count."]
            if thin else []
        ),
        "grounding_note": (
            "The entropy / mutual-information approach to feature analysis has "
            "no support in the seventeen supplied papers. This comparison is "
            "what makes it defensible: it shows empirically how the model-free "
            "screen relates to a standard model-based method, rather than "
            "asserting that it works."
        ),
    }


def to_score_map(rows: Sequence[dict[str, Any]], key: str = "importance") -> dict[str, float]:
    """Importance rows to {feature: score}, for `rank_agreement`."""
    return {
        str(row["feature"]): float(row[key])
        for row in rows
        if row.get(key) is not None
    }
