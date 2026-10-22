"""Ordering recommendations, using only quantities this dataset supports.

Assessment One proposed a composite actionability score combining statistical
interest with margin contribution and inventory feasibility. Online Retail II
records unit price and quantity and carries neither product cost nor stock
level, so two of those three components were never computable. Substituting a
plausible-looking proxy - treating price as margin, say - would have produced a
number that looked rigorous and meant nothing.

What remains is three components the data does support:

**Revenue at stake** places a recommendation about the segment holding 81.7% of
revenue above one about a segment holding 3%. Where a recommendation has no
monetary quantity attached, this component is zero and the omission is visible
in the ranking evidence rather than filled in with an average.

**Evidence weight** is the reliability of the engine that produced the signal,
computed in `reliability.py` from out-of-sample performance. A recommendation
resting on segments that proved unstable ranks below one resting on rules that
all survived their hold-out.

**Corroboration** is the integration premium, and it is the component that only
an integrated platform can compute. A finding more than one engine spoke about
is ranked above an otherwise identical finding from a single engine. The
isolated-component baseline in `baseline.py` has no access to this term, which
is what makes the RQ4 comparison a comparison of something.

**The weights are declared in the experiment configuration and hashed with it.**
Adjusting them after seeing which recommendations reached the top would be
choosing the answer.

**On what this score is and is not.** Jordan and Mitchell (2015) describe a
learning problem as a task, a performance measure and a training experience,
and note that the performance measure is a choice rather than a given: one may
"define a different performance metric that assigns a higher penalty" to one
error direction than the other. Their example is a fraud classifier penalised
more for missing fraud than for a false alarm; the retail equivalent is the
asymmetry between a stockout and overstock.

Priority here is an attention-ordering measure, not a cost model. It answers
which recommendation to read first, and it is symmetric: it does not know that
acting on a wrong recommendation and ignoring a right one cost different
amounts. That asymmetry is real, and this project handles it in two other
places rather than hiding it inside this score - in the forecasting evaluation,
which reports symmetric and asymmetric cost rankings side by side, and in the
RQ4 session measures, which record acceptance of a poor recommendation
separately from rejection of a sound one. Naming the performance measure, and
its limits, is the discipline Jordan and Mitchell ask for.
"""

from __future__ import annotations

from typing import Any

from app.insights.recommendations import Recommendation

DEFAULT_WEIGHTS = {
    "revenue_at_stake": 0.40,
    "evidence_weight": 0.40,
    "corroboration": 0.20,
}


class RankingError(ValueError):
    """The weights are unusable, raised before anything is ranked."""


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    missing = set(DEFAULT_WEIGHTS) - set(weights)
    if missing:
        raise RankingError(
            f"Missing weight(s) {sorted(missing)}. Every component must be given "
            f"a weight in the configuration, including zero, so that omitting one "
            f"is a visible decision rather than a default."
        )
    unknown = set(weights) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise RankingError(f"Unknown weight(s) {sorted(unknown)}.")
    if any(value < 0 for value in weights.values()):
        raise RankingError("Weights cannot be negative.")
    total = sum(weights.values())
    if total <= 0:
        raise RankingError("Weights sum to zero, so every recommendation would tie.")
    return {k: v / total for k, v in weights.items()}


def _revenue_component(recommendations: list[Recommendation]) -> dict[str, float]:
    """Revenue at stake, scaled against the largest in this set.

    Relative rather than absolute, because the question the ranking answers is
    which of these to read first. A recommendation with no revenue attached
    scores zero here and is not penalised elsewhere for it.
    """
    values = [
        r.revenue_at_stake for r in recommendations if r.revenue_at_stake is not None
    ]
    largest = max(values) if values else 0.0
    if largest <= 0:
        return {r.key: 0.0 for r in recommendations}
    return {
        r.key: (r.revenue_at_stake / largest if r.revenue_at_stake else 0.0)
        for r in recommendations
    }


def rank(
    recommendations: list[Recommendation],
    *,
    weights: dict[str, float] | None = None,
) -> list[Recommendation]:
    """Score every recommendation and return them in priority order."""
    normalised = validate_weights(dict(weights or DEFAULT_WEIGHTS))
    revenue = _revenue_component(recommendations)

    for rec in recommendations:
        components = {
            "revenue_at_stake": revenue[rec.key],
            "evidence_weight": rec.evidence_weight,
            "corroboration": 1.0 if rec.corroborated else 0.0,
        }
        rec.priority = sum(normalised[k] * v for k, v in components.items())
        rec.evidence.append({
            "source": "ranking",
            "kind": "priority_components",
            "summary": (
                f"Priority {rec.priority:.3f} from revenue {components['revenue_at_stake']:.2f}, "
                f"evidence {components['evidence_weight']:.2f}, corroboration "
                f"{components['corroboration']:.0f}."
            ),
            "evidence": {"components": components, "weights": normalised},
        })

    return sorted(
        recommendations,
        key=lambda r: (-r.priority, -r.evidence_weight, r.key),
    )


def explain_weights(weights: dict[str, float] | None = None) -> dict[str, Any]:
    """The weighting, stated so a reader can disagree with it."""
    normalised = validate_weights(dict(weights or DEFAULT_WEIGHTS))
    return {
        "weights": normalised,
        "components": {
            "revenue_at_stake": (
                "Share of the largest monetary quantity in the set. Zero where no "
                "monetary quantity could be attached."
            ),
            "evidence_weight": (
                "Reliability of the engine that produced the signal, computed from "
                "its out-of-sample performance."
            ),
            "corroboration": (
                "One where more than one engine spoke about the subject, zero "
                "otherwise. Only an integrated view can compute this term."
            ),
        },
        "excluded": (
            "Margin contribution and inventory feasibility were proposed in "
            "Assessment One and are absent here, because Online Retail II records "
            "neither product cost nor stock level. A proxy would have made the "
            "score look more complete without making it more informative."
        ),
    }
