"""Turning findings into something a category manager can act on.

A recommendation here is a decision item with four parts fixed by construction:
an action a person can take, the subject it applies to, the evidence that
produced it, and the caveats that evidence carries. Nothing is emitted without
all four, which is what lets the transparency index in `explanation.py` be
computed rather than asserted.

**The templates are deliberately few.** Each corresponds to a signal
combination the three engines actually produce, and each was written against a
real result rather than imagined in advance. A template with no supporting
signal would generate empty advice, and a manager reading advice with no
evidence behind it learns to distrust all of it.

**Nothing here scores business value.** Assessment One proposed ranking by
margin contribution and inventory feasibility, and Online Retail II records
neither cost nor stock. Rather than substituting a plausible-looking proxy,
priority is computed in `ranking.py` from quantities the data supports:
revenue at stake, the reliability of the engine that produced the evidence,
and whether more than one engine contributed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.insights.reconcile import Finding
from app.insights.signals import Scope

# A segment holding this much more revenue than its share of customers is
# concentrated enough to warrant separate handling.
CONCENTRATION_THRESHOLD = 1.5


@dataclass
class Recommendation:
    """One action, with everything needed to judge whether to take it."""

    key: str
    template: str
    action: str
    subject: dict[str, str]
    rationale: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    silent_sources: list[str] = field(default_factory=list)
    corroborated: bool = False
    evidence_weight: float = 0.0
    revenue_at_stake: float | None = None
    priority: float = 0.0

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "template": self.template,
            "action": self.action,
            "subject": self.subject,
            "rationale": self.rationale,
            "priority": round(self.priority, 4),
            "corroborated": self.corroborated,
            "sources": self.sources,
            "silent_sources": self.silent_sources,
            "evidence_weight": round(self.evidence_weight, 3),
            "revenue_at_stake": self.revenue_at_stake,
            "evidence": self.evidence,
            "caveats": self.caveats,
        }


def _caveats_from(finding: Finding) -> list[str]:
    """Every reason to treat this recommendation with care, stated up front."""
    caveats: list[str] = []
    seen: set[str] = set()
    for signal in finding.signals:
        rel = signal.reliability
        if rel and rel.band in {"weak", "unknown"} and rel.source not in seen:
            seen.add(rel.source)
            caveats.append(
                f"Evidence from {rel.source} is {rel.band}: {rel.basis}"
            )
    for conflict in finding.conflicts:
        if conflict["kind"] == "between_sources":
            caveats.append(
                f"Sources disagree about direction: "
                f"{', '.join(conflict['favourable'])} favourable against "
                f"{', '.join(conflict['adverse'])} adverse."
            )
        else:
            caveats.append(
                f"{conflict['source']} produced both favourable and adverse "
                f"signals for this subject."
            )
    return caveats


def _silent(finding: Finding, all_sources: list[str]) -> list[str]:
    """Engines that said nothing about this subject.

    Reported on every recommendation. A reader who cannot tell the difference
    between an engine that agreed and an engine that was never asked is being
    given false assurance.
    """
    return sorted(set(all_sources) - set(finding.sources))


def build(
    findings: list[Finding],
    *,
    total_revenue: float | None = None,
    all_sources: tuple[str, ...] = ("forecast", "segmentation", "association"),
) -> list[Recommendation]:
    """Every recommendation the findings support, unranked."""
    out: list[Recommendation] = []
    for finding in findings:
        kinds = {s.kind for s in finding.signals}
        base = dict(
            subject=finding.subject.as_dict(),
            evidence=[s.as_dict() for s in finding.signals],
            caveats=_caveats_from(finding),
            sources=finding.sources,
            silent_sources=_silent(finding, list(all_sources)),
            corroborated=finding.corroborated,
            evidence_weight=finding.evidence_weight,
        )

        if "durable_pairing" in kinds or "pairing" in kinds:
            out.append(_pairing(finding, base))
        if "revenue_concentration" in kinds:
            rec = _concentration(finding, base, total_revenue)
            if rec:
                out.append(rec)
        if "segment_outflow" in kinds:
            out.append(_outflow(finding, base))
        if "demand_direction" in kinds:
            out.append(_demand(finding, base))
        if "catalogue_blind_spot" in kinds or "new_product_blind_spot" in kinds:
            out.append(_blind_spot(finding, base))
    return out


def _signal(finding: Finding, kind: str):
    return next((s for s in finding.signals if s.kind == kind), None)


def _pairing(finding: Finding, base: dict[str, Any]) -> Recommendation:
    signal = _signal(finding, "durable_pairing") or _signal(finding, "pairing")
    held = signal.kind == "durable_pairing"
    left = signal.evidence.get("antecedent", [])
    right = signal.evidence.get("consequent", [])
    antecedent, consequent = " + ".join(left), " + ".join(right)
    caveats = list(base["caveats"])
    if not held:
        caveats.append(
            "This rule was not among those confirmed on the hold-out period, so "
            "it rests on the window it was mined from."
        )
    # A rule is directed and a shelf is not. Mining produces A -> B and B -> A
    # as separate rules, and both describe the same physical arrangement, so
    # the key is the unordered set of products. Without this the top of the
    # list fills with the same action stated twice.
    key = "pairing::" + " | ".join(sorted(set(left) | set(right)))
    return Recommendation(
        key=key,
        template="stock_and_display_together",
        action=(
            f"Keep {consequent} available and adjacent wherever {antecedent} is "
            f"stocked or promoted."
        ),
        rationale=signal.summary,
        **{**base, "caveats": caveats},
    )


def _concentration(
    finding: Finding, base: dict[str, Any], total_revenue: float | None
) -> Recommendation | None:
    signal = _signal(finding, "revenue_concentration")
    ratio = float(signal.magnitude)
    if ratio < CONCENTRATION_THRESHOLD:
        return None
    share = float(signal.evidence.get("revenue_share") or 0.0)
    revenue = total_revenue * share if total_revenue else None
    return Recommendation(
        key=f"concentration::{finding.subject.key}",
        template="protect_concentrated_revenue",
        action=(
            f"Handle {finding.subject} separately from the general customer base "
            f"for service levels, stock allocation and contact frequency."
        ),
        rationale=(
            f"{signal.summary} That is {ratio:.1f} times the revenue its size "
            f"would imply, so a change in this group moves the business total "
            f"more than its customer count suggests."
        ),
        revenue_at_stake=revenue,
        **base,
    )


def _outflow(finding: Finding, base: dict[str, Any]) -> Recommendation:
    signal = _signal(finding, "segment_outflow")
    return Recommendation(
        key=f"outflow::{finding.subject.key}::{signal.evidence.get('to')}",
        template="investigate_segment_outflow",
        action=(
            f"Review what changed for customers leaving {finding.subject} before "
            f"the next planning cycle."
        ),
        rationale=signal.summary,
        **base,
    )


def _demand(finding: Finding, base: dict[str, Any]) -> Recommendation:
    signal = _signal(finding, "demand_direction")
    interval = _signal(finding, "interval_understates_risk")
    change = float(signal.magnitude)
    direction = "increase" if change > 0 else "decrease" if change < 0 else "hold"
    scenarios = signal.evidence.get("scenarios")

    # Eshov et al. (2025) present a pessimistic, central and optimistic band and
    # recommend against the spread rather than against a point. Where the
    # forecast supplies interval bounds the action states all three, because a
    # single figure reads as settled and the hold-out showed it is not.
    if scenarios:
        action = (
            f"Plan against a range: revenue between "
            f"{scenarios['pessimistic']:+.0%} and {scenarios['optimistic']:+.0%} "
            f"over the next {signal.evidence.get('horizon')} periods, central "
            f"case {scenarios['central']:+.0%}"
            + (", and size the buffer from the hold-out error rather than from "
               "the stated interval." if interval else ".")
        )
    else:
        action = (
            f"Plan for revenue to {direction} by roughly {abs(change):.0%} over "
            f"the next {signal.evidence.get('horizon')} periods"
            + (", and size the buffer from the hold-out error rather than from "
               "the stated interval." if interval else ".")
        )
    caveats = list(base["caveats"])
    if interval:
        caveats.append(interval.summary)
    return Recommendation(
        key="demand::total",
        template="plan_for_demand_direction",
        action=action,
        rationale=signal.summary,
        **{**base, "caveats": caveats},
    )


def _blind_spot(finding: Finding, base: dict[str, Any]) -> Recommendation:
    signal = (
        _signal(finding, "catalogue_blind_spot")
        or _signal(finding, "new_product_blind_spot")
    )
    new_products = signal.kind == "new_product_blind_spot"
    # Two templates rather than one. A catalogue blind spot concerns products
    # below the support threshold; a new-product blind spot concerns products
    # that did not exist when the rules were mined. They are different
    # decisions resting on different evidence, and grouping them under one
    # template name made the procedural fairness check in `fairness.py` report
    # maximum divergence - correctly, since it was comparing decisions that
    # were never alike. The check found the modelling error, not a fairness
    # problem.
    return Recommendation(
        key=f"blindspot::{finding.subject.key}",
        template=(
            "cover_new_product_blind_spot" if new_products
            else "cover_catalogue_blind_spot"
        ),
        action=(
            "Use a non-rule method for newly listed products until they have "
            "traded long enough to appear in a mined rule."
            if new_products else
            "Treat the rule set as advice about the products it can see, and "
            "keep a separate process for the rest of the catalogue."
        ),
        rationale=signal.summary,
        **base,
    )


def deduplicate(recommendations: list[Recommendation]) -> list[Recommendation]:
    """One recommendation per key, keeping the best evidenced.

    Two windows can produce the same outflow, and a product can appear in
    several rules. Repeating the same action makes a short list look like a
    long one, which is the same failure the association redundancy pruning
    exists to prevent.
    """
    best: dict[str, Recommendation] = {}
    for rec in recommendations:
        current = best.get(rec.key)
        if current is None or rec.evidence_weight > current.evidence_weight:
            best[rec.key] = rec
    return list(best.values())
