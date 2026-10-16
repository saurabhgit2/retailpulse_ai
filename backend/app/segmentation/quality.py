"""How many clusters, and are they any good?

Five measures, reported together and never reduced to one recommendation,
because they routinely disagree and the disagreement is informative. A k that
every index likes is a real structure; a k that only silhouette likes is a
defensible choice that needs saying out loud.

| measure              | direction | what it rewards |
|----------------------|-----------|-----------------|
| Silhouette           | higher    | points closer to their own cluster than the next one |
| Davies-Bouldin       | lower     | compact clusters whose centres are far apart |
| Calinski-Harabasz    | higher    | between-cluster variance relative to within |
| Elbow (inertia)      | knee      | the k after which extra clusters stop paying |
| Gap statistic        | higher    | structure beyond what uniform random data of the same shape would give |

The gap statistic is the only one that answers "is there any clustering here at
all". The others compare partitions; run them on pure noise and they still
name a best k. That is why it is included despite costing a reference set of
simulations per k - on retail RFM, which is one continuous blob with a long
tail rather than separated groups, the honest answer may well be that the gap
statistic never peaks. If so, report it: "the segments are a useful summary of
a continuum, not discovered groups" is a defensible finding and is how most
RFM segmentation actually works.

**These indices were selected because a review of the seventeen supplied
papers found them to be the ones in use in that set's segmentation
literature.** That review is recorded in the project's backend guide; it was
done with the papers to hand, and should be re-verified against your own copies
before any of it is cited.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Silhouette is O(n^2) in memory. Above this many customers it is computed on a
# sample, and the sample size is reported alongside the number.
SILHOUETTE_SAMPLE_LIMIT = 10_000

# Reference datasets per k for the gap statistic. Ten is the usual choice: it
# is enough for the standard error to be meaningful without the simulation
# costing more than the clustering.
GAP_REFERENCES = 10


def quality_indices(
    matrix: np.ndarray, labels: np.ndarray, *, seed: int = 20260101
) -> dict[str, Any]:
    """Silhouette, Davies-Bouldin and Calinski-Harabasz for one partition."""
    from sklearn.metrics import (
        calinski_harabasz_score,
        davies_bouldin_score,
        silhouette_score,
    )

    distinct = len(np.unique(labels))
    if distinct < 2:
        return {
            "available": False,
            "reason": (
                f"All points fell into {distinct} cluster(s); these indices are "
                f"undefined without at least two."
            ),
        }

    sampled = matrix.shape[0] > SILHOUETTE_SAMPLE_LIMIT
    silhouette = float(silhouette_score(
        matrix, labels,
        sample_size=SILHOUETTE_SAMPLE_LIMIT if sampled else None,
        random_state=seed,
    ))

    return {
        "available": True,
        "clusters": int(distinct),
        "silhouette": silhouette,
        "silhouette_sampled": sampled,
        "silhouette_sample_size": SILHOUETTE_SAMPLE_LIMIT if sampled else int(matrix.shape[0]),
        "davies_bouldin": float(davies_bouldin_score(matrix, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(matrix, labels)),
        "directions": {
            "silhouette": "higher is better, range -1 to 1",
            "davies_bouldin": "lower is better, 0 is perfect",
            "calinski_harabasz": "higher is better, unbounded",
        },
        "interpretation": _silhouette_reading(silhouette),
    }


def _silhouette_reading(value: float) -> str:
    """Plain words, deliberately cautious.

    The conventional bands are widely quoted but they are rules of thumb, not
    thresholds with a test behind them, so the wording says what the number
    means rather than passing or failing it.
    """
    if value >= 0.5:
        return (
            f"Silhouette {value:.3f}: the clusters are well separated - points sit "
            f"much closer to their own cluster than to the next one."
        )
    if value >= 0.25:
        return (
            f"Silhouette {value:.3f}: there is some structure, but the clusters "
            f"overlap. Reasonable for RFM, where customers form a continuum "
            f"rather than distinct groups."
        )
    return (
        f"Silhouette {value:.3f}: little separation. The partition is a way of "
        f"dividing a continuum rather than a discovery of groups, and should be "
        f"described that way."
    )


def elbow(inertias: dict[int, float]) -> dict[str, Any]:
    """Where the inertia curve stops falling usefully.

    The knee is found by the standard geometric construction: draw a line from
    the first point to the last, and take the k furthest from it. That is
    reproducible, unlike reading a chart by eye, but it is still only a
    heuristic - the curve for retail RFM is usually smooth, and a smooth curve
    has no real elbow. The returned `distinct` flag says whether the chosen
    point actually stands out.
    """
    if len(inertias) < 3:
        return {
            "available": False,
            "reason": f"The elbow needs at least 3 values of k; got {len(inertias)}.",
        }

    ks = sorted(inertias)
    values = np.array([inertias[k] for k in ks], dtype="float64")
    points = np.column_stack([np.array(ks, dtype="float64"), values])

    start, end = points[0], points[-1]
    line = end - start
    length = np.linalg.norm(line)
    if length == 0:
        return {"available": False, "reason": "The inertia curve is flat."}

    unit = line / length
    offsets = points - start
    projections = np.outer(offsets @ unit, unit)
    distances = np.linalg.norm(offsets - projections, axis=1)

    position = int(np.argmax(distances))
    best = ks[position]
    spread = float(distances.max() - distances.min())

    # Is the knee real, or an artefact?
    #
    # On an exactly straight curve every distance is zero in exact arithmetic,
    # but floating point leaves noise around 1e-15 - and noise has a maximum,
    # so a naive `max > 0` test finds an "elbow" in a perfectly linear curve.
    # The deviation is therefore judged relative to the range of the inertia
    # values: a bend that is a billionth of the curve's own scale is not a bend.
    scale = float(np.ptp(values))
    negligible = scale <= 0 or float(distances.max()) <= 1e-9 * scale
    distinct = bool(
        not negligible and distances[position] > 1.5 * float(np.median(distances))
    )

    return {
        "available": True,
        "k": best,
        "distances": {int(k): float(d) for k, d in zip(ks, distances, strict=True)},
        "distinct": distinct,
        "note": (
            f"The inertia curve bends most at k={best}."
            if distinct else
            f"The curve is smooth: k={best} is the furthest point from the "
            f"chord, but it does not stand out, so the elbow should not be "
            f"presented as evidence for that k."
        ),
        "spread": spread,
    }


def gap_statistic(
    matrix: np.ndarray,
    k_values: list[int],
    *,
    algorithm: str = "kmeans",
    references: int = GAP_REFERENCES,
    seed: int = 20260101,
) -> dict[str, Any]:
    """Compare the clustering against uniform random data of the same shape.

    For each k, the within-cluster dispersion of the real data is compared with
    the dispersion of reference datasets drawn uniformly over the bounding box
    of the real data. A large gap means the structure is more than what random
    points of the same spread would produce.

    This is the only measure here that can say "there is no clustering". If the
    gap keeps rising with k and never peaks, the data is a continuum - which is
    the usual outcome for RFM and is worth reporting as such rather than
    picking the largest k tested.
    """
    from app.segmentation.clustering import cluster

    if matrix.shape[0] < 10:
        return {"available": False, "reason": "Too few points for a reference comparison."}

    rng = np.random.default_rng(seed)
    low, high = matrix.min(axis=0), matrix.max(axis=0)

    rows = []
    for k in sorted(k_values):
        observed = _dispersion(matrix, cluster(matrix, k, algorithm, seed=seed).labels)

        reference_logs = []
        for draw in range(references):
            sample = rng.uniform(low, high, size=matrix.shape)
            labels = cluster(sample, k, algorithm, seed=seed + draw).labels
            reference_logs.append(np.log(_dispersion(sample, labels)))

        reference_logs = np.array(reference_logs)
        gap = float(reference_logs.mean() - np.log(observed))
        # The standard error is inflated by sqrt(1 + 1/B), the usual correction
        # for estimating the reference mean from B simulations.
        deviation = float(reference_logs.std(ddof=1) * np.sqrt(1 + 1 / references))
        rows.append({"k": int(k), "gap": gap, "std_error": deviation})

    # The conventional rule: the smallest k whose gap is at least the next k's
    # gap minus that k's standard error.
    chosen: int | None = None
    for index in range(len(rows) - 1):
        if rows[index]["gap"] >= rows[index + 1]["gap"] - rows[index + 1]["std_error"]:
            chosen = rows[index]["k"]
            break

    return {
        "available": True,
        "references": references,
        "rows": rows,
        "k": chosen,
        "note": (
            f"The gap statistic selects k={chosen}."
            if chosen is not None else
            "The gap never stops rising across the range tested, which means no "
            "k is supported over a larger one. On RFM this usually means the "
            "customers form a continuum rather than separable groups - report "
            "the segments as a useful partition of that continuum, not as "
            "discovered clusters."
        ),
    }


def _dispersion(matrix: np.ndarray, labels: np.ndarray) -> float:
    """Pooled within-cluster sum of squares, floored so the log is finite."""
    total = 0.0
    for label in np.unique(labels):
        points = matrix[labels == label]
        if len(points) < 2:
            continue
        centre = points.mean(axis=0)
        total += float(((points - centre) ** 2).sum())
    return max(total, 1e-12)


def compare_k(
    matrix: np.ndarray,
    results: dict[int, Any],
    *,
    seed: int = 20260101,
) -> dict[str, Any]:
    """Every index at every k, with the honest summary.

    `results` maps k to a `ClusterResult`. Returns a table plus which k each
    index prefers - and, deliberately, no single recommendation. If the indices
    disagree the choice is the researcher's and must be justified in the report;
    returning one number would hide that.
    """
    rows = []
    inertias: dict[int, float] = {}
    for k in sorted(results):
        result = results[k]
        indices = quality_indices(matrix, result.labels, seed=seed)
        if result.inertia is not None:
            inertias[k] = result.inertia
        rows.append({
            "k": int(k),
            "silhouette": indices.get("silhouette"),
            "davies_bouldin": indices.get("davies_bouldin"),
            "calinski_harabasz": indices.get("calinski_harabasz"),
            "inertia": result.inertia,
            "smallest_cluster_share": result.as_dict()["smallest_cluster_share"],
        })

    def _best(column: str, highest: bool) -> int | None:
        usable = [row for row in rows if row[column] is not None]
        if not usable:
            return None
        chosen = max(usable, key=lambda r: r[column]) if highest else min(usable, key=lambda r: r[column])
        return int(chosen["k"])

    preferences = {
        "silhouette": _best("silhouette", True),
        "davies_bouldin": _best("davies_bouldin", False),
        "calinski_harabasz": _best("calinski_harabasz", True),
    }
    knee = elbow(inertias) if inertias else {"available": False, "reason": "No inertia."}
    if knee.get("available"):
        preferences["elbow"] = knee["k"]

    agreed = len(set(v for v in preferences.values() if v is not None)) == 1

    return {
        "rows": rows,
        "preferred_k": preferences,
        "elbow": knee,
        "unanimous": agreed,
        "summary": (
            f"All indices prefer k={next(iter(set(preferences.values())))}, which "
            f"is unusually clear agreement and worth saying."
            if agreed else
            "The indices disagree on k, which is the normal case. The choice is "
            "the researcher's and belongs in the method with its reasoning; no "
            "single number is returned here because that would hide the "
            "disagreement."
        ),
    }
