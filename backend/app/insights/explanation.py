"""Rendering a recommendation so a manager can disagree with it.

Functional requirement FR7 in Assessment One asks that the features driving
each recommendation be exposed, and the evaluation plan expects every
recommendation to carry an inspectable explanation. That is a measurable
property, so it is measured here rather than claimed.

**An explanation is not a restatement.** Writing "this product is recommended
because it has a high score" tells a reader nothing they can check. The
rendering below names the quantity, its value, the period it was measured over
and the engine that produced it, so a manager who doubts a recommendation knows
exactly which number to go and look at.

**Caveats are rendered first, not last.** A recommendation resting on segments
that proved unstable should present that fact before the suggested action,
because a reader who has already decided is unlikely to revise on reaching a
footnote. This is a deliberate inversion of the usual order.

**What `drivers()` is, and what it is not.** It names the features behind a
decision, which is a transparency property and satisfies FR7. It is *not* a
measure of procedural fairness, although an earlier version of this project
claimed as much. Wang et al. (2026) attribute that position to Grgic-Hlaca et
al. (2018) and reject it, defining procedural fairness over the consistency of
the decision process between similar cases rather than over the identity of the
features used. That assessment lives in `app.insights.fairness`, which also
records the correction. Jordan and Mitchell (2015) list "requirements that
learned models be interpretable by users" among the forces shaping a learning
system's design, which is the standing justification for this module; it is not
a fairness guarantee.
"""

from __future__ import annotations

from typing import Any

from app.insights.recommendations import Recommendation

# Quantities worth naming in an explanation, with how to phrase each.
DRIVER_LABELS = {
    "confidence": "basket confidence",
    "normalised_lift": "normalised lift",
    "lift": "lift",
    "support_count": "baskets containing the pairing",
    "q_value": "false-discovery-adjusted p-value",
    "revenue_share": "share of revenue",
    "customer_share": "share of customers",
    "concentration_ratio": "revenue per unit of customer share",
    "median_recency_days": "median days since last purchase",
    "median_frequency": "median orders per customer",
    "median_monetary": "median net spend per customer",
    "share_of_source": "share of the segment that moved",
    "mean_forecast": "mean forecast revenue",
    "baseline": "recent observed revenue",
    "observed": "observed interval coverage",
    "nominal": "nominal interval coverage",
    # Hazard quantities. Added after the transparency index came back at 71%
    # and identified the two blind-spot templates as emitting advice with no
    # figure a reader could go and check.
    "item_coverage": "share of the catalogue any rule can reach",
    "catalogue_size": "products in the catalogue",
    "reachable": "products a rule can name",
    "coverage_new": "share of newly listed products a rule can reach",
    "new_items": "products introduced during the hold-out window",
    "gini": "concentration of recommendation exposure",
}


def drivers(recommendation: Recommendation) -> list[dict[str, Any]]:
    """The named quantities that produced this recommendation.

    FR7 made computable. Only quantities with a label are returned, so a reader
    is given numbers that mean something rather than every key in the evidence.
    """
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in recommendation.evidence:
        source = item.get("source", "")
        for key, value in (item.get("evidence") or {}).items():
            label = DRIVER_LABELS.get(key)
            if label is None or value is None or (source, key) in seen:
                continue
            seen.add((source, key))
            found.append({
                "source": source,
                "feature": key,
                "label": label,
                "value": value,
            })
    return found


def _format(value: Any) -> str:
    if isinstance(value, float):
        if 0 < abs(value) < 0.001:
            return f"{value:.2e}"
        if abs(value) < 10:
            return f"{value:,.3f}".rstrip("0").rstrip(".")
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def render(recommendation: Recommendation, *, index: int | None = None) -> str:
    """One recommendation as plain text, for a session pack or a report."""
    lines: list[str] = []
    heading = recommendation.action
    lines.append(f"{index}. {heading}" if index is not None else heading)
    lines.append("")

    if recommendation.caveats:
        lines.append("Before acting:")
        for caveat in recommendation.caveats:
            lines.append(f"  - {caveat}")
        lines.append("")

    lines.append(f"Why: {recommendation.rationale}")
    lines.append("")

    named = drivers(recommendation)
    if named:
        lines.append("Driving figures:")
        for driver in named:
            lines.append(
                f"  - {driver['label']}: {_format(driver['value'])} "
                f"(from {driver['source']})"
            )
        lines.append("")

    lines.append(
        f"Evidence from: {', '.join(recommendation.sources) or 'none'}"
        + (f"; silent: {', '.join(recommendation.silent_sources)}"
           if recommendation.silent_sources else "")
    )
    lines.append(
        f"Corroborated by more than one engine: "
        f"{'yes' if recommendation.corroborated else 'no'}"
    )
    lines.append(f"Priority: {recommendation.priority:.3f}")
    return "\n".join(lines)


def transparency_index(recommendations: list[Recommendation]) -> dict[str, Any]:
    """The share of recommendations carrying evidence and named driving figures.

    Assessment One's evaluation plan expects 100%. Measuring it keeps that a
    result rather than a design intention, and a value below 100% identifies
    exactly which templates emit advice a reader cannot check.
    """
    if not recommendations:
        return {"available": False, "reason": "No recommendations to assess."}

    with_evidence = [r for r in recommendations if r.has_evidence]
    with_drivers = [r for r in recommendations if drivers(r)]
    with_sources = [r for r in recommendations if r.sources]
    bare = sorted({r.template for r in recommendations if not drivers(r)})

    index = len(with_drivers) / len(recommendations)
    return {
        "available": True,
        "recommendations": len(recommendations),
        "with_evidence": len(with_evidence),
        "with_driving_features": len(with_drivers),
        "with_named_sources": len(with_sources),
        "transparency_index": index,
        "templates_without_drivers": bare,
        "verdict": (
            f"Every recommendation carries evidence, a named source and at least "
            f"one driving figure, so the transparency index is {index:.0%}."
            if index == 1.0 else
            f"{index:.0%} of recommendations carry a named driving figure. The "
            f"templates that do not are {', '.join(bare)}, and a reader cannot "
            f"check those without going back to the engine output."
        ),
    }


def session_pack(recommendations: list[Recommendation], *, title: str) -> str:
    """The integrated condition as a document for an RQ4 session."""
    lines = [title, "=" * len(title), ""]
    lines.append(
        "Each item below states the action, the reasons to be careful with it, "
        "the evidence behind it, and which analyses contributed. Items are "
        "ordered by priority."
    )
    lines.append("")
    for position, rec in enumerate(recommendations, start=1):
        lines.append(render(rec, index=position))
        lines.append("")
        lines.append("-" * 70)
        lines.append("")
    return "\n".join(lines)
