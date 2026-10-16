"""Do the segments survive the window moving? This is RQ2.

A segmentation that reshuffles every quarter is not a description of the
business; it is a description of the quarter. Two measures, deliberately of
different kinds:

**Adjusted Rand Index** - do the two partitions group the same customers
together, ignoring the labels? 1.0 is identical, 0.0 is what random relabelling
would give, and it can go slightly negative. It is label-free, which matters
because cluster 0 in one run has nothing to do with cluster 0 in the next.

**Retention share** - after matching the clusters between windows, what share
of customers stayed put? Less rigorous than ARI, but it needs no citation and
any reader can interpret it, which makes it the right number to lead with.

**On the Adjusted Rand Index's provenance, plainly.** A review of the
seventeen supplied papers found "Adjusted Rand" absent from that set's
segmentation literature entirely. It is used here because it is the standard
label-free way to compare two partitions of the same objects and the
alternative - judging whether segments "look similar" - is not a measure. Treat
it as a measurement choice of your own, justified by that argument, or find and
read a reference before citing one. The retention share is reported alongside
precisely so the finding does not rest on the unsupported measure.

**Matching clusters between windows.** Labels are arbitrary, so before a
migration can be counted the clusters have to be paired up. They are matched by
overlap: the pairing that puts the most customers on the diagonal, found by the
Hungarian algorithm on the contingency table. Without that step a migration
matrix is just a picture of the labelling order.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Conventional readings of ARI. These are descriptive bands, not thresholds
# with a test behind them, and the wording says so.
STRONG_AGREEMENT = 0.75
MODERATE_AGREEMENT = 0.40


def _aligned_labels(
    first: dict[str, int], second: dict[str, int]
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Customers in both partitions, with their labels from each."""
    shared = sorted(set(first) & set(second))
    return (
        shared,
        np.array([first[c] for c in shared], dtype="int64"),
        np.array([second[c] for c in shared], dtype="int64"),
    )


def match_clusters(labels_a: np.ndarray, labels_b: np.ndarray) -> dict[int, int]:
    """Pair clusters between two partitions by maximum overlap.

    Returns a map from the second partition's labels to the first's. Uses the
    Hungarian algorithm on the negated contingency table, which finds the
    pairing maximising the number of customers on the diagonal - the
    assignment problem, solved exactly rather than greedily.
    """
    from scipy.optimize import linear_sum_assignment

    a_labels = sorted(set(labels_a.tolist()))
    b_labels = sorted(set(labels_b.tolist()))

    table = np.zeros((len(b_labels), len(a_labels)), dtype="int64")
    for row, b in enumerate(b_labels):
        for column, a in enumerate(a_labels):
            table[row, column] = int(((labels_b == b) & (labels_a == a)).sum())

    rows, columns = linear_sum_assignment(-table)
    return {int(b_labels[r]): int(a_labels[c]) for r, c in zip(rows, columns, strict=True)}


def migration_matrix(
    first: dict[str, int], second: dict[str, int], *, match: bool = True
) -> dict[str, Any]:
    """Where customers went between two windows.

    Rows are the earlier window's clusters, columns the later one's. With
    `match=True` the later labels are renamed to their best-matching earlier
    cluster first, so the diagonal means "stayed" rather than "happened to get
    the same number".
    """
    shared, labels_a, labels_b = _aligned_labels(first, second)
    if not shared:
        return {
            "available": False,
            "reason": "No customers appear in both windows, so nothing can have moved.",
        }

    mapping: dict[int, int] = {}
    if match:
        mapping = match_clusters(labels_a, labels_b)
        labels_b = np.array([mapping.get(int(v), int(v)) for v in labels_b], dtype="int64")

    clusters = sorted(set(labels_a.tolist()) | set(labels_b.tolist()))
    table = pd.DataFrame(0, index=clusters, columns=clusters, dtype="int64")
    for a, b in zip(labels_a, labels_b, strict=True):
        table.loc[int(a), int(b)] += 1

    stayed = int(np.trace(table.to_numpy()))
    total = int(len(shared))

    # Where did each cluster's members end up? The largest off-diagonal flow is
    # usually the interesting one - "at risk" draining into "lapsed" is a
    # business event, not noise.
    flows = []
    for source in clusters:
        for destination in clusters:
            if source == destination:
                continue
            count = int(table.loc[source, destination])
            if count:
                flows.append({
                    "from": int(source), "to": int(destination), "customers": count,
                    "share_of_source": float(count / max(1, int(table.loc[source].sum()))),
                })
    flows.sort(key=lambda row: row["customers"], reverse=True)

    return {
        "available": True,
        "customers_compared": total,
        "matrix": table.to_dict(),
        "stayed": stayed,
        "retention_share": float(stayed / total) if total else None,
        "clusters_matched": match,
        "label_mapping": mapping,
        "largest_flows": flows[:5],
        "note": (
            "Rows are the earlier window's clusters, columns the later one's. "
            "Cluster labels are arbitrary, so the later window's labels were "
            "matched to the earlier window's by maximum overlap before "
            "counting; without that step the diagonal would be meaningless."
            if match else
            "Labels were NOT matched. The diagonal counts customers whose "
            "cluster number happened to be identical, which is not the same as "
            "staying in the same group."
        ),
    }


def stability_across_windows(
    partitions: dict[str, dict[str, int]],
    *,
    consecutive_only: bool = False,
) -> dict[str, Any]:
    """ARI and retention between windows. The RQ2 answer.

    `partitions` maps a window label to {customer: cluster}. Compares every
    pair by default, because the gap between window 1 and window 4 is a
    different question from window 3 to window 4 - slow drift and sudden
    reshuffles look the same if only neighbours are compared.
    """
    from sklearn.metrics import adjusted_rand_score

    labels = sorted(partitions)
    if len(labels) < 2:
        return {
            "available": False,
            "reason": f"Stability needs at least two windows; got {len(labels)}.",
        }

    pairs = []
    for index, earlier in enumerate(labels):
        for later in labels[index + 1:]:
            if consecutive_only and labels.index(later) != index + 1:
                continue
            shared, a, b = _aligned_labels(partitions[earlier], partitions[later])
            if len(shared) < 2:
                pairs.append({
                    "from": earlier, "to": later, "customers_compared": len(shared),
                    "adjusted_rand": None,
                    "note": "Too few customers in both windows to compare.",
                })
                continue

            migration = migration_matrix(partitions[earlier], partitions[later])
            pairs.append({
                "from": earlier,
                "to": later,
                "consecutive": labels.index(later) == index + 1,
                "customers_compared": len(shared),
                "adjusted_rand": float(adjusted_rand_score(a, b)),
                "retention_share": migration.get("retention_share"),
            })

    scored = [p for p in pairs if p.get("adjusted_rand") is not None]
    if not scored:
        return {"available": False, "reason": "No comparable window pairs.", "pairs": pairs}

    neighbours = [p for p in scored if p.get("consecutive")]
    mean_ari = float(np.mean([p["adjusted_rand"] for p in scored]))
    mean_neighbour = (
        float(np.mean([p["adjusted_rand"] for p in neighbours])) if neighbours else None
    )
    mean_retention = float(np.mean([
        p["retention_share"] for p in scored if p.get("retention_share") is not None
    ]))

    return {
        "available": True,
        "windows": labels,
        "pairs": pairs,
        "mean_adjusted_rand": mean_ari,
        "mean_consecutive_adjusted_rand": mean_neighbour,
        "mean_retention_share": mean_retention,
        "verdict": _verdict(mean_ari, mean_retention),
        "measure_note": (
            "The Adjusted Rand Index does not appear in the supplied "
            "segmentation literature; it is used here as a label-free way to "
            "compare two partitions of the same customers. The retention share "
            "is reported alongside because it needs no reference and any reader "
            "can interpret it."
        ),
        "caveat": (
            f"Computed on the customers present in both windows "
            f"({min(p['customers_compared'] for p in scored)} at the thinnest "
            f"pair). Customers who joined later cannot have moved, and counting "
            f"them would make stability look worse the faster the business grows."
        ),
    }


def _verdict(ari: float, retention: float) -> str:
    """The sentence to write, matched to what the numbers support."""
    if ari >= STRONG_AGREEMENT:
        return (
            f"Segments are stable (mean ARI {ari:.3f}, {retention:.1%} of customers "
            f"stayed in the same group). The partition describes the customer "
            f"base rather than the window it was fitted to."
        )
    if ari >= MODERATE_AGREEMENT:
        return (
            f"Segments are moderately stable (mean ARI {ari:.3f}, {retention:.1%} "
            f"retention). Membership shifts at the boundaries while the broad "
            f"structure holds - expected for RFM, where customers sit on a "
            f"continuum and small changes in recency move borderline cases."
        )
    return (
        f"Segments are unstable (mean ARI {ari:.3f}, {retention:.1%} retention). "
        f"The grouping changes substantially as the window moves, so it should "
        f"not be presented as a description of the customer base, and any "
        f"campaign built on it would be targeting a different population each "
        f"time it ran. This is a finding, not a failure - report it."
    )
