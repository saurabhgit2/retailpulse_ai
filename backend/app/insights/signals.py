"""Three engines, three vocabularies, one record type.

The forecasting engine emits weighted error rates and prediction intervals. The
segmentation engine emits cluster profiles, Adjusted Rand Indices and migration
flows. The association engine emits rules with support, confidence and four
dependence measures. None of those can be compared with either of the others.

A signal is the common form: something observed, about some subject, pointing
in some direction, with the evidence that produced it and the reliability of
the engine that produced it. Reconciliation then works on signals rather than
on three incompatible result files, which is what makes "two engines agree
about this segment" a computable statement.

**Scope is the part that needs care.** The three engines do not all speak about
the same kind of thing:

- the forecasting experiment as currently configured targets `__TOTAL__`,
  weekly revenue for the whole business, so its signals are BUSINESS scope;
- segmentation speaks about customer groups, so SEGMENT scope;
- association speaks about products, so PRODUCT scope.

Assessment One imagined reconciling "a product with rising forecast demand that
also appears in a high-actionability rule". That join needs per-product
forecasts, and the current configuration does not produce them. Rather than
inventing a product-level forecast, signals carry their scope, business-scope
signals attach to findings as context, and any recommendation that would have
wanted a product forecast records that forecasting was silent at that scope.
Setting a per-product target in the forecasting configuration makes the join
available; nothing here needs to change when it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.insights.reliability import Reliability

# A migration flow smaller than this share of its source cluster is ordinary
# churn at a segment boundary rather than an event worth acting on.
MATERIAL_FLOW = 0.15

# Rules weaker than this on the bounded measure are reported in the rule table
# but do not generate recommendations.
MIN_NORMALISED_LIFT = 0.5


class Scope(str, Enum):
    BUSINESS = "business"
    SEGMENT = "segment"
    PRODUCT = "product"
    CUSTOMER = "customer"


@dataclass(frozen=True)
class Subject:
    """What a signal is about."""

    scope: Scope
    key: str
    label: str = ""

    def __str__(self) -> str:
        return self.label or self.key

    def as_dict(self) -> dict[str, str]:
        return {"scope": self.scope.value, "key": self.key, "label": str(self)}


@dataclass(frozen=True)
class Signal:
    """One observation from one engine, in a form the others can be compared to."""

    source: str
    kind: str
    subject: Subject
    direction: int                       # +1 favourable, -1 adverse, 0 neutral
    magnitude: float                     # engine-specific units, kept raw
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    reliability: Reliability | None = None

    @property
    def weight(self) -> float:
        return self.reliability.score if self.reliability else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "subject": self.subject.as_dict(),
            "direction": self.direction,
            "magnitude": self.magnitude,
            "summary": self.summary,
            "evidence": self.evidence,
            "reliability": self.reliability.as_dict() if self.reliability else None,
        }


# ---------------------------------------------------------------------------
# forecasting
# ---------------------------------------------------------------------------

def from_forecast(run: dict[str, Any], reliability: Reliability) -> list[Signal]:
    """Business-level demand direction and the width of its uncertainty."""
    signals: list[Signal] = []
    intervals = run.get("intervals") or {}
    if not intervals.get("available"):
        return signals

    point = [float(v) for v in intervals.get("point", []) if v is not None]
    actual = [float(v) for v in intervals.get("actual", []) if v is not None]
    if not point:
        return signals

    subject = Subject(Scope.BUSINESS, "__TOTAL__", "Total weekly revenue")
    horizon = len(point)

    # Direction compares the forecast horizon against the observed level it
    # follows. Without actuals the forecast's own trajectory is used, and the
    # weaker basis is recorded.
    if actual:
        baseline = sum(actual) / len(actual)
        basis = "the most recent observed period"
    else:
        baseline = point[0]
        basis = "the first forecast period, no actuals being available"
    mean_point = sum(point) / len(point)
    change = (mean_point - baseline) / baseline if baseline else 0.0

    # Eshov et al. (2025) report their retail lending forecast as a pessimistic,
    # central and optimistic triple rather than a single figure (their Table 9),
    # and make recommendations against the spread. A central figure alone
    # invites a reader to treat it as settled, which is the wrong impression to
    # give when the hold-out showed the intervals understate risk. The bounds
    # come from the forecast's own interval output, so nothing is invented.
    lower = [float(v) for v in intervals.get("lower", []) if v is not None]
    upper = [float(v) for v in intervals.get("upper", []) if v is not None]
    scenarios: dict[str, float] = {}
    if lower and upper and baseline:
        scenarios = {
            "pessimistic": (sum(lower) / len(lower) - baseline) / baseline,
            "central": change,
            "optimistic": (sum(upper) / len(upper) - baseline) / baseline,
        }

    spread = (
        f" The interval spans {scenarios['pessimistic']:+.1%} to "
        f"{scenarios['optimistic']:+.1%}."
        if scenarios else ""
    )
    signals.append(Signal(
        source="forecast",
        kind="demand_direction",
        subject=subject,
        direction=1 if change > 0.02 else -1 if change < -0.02 else 0,
        magnitude=change,
        summary=(
            f"Forecast revenue over the next {horizon} periods averages "
            f"{change:+.1%} against {basis}.{spread}"
        ),
        evidence={
            "horizon": horizon,
            "mean_forecast": mean_point,
            "baseline": baseline,
            "model": intervals.get("model"),
            "interval_level": intervals.get("level"),
            "scenarios": scenarios or None,
        },
        reliability=reliability,
    ))

    coverage = intervals.get("coverage") or {}
    nominal, observed = coverage.get("nominal"), coverage.get("observed")
    if nominal is not None and observed is not None and float(observed) < float(nominal):
        signals.append(Signal(
            source="forecast",
            kind="interval_understates_risk",
            subject=subject,
            direction=-1,
            magnitude=float(nominal) - float(observed),
            summary=(
                f"Prediction intervals covered {float(observed):.0%} of hold-out "
                f"observations against a nominal {float(nominal):.0%}, so the "
                f"stated range understates how wrong the forecast can be."
            ),
            evidence=coverage,
            reliability=reliability,
        ))
    return signals


# ---------------------------------------------------------------------------
# segmentation
# ---------------------------------------------------------------------------

def from_segmentation(run: dict[str, Any], reliability: Reliability) -> list[Signal]:
    """Revenue concentration by segment, and material movement between segments."""
    signals: list[Signal] = []
    profiles = run.get("profiles") or {}
    rows = profiles.get("rows") or []

    for row in rows:
        share = row.get("revenue_share")
        customers = row.get("customer_share")
        if share is None or customers is None:
            continue
        subject = Subject(
            Scope.SEGMENT, str(row.get("cluster")), str(row.get("name") or row.get("cluster"))
        )
        # Concentration is revenue share relative to customer share. A segment
        # holding more revenue than its size implies is where attention pays.
        ratio = (float(share) / float(customers)) if customers else 0.0
        signals.append(Signal(
            source="segmentation",
            kind="revenue_concentration",
            subject=subject,
            direction=1 if ratio > 1.0 else -1,
            magnitude=ratio,
            summary=(
                f"{row.get('name')} holds {float(share):.1%} of revenue from "
                f"{float(customers):.1%} of customers."
            ),
            evidence={
                "customers": row.get("customers"),
                "customer_share": customers,
                "revenue_share": share,
                "median_recency_days": row.get("median_recency_days"),
                "median_frequency": row.get("median_frequency"),
                "median_monetary": row.get("median_monetary"),
                "concentration_ratio": ratio,
            },
            reliability=reliability,
        ))

    names = {str(row.get("cluster")): str(row.get("name")) for row in rows}
    for window, migration in (run.get("migrations") or {}).items():
        if not isinstance(migration, dict) or not migration.get("available"):
            continue
        for flow in migration.get("largest_flows", []):
            share = float(flow.get("share_of_source", 0.0))
            if share < MATERIAL_FLOW:
                continue
            source_id = str(flow.get("from"))
            signals.append(Signal(
                source="segmentation",
                kind="segment_outflow",
                subject=Subject(Scope.SEGMENT, source_id, names.get(source_id, source_id)),
                direction=-1,
                magnitude=share,
                summary=(
                    f"{share:.0%} of {names.get(source_id, 'cluster ' + source_id)} "
                    f"moved to {names.get(str(flow.get('to')), 'cluster ' + str(flow.get('to')))} "
                    f"between {window}."
                ),
                evidence={"window": window, **flow},
                reliability=reliability,
            ))
    return signals


# ---------------------------------------------------------------------------
# association
# ---------------------------------------------------------------------------

def from_association(
    run: dict[str, Any], reliability: Reliability, *, limit: int = 25
) -> list[Signal]:
    """Durable product pairings, and the share of catalogue no rule can reach."""
    signals: list[Signal] = []

    survived = {
        (tuple(row["antecedent"]), tuple(row["consequent"]))
        for row in ((run.get("holdout_validation") or {}).get("strongest_survivors") or [])
    }

    ranked = sorted(
        (r for r in (run.get("rules") or [])
         if r.get("is_association") and (r.get("normalised_lift") or 0) >= MIN_NORMALISED_LIFT),
        key=lambda r: -(r.get("normalised_lift") or 0),
    )[:limit]

    for rule in ranked:
        antecedent = rule.get("antecedent") or []
        consequent = rule.get("consequent") or []
        if not antecedent or not consequent:
            continue
        key = " + ".join(antecedent) + " -> " + " + ".join(consequent)
        held = (
            tuple(rule.get("antecedent_ids", [])),
            tuple(rule.get("consequent_ids", [])),
        ) in survived
        signals.append(Signal(
            source="association",
            kind="durable_pairing" if held else "pairing",
            subject=Subject(Scope.PRODUCT, key, key),
            direction=1,
            magnitude=float(rule.get("normalised_lift") or 0.0),
            summary=(
                f"{' + '.join(antecedent)} is bought with {' + '.join(consequent)} in "
                f"{float(rule.get('confidence', 0)):.0%} of baskets containing it, "
                f"across {int(rule.get('support_count', 0)):,} baskets."
            ),
            evidence={
                "antecedent": antecedent,
                "consequent": consequent,
                "support_count": rule.get("support_count"),
                "confidence": rule.get("confidence"),
                "lift": rule.get("lift"),
                "normalised_lift": rule.get("normalised_lift"),
                "q_value": rule.get("q_value"),
                "held_on_holdout": held,
            },
            reliability=reliability,
        ))

    hazards = run.get("recommender_hazards") or {}
    coverage = hazards.get("item_coverage") or {}
    if coverage.get("available"):
        reachable = float(coverage["item_coverage"])
        signals.append(Signal(
            source="association",
            kind="catalogue_blind_spot",
            subject=Subject(Scope.BUSINESS, "__CATALOGUE__", "Product catalogue"),
            direction=-1,
            magnitude=1.0 - reachable,
            summary=(
                f"No rule can reach {1 - reachable:.1%} of the catalogue "
                f"({coverage['catalogue_size'] - coverage['reachable']:,} of "
                f"{coverage['catalogue_size']:,} products), because they never "
                f"meet the minimum support threshold."
            ),
            evidence=coverage,
            reliability=reliability,
        ))

    new_items = hazards.get("new_item_coverage") or {}
    if new_items.get("available"):
        signals.append(Signal(
            source="association",
            kind="new_product_blind_spot",
            subject=Subject(Scope.BUSINESS, "__NEW_PRODUCTS__", "Newly listed products"),
            direction=-1,
            magnitude=1.0 - float(new_items["coverage_new"]),
            summary=(
                f"{float(new_items['coverage_new']):.1%} of the "
                f"{new_items['new_items']:,} products introduced during the hold-out "
                f"window can be recommended, since a rule can only name products "
                f"that existed when it was mined."
            ),
            evidence=new_items,
            reliability=reliability,
        ))
    return signals


def collect(
    *,
    forecast: dict[str, Any] | None,
    segmentation: dict[str, Any] | None,
    association: dict[str, Any] | None,
    reliabilities: dict[str, Reliability],
    rule_limit: int = 25,
) -> list[Signal]:
    """Every signal the three runs support, in one list."""
    signals: list[Signal] = []
    if forecast:
        signals += from_forecast(forecast, reliabilities["forecast"])
    if segmentation:
        signals += from_segmentation(segmentation, reliabilities["segmentation"])
    if association:
        signals += from_association(
            association, reliabilities["association"], limit=rule_limit
        )
    return signals


def scopes_present(signals: list[Signal]) -> dict[str, list[str]]:
    """Which engine spoke at which scope. Used to report who was silent."""
    seen: dict[str, set[str]] = {}
    for signal in signals:
        seen.setdefault(signal.source, set()).add(signal.subject.scope.value)
    return {source: sorted(values) for source, values in seen.items()}
