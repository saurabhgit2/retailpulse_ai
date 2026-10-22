"""How much each engine's output deserves to be believed, taken from its own evidence.

This is the mechanism that makes the insight layer worth building, so it comes
first.

A dashboard that merges three analyses usually presents them as equals. The
forecast, the segment and the rule each appear in a panel of the same size, in
the same typeface, with the same implied authority. Nothing on the screen
records that one of those three validated well out of sample and another did
not.

RetailPulse measured all three. The forecasting experiment found that empirical
80% prediction intervals covered 25% of hold-out observations. The segmentation
experiment found Adjusted Rand Indices between 0.22 and 0.39 across three
clustering families, which is instability. The association experiment found
every mined rule still holding on a period it was not mined from. Those three
results are not equally trustworthy, and a recommendation built from them
should say so.

So every signal inherits a reliability score computed from the engine's own
out-of-sample evidence, and that score travels into the recommendation, the
ranking and the explanation. A recommendation resting on unstable segments is
marked as resting on unstable segments.

**The bands are declared, not tuned.** The thresholds below were fixed before
the first reconciliation ran. Choosing them afterwards, once it was visible
which engine they favoured, would be choosing the answer - the same discipline
the experiment configurations follow.

**What this deliberately does not do.** It does not combine the three scores
into one number for the platform. Reliability is a property of a source with
respect to a question, and an average across three different questions would
mean nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Declared before the first run. See the module docstring.
STRONG, MODERATE = 0.70, 0.40

# A forecast whose weighted absolute percentage error exceeds this on the
# hold-out is treated as weak evidence whatever its cross-validation score,
# because the hold-out is the only period it did not see.
WAPE_WEAK = 30.0
WAPE_STRONG = 15.0

# Interval coverage is scored by how far observed coverage falls short of
# nominal. Intervals that are too wide are conservative and cost little;
# intervals that are too narrow understate risk, which is the failure that
# matters to a stock decision.
COVERAGE_TOLERANCE = 0.15


@dataclass(frozen=True)
class Reliability:
    """One engine's trustworthiness, with the evidence that produced it."""

    source: str
    score: float
    band: str
    basis: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_weak(self) -> bool:
        return self.score < MODERATE

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "score": round(self.score, 3),
            "band": self.band,
            "basis": self.basis,
            "evidence": self.evidence,
        }


def _band(score: float) -> str:
    return "strong" if score >= STRONG else "moderate" if score >= MODERATE else "weak"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def unavailable(source: str, reason: str) -> Reliability:
    """An engine that produced no usable validation evidence.

    Scored at zero rather than at some neutral midpoint. A source that cannot
    show how it performed out of sample has not earned a default level of
    trust, and silently assigning one is how unvalidated output acquires the
    authority of validated output.
    """
    return Reliability(source=source, score=0.0, band="unknown", basis=reason)


def forecast_reliability(run: dict[str, Any]) -> Reliability:
    """From hold-out error and interval coverage, never from cross-validation.

    Cross-validation scores are what the model was selected on, so using them
    here would ask the model to grade its own selection. The hold-out was
    scored once and is the only evidence of behaviour on unseen data.

    Two components, multiplied rather than averaged: accuracy and honesty about
    uncertainty. A model with a good point forecast and intervals that miss
    three quarters of observations is not a reliable basis for a stock
    decision, and averaging would let the good half hide the bad half.
    """
    holdout = run.get("holdout") or []
    selected = (run.get("selection") or {}).get("selected_model")
    if not holdout:
        return unavailable("forecast", "No hold-out scores were recorded.")

    scored = {row.get("model"): row for row in holdout if row.get("mean_wape") is not None}
    if not scored:
        return unavailable("forecast", "No model produced a hold-out score.")

    # The selected model if it was scored; otherwise the best hold-out score,
    # with the substitution recorded.
    row = scored.get(selected)
    substituted = row is None
    if substituted:
        model, row = min(scored.items(), key=lambda kv: kv[1]["mean_wape"])
    else:
        model = selected

    wape = float(row["mean_wape"])
    accuracy = _clamp((WAPE_WEAK - wape) / (WAPE_WEAK - WAPE_STRONG))

    coverage = (run.get("intervals") or {}).get("coverage") or {}
    nominal = coverage.get("nominal")
    observed = coverage.get("observed")
    if nominal is None or observed is None:
        honesty, coverage_note = 0.5, "No interval coverage was measured."
    else:
        shortfall = max(0.0, float(nominal) - float(observed))
        honesty = _clamp(1.0 - shortfall / COVERAGE_TOLERANCE) if shortfall else 1.0
        coverage_note = (
            f"{float(observed):.0%} observed against {float(nominal):.0%} nominal"
        )

    score = accuracy * honesty
    basis = (
        f"Hold-out WAPE {wape:.2f} for {model}; prediction intervals {coverage_note}."
        + (" The selected model carried no hold-out score, so the best-scoring "
           "model was used and the substitution is recorded."
           if substituted else "")
    )
    return Reliability(
        source="forecast",
        score=score,
        band=_band(score),
        basis=basis,
        evidence={
            "model": model,
            "holdout_wape": wape,
            "accuracy_component": round(accuracy, 3),
            "interval_component": round(honesty, 3),
            "interval_coverage": coverage or None,
            "selected_model_scored": not substituted,
        },
    )


def segmentation_reliability(run: dict[str, Any]) -> Reliability:
    """From cross-window stability, which is what RQ2 was written to measure.

    Silhouette and the other internal indices describe how tidy a partition
    looks on the data it was fitted to. None of them indicates whether the same
    customers would be grouped the same way next quarter, and a campaign is
    built on the second question. The Adjusted Rand Index across windows is
    used, with retention share reported beside it.

    Where several clustering families were run, the weakest is taken. A
    segmentation is only as dependable as the agreement between methods; if
    k-means and a Gaussian mixture disagree about who belongs together, the
    higher of the two is not the safer number to carry forward.
    """
    stability = run.get("stability") or {}
    scored = {
        algorithm: result for algorithm, result in stability.items()
        if isinstance(result, dict) and result.get("mean_adjusted_rand") is not None
    }
    if not scored:
        return unavailable("segmentation", "No cross-window stability was measured.")

    weakest, result = min(
        scored.items(), key=lambda kv: kv[1]["mean_adjusted_rand"]
    )
    ari = float(result["mean_adjusted_rand"])
    retention = result.get("mean_retention_share")

    # ARI is already a chance-corrected agreement in [0, 1] for partitions that
    # agree at all, so it is used directly rather than rescaled.
    score = _clamp(ari)
    basis = (
        f"Weakest of {len(scored)} clustering families is {weakest} at mean "
        f"Adjusted Rand Index {ari:.3f}"
        + (f" with {float(retention):.0%} of customers retained." if retention else ".")
    )
    return Reliability(
        source="segmentation",
        score=score,
        band=_band(score),
        basis=basis,
        evidence={
            "weakest_algorithm": weakest,
            "mean_adjusted_rand": ari,
            "mean_retention_share": retention,
            "families_compared": sorted(scored),
            "all_scores": {a: r["mean_adjusted_rand"] for a, r in scored.items()},
        },
    )


def association_reliability(run: dict[str, Any]) -> Reliability:
    """From the share of rules still holding on a period they were not mined on.

    The hold-out survival rate answers precisely the question a manager is
    entitled to ask of a rule: if I act on this next quarter, will it still be
    true? Where the rank correlation of lift between periods is also recorded,
    it moderates the rate, because a rule set whose members all survive while
    their ordering reshuffles supports a different kind of action from one
    whose ordering holds.
    """
    validation = run.get("holdout_validation") or {}
    if not validation.get("available"):
        return unavailable(
            "association",
            validation.get("reason", "No hold-out validation was performed."),
        )

    rate = float(validation.get("survival_rate", 0.0))
    correlation = validation.get("lift_rank_correlation")
    judged = int(validation.get("judged", 0))

    if correlation is None:
        score = _clamp(rate)
        ordering = ""
    else:
        # Ordering counts for a quarter: a surviving rule is useful even where
        # its rank moved, so the rate dominates.
        score = _clamp(0.75 * rate + 0.25 * _clamp(float(correlation)))
        ordering = f" Lift ranking correlates at {float(correlation):.2f} across periods."

    basis = (
        f"{rate:.1%} of {judged:,} judged rules held on baskets they were not "
        f"mined from.{ordering}"
    )
    return Reliability(
        source="association",
        score=score,
        band=_band(score),
        basis=basis,
        evidence={
            "survival_rate": rate,
            "judged": judged,
            "survived": validation.get("survived"),
            "failed": validation.get("failed"),
            "lift_rank_correlation": correlation,
        },
    )


def assess(
    forecast: dict[str, Any] | None,
    segmentation: dict[str, Any] | None,
    association: dict[str, Any] | None,
) -> dict[str, Reliability]:
    """All three engines, including the ones that produced nothing."""
    return {
        "forecast": (
            forecast_reliability(forecast) if forecast
            else unavailable("forecast", "No forecasting run was supplied.")
        ),
        "segmentation": (
            segmentation_reliability(segmentation) if segmentation
            else unavailable("segmentation", "No segmentation run was supplied.")
        ),
        "association": (
            association_reliability(association) if association
            else unavailable("association", "No association run was supplied.")
        ),
    }


def summarise(assessed: dict[str, Reliability]) -> dict[str, Any]:
    """The reliability table a reader needs before reading any recommendation."""
    rows = [r.as_dict() for r in assessed.values()]
    weak = [r.source for r in assessed.values() if r.is_weak and r.band != "unknown"]
    missing = [r.source for r in assessed.values() if r.band == "unknown"]
    return {
        "rows": rows,
        "weak_sources": weak,
        "unavailable_sources": missing,
        "note": (
            "Each score comes from that engine's own out-of-sample evidence and "
            "is carried into every recommendation built from it. The three are "
            "deliberately not averaged, because they answer different questions "
            "and a combined figure would describe nothing."
        ),
        "caveat": (
            f"Evidence from {', '.join(weak)} is weak and every recommendation "
            f"resting on it says so."
            if weak else
            "No source fell into the weak band."
        ),
    }
