"""Grouping signals by what they are about, and reporting where engines agree.

Assessment One described the insight layer as the substantive novelty: instead
of presenting three sets of output side by side, it reconciles them. This
module is that step, and it has one honest complication to handle.

**Reconciliation needs the engines to be talking about the same thing.** Two
signals corroborate each other only when they share a subject. With the
experiment configurations as they stand, the forecasting engine speaks about
total weekly revenue, segmentation about customer groups, and association about
products, so direct agreement between engines at the same subject is possible
only at business scope.

Rather than manufacturing agreement, this module does two things. Signals at
business scope are attached to every finding as **context**, since a forecast
of falling revenue is relevant to a decision about a segment even though it is
not a statement about that segment. And the reconciliation reports how many
findings had more than one source, so a reader can see how much genuine
cross-engine corroboration the data supported. On the current configuration
that number is small, which is a finding about the integration rather than a
flaw to hide.

**Conflict is reported, not resolved.** Where two sources point in opposite
directions about one subject, the finding records both and is marked. A layer
that silently picked a winner would be making the decision it exists to inform.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.insights.signals import Scope, Signal, Subject


@dataclass
class Finding:
    """Everything known about one subject, from every engine that spoke."""

    subject: Subject
    signals: list[Signal] = field(default_factory=list)
    context: list[Signal] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({s.source for s in self.signals})

    @property
    def corroborated(self) -> bool:
        """More than one engine spoke about this subject.

        Context does not count. A business-level forecast attached to a segment
        finding is useful background and is not a second engine agreeing about
        that segment, and conflating the two would overstate the integration.
        """
        return len(self.sources) > 1

    @property
    def conflicts(self) -> list[dict[str, Any]]:
        by_source: dict[str, set[int]] = defaultdict(set)
        for signal in self.signals:
            if signal.direction:
                by_source[signal.source].add(signal.direction)
        positive = {s for s, d in by_source.items() if 1 in d}
        negative = {s for s, d in by_source.items() if -1 in d}
        both = sorted(positive & negative)
        across = sorted(positive - set(both)), sorted(negative - set(both))
        out: list[dict[str, Any]] = []
        if across[0] and across[1]:
            out.append({
                "kind": "between_sources",
                "favourable": across[0],
                "adverse": across[1],
            })
        for source in both:
            out.append({"kind": "within_source", "source": source})
        return out

    @property
    def evidence_weight(self) -> float:
        """Strongest reliability among the engines that spoke about this subject.

        The strongest rather than the mean: a finding supported by one
        well-validated engine and one poorly validated one is at least as good
        as the well-validated engine alone, and averaging would penalise it for
        receiving extra information.
        """
        return max((s.weight for s in self.signals), default=0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.as_dict(),
            "sources": self.sources,
            "corroborated": self.corroborated,
            "conflicts": self.conflicts,
            "evidence_weight": round(self.evidence_weight, 3),
            "signals": [s.as_dict() for s in self.signals],
            "context": [s.as_dict() for s in self.context],
        }


def reconcile(signals: list[Signal]) -> list[Finding]:
    """One finding per subject, with business-scope signals attached as context.

    Business-scope signals also become findings in their own right, because a
    catalogue blind spot or a forecast that understates risk is a decision item
    and not only background to one.
    """
    grouped: dict[tuple[str, str], Finding] = {}
    for signal in signals:
        key = (signal.subject.scope.value, signal.subject.key)
        finding = grouped.get(key)
        if finding is None:
            finding = Finding(subject=signal.subject)
            grouped[key] = finding
        finding.signals.append(signal)

    context = [s for s in signals if s.subject.scope is Scope.BUSINESS]
    for (scope, _), finding in grouped.items():
        if scope != Scope.BUSINESS.value:
            finding.context = list(context)

    return sorted(
        grouped.values(),
        key=lambda f: (-f.evidence_weight, -len(f.signals), f.subject.key),
    )


def integration_report(findings: list[Finding], signals: list[Signal]) -> dict[str, Any]:
    """How much cross-engine agreement the data actually supported.

    The number that matters for RQ4. An integrated platform claims to say
    things the three components cannot say separately, and the only honest
    version of that claim is a count of how often it did.
    """
    corroborated = [f for f in findings if f.corroborated]
    conflicting = [f for f in findings if f.conflicts]
    by_scope: dict[str, int] = defaultdict(int)
    for finding in findings:
        by_scope[finding.subject.scope.value] += 1

    sources_by_scope: dict[str, set[str]] = defaultdict(set)
    for signal in signals:
        sources_by_scope[signal.subject.scope.value].add(signal.source)
    shared_scopes = sorted(
        scope for scope, sources in sources_by_scope.items() if len(sources) > 1
    )

    return {
        "findings": len(findings),
        "corroborated": len(corroborated),
        "corroborated_share": (
            len(corroborated) / len(findings) if findings else 0.0
        ),
        "with_conflicts": len(conflicting),
        "findings_by_scope": dict(by_scope),
        "sources_by_scope": {k: sorted(v) for k, v in sources_by_scope.items()},
        "scopes_with_multiple_sources": shared_scopes,
        "note": (
            f"{len(corroborated)} of {len(findings)} findings drew on more than one "
            f"engine. Direct agreement is only possible where two engines speak "
            f"about the same kind of subject, which on this configuration happens "
            f"at {', '.join(shared_scopes) if shared_scopes else 'no'} scope."
        ),
        "limitation": (
            "The forecasting experiment targets total weekly revenue, so it "
            "produces no product-level signal and cannot corroborate a product "
            "pairing. Configuring a per-product forecast target would make that "
            "join available without changing this module."
        ),
    }
