"""RFM: Recency, Frequency, Monetary.

Grounded in the paper behind this dataset. Chen, Sain and Guo (2012), "Data
mining for the online retail industry: A case study of RFM model-based customer
segmentation using data mining", *Journal of Database Marketing & Customer
Strategy Management* 19(3), 197-208, aggregate three variables per customer and
then cluster them with k-means. Their preprocessing is the same shape as ours:
select the transaction variables, derive `Amount = Quantity x Price`, separate
date from time, drop records with no customer identifier, then aggregate.

Two differences worth stating in the report, because they change what is
comparable:

* their dataset had a **PostCode** per delivery and they identified customers by
  it; the public Online Retail II release has `Customer ID` instead, so a
  "customer" here is an account, not an address;
* they restricted the analysis to **UK customers in 2011**. The filter set
  reproduces that without code changes, so the comparison can be made directly.

This module computes and describes R, F and M. It deliberately stops short of
clustering: the k-means segmentation and its stability analysis are RQ2, in
Phase 5b. What it does provide is the evidence that work will need - the
distributions, their skew, and the warning Chen et al. raise explicitly, that
k-means is sensitive to outliers and to variables on incomparable scales.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.kpis import concentration, gini

# Quintiles are the usual choice and give an interpretable 1-5 score per
# dimension. Fewer bins lose resolution; more produce bins too thin to act on.
DEFAULT_SCORE_BINS = 5

# A conventional reading of the score triples. These names are industry
# shorthand, NOT a finding from the cited papers, and they are a descriptive
# convenience only - the clustering in Phase 5b decides the real segments.
SEGMENT_RULES: tuple[tuple[str, str], ...] = (
    ("champions", "Bought recently, buy often, and spend the most."),
    ("loyal", "Buy regularly and spend above average."),
    ("potential_loyalist", "Recent buyers with moderate frequency or spend."),
    ("new", "Bought very recently but have not bought often."),
    ("at_risk", "Used to buy often and spend well, but not recently."),
    ("hibernating", "Low recency, frequency and spend."),
)


def _score(values: pd.Series, bins: int, ascending: bool) -> pd.Series:
    """Quintile score from 1 to `bins`.

    `ascending=False` is used for recency, where a *smaller* number of days is
    better, so the best customers get the highest score on every dimension and
    the three are comparable.

    Ties are the awkward case: a dataset where most customers bought exactly
    once has no five distinct frequency quintiles. `qcut` would raise, so the
    ranking is done first and duplicate edges dropped, which yields fewer than
    `bins` levels rather than an error - and that compression is itself worth
    seeing.
    """
    ranked = values.rank(method="first", ascending=ascending)
    try:
        scored = pd.qcut(ranked, q=bins, labels=False, duplicates="drop")
    except ValueError:
        return pd.Series(1, index=values.index, dtype="int64")
    return (scored.astype("float64").fillna(0) + 1).astype("int64")


def _segment(recency: int, frequency: int, monetary: int, top: int) -> str:
    """A conventional label from the three scores. Descriptive only."""
    high = top - 1          # 4 and 5 on a 1-5 scale
    low = 2                 # 1 and 2
    value = max(frequency, monetary)

    if recency >= high and value >= high:
        return "champions"
    if value >= high and recency >= low:
        return "loyal"
    if recency >= high and frequency <= low:
        return "new"
    if recency >= high:
        return "potential_loyalist"
    if value >= high:
        return "at_risk"
    return "hibernating"


def build_rfm(
    customers: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
    bins: int = DEFAULT_SCORE_BINS,
) -> dict[str, object]:
    """Describe the RFM distribution of a set of customers.

    `customers` is what SQL aggregated: one row per customer with
    `last_purchase`, `first_purchase`, `frequency` (distinct invoices),
    `monetary_gross`, `returns_value` and `lines`.
    """
    if customers.empty:
        return {"available": False, "reason": "No identified customers in range."}

    frame = customers.copy()
    frame["last_purchase"] = pd.to_datetime(frame["last_purchase"])
    frame["first_purchase"] = pd.to_datetime(frame["first_purchase"])

    # Recency is measured from the end of the data, not from today: the dataset
    # is historical, and "days since last purchase" relative to the present
    # would grow every time the report is run.
    reference = pd.Timestamp(as_of) if as_of is not None else frame["last_purchase"].max()

    frame["recency_days"] = (reference - frame["last_purchase"]).dt.days.clip(lower=0)
    frame["tenure_days"] = (reference - frame["first_purchase"]).dt.days.clip(lower=0)
    frame["frequency"] = pd.to_numeric(frame["frequency"], errors="coerce").fillna(0).astype("int64")
    frame["monetary_gross"] = pd.to_numeric(
        frame["monetary_gross"], errors="coerce"
    ).fillna(0.0).astype("float64")
    frame["returns_value"] = pd.to_numeric(
        frame.get("returns_value", 0), errors="coerce"
    ).fillna(0.0).astype("float64")
    # Net, because a customer who returns most of what they buy is not a top
    # customer however large their gross spend.
    frame["monetary"] = frame["monetary_gross"] - frame["returns_value"]
    frame["average_order_value"] = np.where(
        frame["frequency"] > 0, frame["monetary_gross"] / frame["frequency"], np.nan
    )

    frame["r_score"] = _score(frame["recency_days"], bins, ascending=False)
    frame["f_score"] = _score(frame["frequency"], bins, ascending=True)
    frame["m_score"] = _score(frame["monetary"], bins, ascending=True)
    top = int(max(frame[["r_score", "f_score", "m_score"]].to_numpy().max(), 1))
    frame["rfm_cell"] = (
        frame["r_score"].astype(str) + frame["f_score"].astype(str) + frame["m_score"].astype(str)
    )
    frame["segment"] = [
        _segment(int(r), int(f), int(m), top)
        for r, f, m in zip(frame["r_score"], frame["f_score"], frame["m_score"], strict=True)
    ]

    segments = []
    total_monetary = float(frame["monetary"].sum())
    for name, description in SEGMENT_RULES:
        group = frame[frame["segment"] == name]
        if group.empty:
            continue
        segments.append({
            "segment": name,
            "description": description,
            "customers": int(len(group)),
            "customer_share": float(len(group) / len(frame)),
            "monetary": float(group["monetary"].sum()),
            "monetary_share": (
                float(group["monetary"].sum() / total_monetary) if total_monetary else None
            ),
            "median_recency_days": float(group["recency_days"].median()),
            "median_frequency": float(group["frequency"].median()),
            "median_monetary": float(group["monetary"].median()),
        })
    segments.sort(key=lambda row: row["monetary"], reverse=True)

    def _describe(column: str) -> dict[str, float | None]:
        values = frame[column].astype("float64")
        mean = float(values.mean())
        skewness = float(values.skew()) if len(values) > 2 else 0.0
        return {
            "min": float(values.min()),
            "median": float(values.median()),
            "mean": mean,
            "max": float(values.max()),
            "std_dev": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            "skewness": skewness,
            "p90": float(values.quantile(0.9)),
            "p99": float(values.quantile(0.99)),
        }

    distributions = {
        "recency_days": _describe("recency_days"),
        "frequency": _describe("frequency"),
        "monetary": _describe("monetary"),
    }

    # Chen et al. note that k-means is very sensitive to outliers and to
    # variables on incomparable scales - exactly the condition retail monetary
    # values are in. Saying so here means Phase 5b inherits the warning rather
    # than rediscovering it.
    monetary_skew = distributions["monetary"]["skewness"]
    clustering_notes = [
        "k-means is sensitive to outliers and to variables measured on different "
        "scales (Chen, Sain & Guo 2012). Recency is in days, frequency is a count "
        "and monetary is money, so they must be standardised before clustering.",
    ]
    if abs(monetary_skew) > 1:
        clustering_notes.append(
            f"Monetary value is strongly right-skewed (skewness {monetary_skew:.1f}): "
            f"a log transform before standardising is worth testing, and the result "
            f"of both choices should be reported."
        )
    if frame["frequency"].median() <= 1:
        clustering_notes.append(
            "At least half of these customers bought only once, so the frequency "
            "quintiles collapse and segments built on them will be thin."
        )

    return {
        "available": True,
        "customers": int(len(frame)),
        "as_of": reference.date().isoformat(),
        "score_bins": top,
        "recency_unit": "days",
        "frequency_definition": "distinct invoices",
        "monetary_definition": "sum of revenue on non-return lines, less returns",
        "distributions": distributions,
        "segments": segments,
        "concentration": concentration(frame.set_index(frame.columns[0])["monetary"]),
        "monetary_gini": gini(frame["monetary"]),
        "clustering_notes": clustering_notes,
        "caveats": [
            "Guest sales have no customer identifier and are excluded from RFM "
            "entirely; the share of revenue they represent is reported alongside.",
            "Segment labels here are conventional shorthand applied to score "
            "bands, not a clustering result. The k-means segmentation and its "
            "stability analysis are RQ2.",
            "Recency is measured from the end of the data, not from today.",
        ],
        "table": frame.drop(columns=["first_purchase", "last_purchase"]).to_dict(orient="records"),
    }
