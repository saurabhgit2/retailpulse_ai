"""What each cluster actually is, in the original units.

A clustering returns integers. Nobody can act on an integer. This module turns
each cluster back into the numbers a category manager recognises - median days
since last purchase, median orders, median spend, share of revenue - and gives
it a descriptive name derived from where its centroid sits.

**The names are derived, not assigned.** `analytics/rfm.py` carries a set of
conventional RFM labels (champions, at risk, hibernating) and explicitly marks
them as "not a clustering result" - they come from score bands, not from any
algorithm. The names here are different: each is computed from the cluster's
own position relative to the others on the three axes. A cluster is "high
value" because its median spend is in the top third of the clusters found, not
because someone decided what a champion looks like.

That distinction matters in the report. If both naming schemes appear and look
similar, that similarity is a *result* - the conventional bands happened to
recover what clustering found - and it should be shown rather than assumed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Axis descriptions. Thirds rather than quantiles of the customer population,
# because what matters is where a cluster sits relative to the other clusters.
HIGH = 2 / 3
LOW = 1 / 3


def describe_clusters(
    customers: pd.DataFrame,
    labels: np.ndarray,
    *,
    customer_column: str = "customer",
    revenue_column: str = "monetary",
) -> dict[str, Any]:
    """One row per cluster, in original units, with a derived name.

    `customers` is the RFM table in its *untransformed* form - the profile has
    to be in days, counts and currency, not in scaled log space, or it cannot
    be read.
    """
    if customers.empty:
        return {"available": False, "reason": "No customers to profile."}
    if len(labels) != len(customers):
        raise ValueError(
            f"{len(labels)} labels for {len(customers)} customers. The matrix "
            f"builder drops unusable rows, so profile against the same frame it "
            f"returned customers for, not the original."
        )

    frame = customers.copy()
    frame["cluster"] = labels.astype("int64")

    total_revenue = float(frame[revenue_column].sum())
    total_customers = int(len(frame))

    rows = []
    for cluster_id, group in frame.groupby("cluster", observed=True):
        revenue = float(group[revenue_column].sum())
        rows.append({
            "cluster": int(cluster_id),
            "customers": int(len(group)),
            "customer_share": float(len(group) / total_customers),
            "median_recency_days": float(group["recency_days"].median()),
            "median_frequency": float(group["frequency"].median()),
            "median_monetary": float(group[revenue_column].median()),
            "mean_monetary": float(group[revenue_column].mean()),
            "total_monetary": revenue,
            "revenue_share": float(revenue / total_revenue) if total_revenue else None,
        })

    rows = _name_clusters(rows)
    rows.sort(key=lambda row: row["total_monetary"], reverse=True)

    concentration = _concentration(rows)
    return {
        "available": True,
        "clusters": len(rows),
        "customers": total_customers,
        "rows": rows,
        "revenue_concentration": concentration,
        "naming_note": (
            "Names are derived from each cluster's position relative to the "
            "others on the three axes, not from conventional RFM bands. If they "
            "resemble the band labels in the RFM report, that resemblance is a "
            "result worth showing, not an assumption."
        ),
    }


def _name_clusters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A descriptive name per cluster from its rank on each axis."""
    if len(rows) == 1:
        rows[0]["name"] = "all customers"
        rows[0]["description"] = "A single cluster: no segmentation was produced."
        return rows

    def _position(values: list[float], value: float, lower_is_better: bool) -> str:
        ranked = sorted(values)
        # Where does this cluster sit among the clusters, not among customers?
        index = ranked.index(value)
        share = index / (len(ranked) - 1) if len(ranked) > 1 else 0.5
        if lower_is_better:
            share = 1 - share
        return "high" if share >= HIGH else "low" if share <= LOW else "mid"

    recency = [row["median_recency_days"] for row in rows]
    frequency = [row["median_frequency"] for row in rows]
    monetary = [row["median_monetary"] for row in rows]

    for row in rows:
        r = _position(recency, row["median_recency_days"], lower_is_better=True)
        f = _position(frequency, row["median_frequency"], lower_is_better=False)
        m = _position(monetary, row["median_monetary"], lower_is_better=False)
        row["axes"] = {"recency": r, "frequency": f, "monetary": m}
        row["name"] = _name_from_axes(r, f, m)

    # Two clusters can land in the same band on every axis - with k = 4 the
    # ranked positions are 0, 1/3, 2/3 and 1, so two are "high" and two are
    # "low" on each. Identical names for different segments are unusable in a
    # report, so collisions are broken by spend, which is the axis a reader
    # cares most about.
    _disambiguate(rows)

    # The description is written after disambiguation so it accompanies the
    # final name rather than an intermediate one.
    for row in rows:
        row["description"] = (
            f"Median {row['median_recency_days']:.0f} days since last purchase, "
            f"{row['median_frequency']:.0f} orders, "
            f"{row['median_monetary']:,.0f} net spend. "
            f"{row['customers']:,} customers "
            f"({row['customer_share']:.1%}) holding "
            f"{row['revenue_share']:.1%} of revenue."
            if row.get("revenue_share") is not None else ""
        )
    return rows


def _disambiguate(rows: list[dict[str, Any]]) -> None:
    """Make every cluster name unique, in place.

    Clusters sharing a name are ranked by median spend and qualified
    "(highest spend)", "(second highest spend)" and so on. The qualifier names
    the dimension used, so a reader is never left guessing what separates two
    similarly-named groups.
    """
    from collections import defaultdict

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["name"]].append(row)

    ordinals = ["highest", "second highest", "third highest", "fourth highest",
                "fifth highest", "sixth highest"]

    for name, members in grouped.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda row: row["median_monetary"], reverse=True)
        for position, row in enumerate(members):
            qualifier = (
                ordinals[position] if position < len(ordinals) else f"rank {position + 1}"
            )
            row["name"] = f"{name} ({qualifier} spend)"


def _name_from_axes(recency: str, frequency: str, monetary: str) -> str:
    """Short descriptive phrase. Deliberately plain rather than marketing jargon."""
    value = "high" if monetary == "high" else "low" if monetary == "low" else "mid"

    if recency == "high" and frequency == "high" and value == "high":
        return "recent, frequent, high value"
    if recency == "low" and value == "high":
        return "lapsed high value"
    if recency == "low" and frequency == "low":
        return "lapsed occasional"
    if recency == "high" and frequency == "low":
        return "recent, few purchases"
    if value == "high":
        return "high value"
    if value == "low":
        return "low value"
    return f"{recency} recency, {frequency} frequency, {value} value"


def _concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How much revenue sits in the smallest clusters.

    The number a manager asks for first: if 8% of customers carry 60% of
    revenue, that is the segmentation earning its keep, whatever the silhouette
    score says.
    """
    ranked = sorted(rows, key=lambda row: row["total_monetary"], reverse=True)
    top = ranked[0]
    return {
        "top_cluster": top["cluster"],
        "top_cluster_name": top.get("name"),
        "top_cluster_customer_share": top["customer_share"],
        "top_cluster_revenue_share": top["revenue_share"],
        "summary": (
            f"The largest cluster by revenue holds {top['customer_share']:.1%} of "
            f"customers and {top['revenue_share']:.1%} of revenue."
            if top.get("revenue_share") is not None else None
        ),
    }


def compare_with_rfm_bands(
    cluster_labels: dict[str, int], band_labels: dict[str, str]
) -> dict[str, Any]:
    """Do the clusters recover the conventional RFM bands?

    `analytics/rfm.py` assigns conventional labels from score bands and marks
    them explicitly as not a clustering result. This checks whether an
    algorithm that never saw those bands arrives at a similar grouping. High
    agreement means the cheap, explainable band rule is a reasonable stand-in
    for clustering; low agreement means the bands are hiding structure.

    Either answer is useful, and it is the same move as the §12.7 comparison:
    test the convenient method against the rigorous one rather than assuming.
    """
    from sklearn.metrics import adjusted_rand_score

    shared = sorted(set(cluster_labels) & set(band_labels))
    if len(shared) < 3:
        return {
            "available": False,
            "reason": f"Only {len(shared)} customers appear in both; need at least 3.",
        }

    bands = sorted({band_labels[c] for c in shared})
    band_index = {name: position for position, name in enumerate(bands)}

    clusters = np.array([cluster_labels[c] for c in shared])
    conventional = np.array([band_index[band_labels[c]] for c in shared])
    score = float(adjusted_rand_score(clusters, conventional))

    cross = pd.crosstab(
        pd.Series(clusters, name="cluster"),
        pd.Series([band_labels[c] for c in shared], name="rfm_band"),
    )

    return {
        "available": True,
        "customers_compared": len(shared),
        "adjusted_rand": score,
        "crosstab": cross.to_dict(),
        "verdict": (
            f"The clusters and the conventional RFM bands agree closely "
            f"(ARI {score:.3f}): the explainable band rule is a reasonable "
            f"stand-in for clustering on this data."
            if score >= 0.5 else
            f"The clusters and the conventional RFM bands agree only partly "
            f"(ARI {score:.3f}): clustering finds structure the score bands do "
            f"not capture, which is an argument for reporting both."
            if score >= 0.2 else
            f"The clusters and the conventional RFM bands disagree "
            f"(ARI {score:.3f}). The band labels should not be presented as if "
            f"they described the same groups the clustering found."
        ),
    }
