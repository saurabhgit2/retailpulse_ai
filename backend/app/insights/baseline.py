"""The control condition for RQ4: the same analyses, presented separately.

RQ4 asks whether integrating the three engines produces decision support that
is measurably more actionable and more trustworthy than the same components
used in isolation. Answering it needs the isolated condition to exist, built
from identical data, so that any difference a participant reports is a
difference of presentation rather than of content.

**This module is the control, and it has to be a fair one.** The temptation in
building a baseline you intend to beat is to make it worse than the thing it
stands for. So the rule followed here is that the baseline contains every
number the integrated condition contains. Nothing is withheld, nothing is
degraded, and the same thresholds select the same underlying signals.

What the baseline cannot do is structural rather than a matter of effort:

- it cannot order the three lists against each other, because the three engines
  produce no common scale on which a rule and a segment could be compared;
- it cannot mark a finding as corroborated, because corroboration is a property
  of the join rather than of either list;
- it cannot carry one engine's measured reliability into another's output;
- it cannot tell a reader which engine was silent about a subject, because each
  list only knows its own subjects.

Those four absences are what a manager compensates for by reading three reports
and reconciling them in their head. Measuring that cost is the experiment.
"""

from __future__ import annotations

from typing import Any

from app.insights.reliability import Reliability
from app.insights.signals import Signal

# The three lists are capped at the same depth so neither condition wins by
# volume alone.
DEFAULT_PER_LIST = 10


def _entry(signal: Signal) -> dict[str, Any]:
    """One line of a single-engine report, with the engine's own evidence."""
    return {
        "subject": str(signal.subject),
        "scope": signal.subject.scope.value,
        "statement": signal.summary,
        "kind": signal.kind,
        "magnitude": signal.magnitude,
        "evidence": signal.evidence,
    }


def isolated_presentation(
    signals: list[Signal],
    reliabilities: dict[str, Reliability],
    *,
    per_list: int = DEFAULT_PER_LIST,
) -> dict[str, Any]:
    """Three separate reports, each ranked by its own engine's measure.

    Each list is ordered the way that engine would order its own output,
    because that is what a manager reading three tools actually sees. No
    cross-list ordering is attempted, since none is available without the join.
    """
    lists: dict[str, list[dict[str, Any]]] = {}
    for source in ("forecast", "segmentation", "association"):
        rows = [s for s in signals if s.source == source]
        rows.sort(key=lambda s: -abs(s.magnitude))
        lists[source] = [_entry(s) for s in rows[:per_list]]

    return {
        "lists": lists,
        "reliability": {k: v.as_dict() for k, v in reliabilities.items()},
        "items": sum(len(v) for v in lists.values()),
        "structural_limits": [
            "The three lists cannot be ordered against one another, because the "
            "engines share no common scale.",
            "No item can be marked as corroborated, since corroboration is a "
            "property of the join between lists.",
            "Reliability is reported per engine and cannot be attached to an "
            "individual item from another engine.",
            "No list can report which other engine was silent about a subject.",
        ],
        "note": (
            "Built from the same signals, the same thresholds and the same "
            "underlying runs as the integrated condition. Nothing is withheld; "
            "only the join is absent."
        ),
    }


def reconciliation_burden(
    integrated: list[Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    """What a reader must do themselves in the isolated condition.

    Reported as counts rather than as a claim about difficulty. How hard the
    reconciliation is for a person is exactly what the RQ4 sessions measure,
    and asserting it here would pre-empt the result the experiment exists to
    produce.
    """
    corroborated = [r for r in integrated if getattr(r, "corroborated", False)]
    with_caveats = [r for r in integrated if getattr(r, "caveats", [])]

    return {
        "integrated_items": len(integrated),
        "baseline_items": baseline["items"],
        "baseline_lists": len(baseline["lists"]),
        "cross_list_comparisons_required": baseline["items"] * (len(baseline["lists"]) - 1),
        "corroborated_items_available_only_when_integrated": len(corroborated),
        "items_carrying_an_explicit_caveat": len(with_caveats),
        "note": (
            f"The isolated condition presents {baseline['items']} items across "
            f"{len(baseline['lists'])} lists with no ordering between them, so a "
            f"reader comparing each item against the other lists performs "
            f"{baseline['items'] * (len(baseline['lists']) - 1)} comparisons to "
            f"reach the position the integrated condition starts from. Whether "
            f"that cost matters is what the RQ4 sessions measure."
        ),
    }


def session_pack(baseline: dict[str, Any], *, title: str) -> str:
    """The isolated condition as a document, for the control arm of a session."""
    headings = {
        "forecast": "Demand forecast report",
        "segmentation": "Customer segmentation report",
        "association": "Market basket report",
    }
    lines = [title, "=" * len(title), ""]
    lines.append(
        "Three reports, produced independently. They are not ordered against "
        "one another."
    )
    lines.append("")

    for source, rows in baseline["lists"].items():
        heading = headings.get(source, source)
        lines.append(heading)
        lines.append("-" * len(heading))
        reliability = baseline["reliability"].get(source, {})
        if reliability.get("basis"):
            lines.append(f"Reliability of this analysis: {reliability['basis']}")
            lines.append("")
        if not rows:
            lines.append("  No findings.")
        for position, row in enumerate(rows, start=1):
            lines.append(f"  {position}. {row['statement']}")
        lines.append("")
    return "\n".join(lines)
