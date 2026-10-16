"""Three clustering families behind one interface.

Chen, Sain & Guo (2012) used k-means on RFM, and k-means is the natural
baseline here for that reason. But k-means assumes clusters are roughly
spherical and equally sized in the scaled space, and RFM after a log transform
is not obviously either. Running one algorithm and reporting its output
answers "what does k-means say", not "how do these customers group" - so three
families run, and where they agree the finding is much stronger than where
only one does.

| name           | family        | what it assumes |
|----------------|---------------|-----------------|
| `kmeans`       | partitioning  | spherical, similar-sized clusters; minimises within-cluster variance |
| `hierarchical` | agglomerative | nested structure; Ward merges the pair that increases variance least |
| `gaussian`     | model-based   | a mixture of Gaussians; clusters may differ in size, shape and orientation |

**Determinism.** k-means and Gaussian mixtures both start from a random
initialisation, so the same data gives different labels on different runs
unless the seed is fixed. Every model here takes `random_state` and it is
recorded with the results. Without that, "the segments changed" could mean the
business changed or could mean the random seed did - and the whole of RQ2 is
about telling those two apart.

**Labels are arbitrary.** Cluster 0 in one run and cluster 0 in the next are
not the same group; the numbering comes from initialisation order. Anything
comparing two partitions must use a measure that ignores the labels - which is
why `stability.py` uses the Adjusted Rand Index and a matched migration matrix
rather than counting equal label values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

# Two clusters is the smallest partition worth the name; above about eight,
# retail segments stop being actionable - a manager cannot run eight campaigns.
MIN_CLUSTERS = 2
DEFAULT_MAX_CLUSTERS = 8

DEFAULT_SEED = 20260101


@dataclass
class ClusterResult:
    """Labels, centroids and the settings that produced them."""

    algorithm: str
    k: int
    labels: np.ndarray
    centroids: np.ndarray | None
    inertia: float | None
    converged: bool
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def sizes(self) -> dict[int, int]:
        values, counts = np.unique(self.labels, return_counts=True)
        return {int(v): int(c) for v, c in zip(values, counts, strict=True)}

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "k": self.k,
            "sizes": self.sizes,
            "inertia": self.inertia,
            "converged": self.converged,
            "settings": self.settings,
            "smallest_cluster_share": (
                min(self.sizes.values()) / len(self.labels) if len(self.labels) else None
            ),
        }


def _kmeans(matrix: np.ndarray, k: int, seed: int) -> ClusterResult:
    from sklearn.cluster import KMeans

    # n_init=10 runs ten initialisations and keeps the best. One run of k-means
    # can land in a poor local minimum, and a poor local minimum looks exactly
    # like "these customers do not group well".
    model = KMeans(n_clusters=k, n_init=10, random_state=seed)
    labels = model.fit_predict(matrix)
    return ClusterResult(
        algorithm="kmeans", k=k, labels=labels,
        centroids=model.cluster_centers_,
        inertia=float(model.inertia_),
        converged=bool(model.n_iter_ < model.max_iter),
        settings={"n_init": 10, "random_state": seed},
    )


def _hierarchical(matrix: np.ndarray, k: int, seed: int) -> ClusterResult:
    from sklearn.cluster import AgglomerativeClustering

    model = AgglomerativeClustering(n_clusters=k, linkage="ward")
    labels = model.fit_predict(matrix)
    # Agglomerative clustering has no centroids of its own; the mean of each
    # cluster is the comparable quantity and is what the profiles use.
    centroids = np.vstack([matrix[labels == label].mean(axis=0) for label in range(k)])
    return ClusterResult(
        algorithm="hierarchical", k=k, labels=labels,
        centroids=centroids, inertia=None, converged=True,
        settings={"linkage": "ward", "deterministic": True},
    )


def _gaussian(matrix: np.ndarray, k: int, seed: int) -> ClusterResult:
    from sklearn.mixture import GaussianMixture

    model = GaussianMixture(n_components=k, covariance_type="full",
                            n_init=5, random_state=seed)
    labels = model.fit_predict(matrix)
    return ClusterResult(
        algorithm="gaussian", k=k, labels=labels,
        centroids=model.means_, inertia=None,
        converged=bool(model.converged_),
        settings={"covariance_type": "full", "n_init": 5, "random_state": seed},
    )


CLUSTERERS: dict[str, Callable[[np.ndarray, int, int], ClusterResult]] = {
    "kmeans": _kmeans,
    "hierarchical": _hierarchical,
    "gaussian": _gaussian,
}


def cluster(
    matrix: np.ndarray, k: int, algorithm: str = "kmeans", *, seed: int = DEFAULT_SEED
) -> ClusterResult:
    """Fit one algorithm at one k."""
    if algorithm not in CLUSTERERS:
        raise KeyError(
            f"Unknown algorithm '{algorithm}'. Available: {', '.join(sorted(CLUSTERERS))}."
        )
    if k < MIN_CLUSTERS:
        raise ValueError(f"k must be at least {MIN_CLUSTERS}; got {k}.")
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        raise ValueError("The feature matrix is empty.")
    if k > matrix.shape[0]:
        raise ValueError(
            f"Asked for {k} clusters from {matrix.shape[0]} customers. There has "
            f"to be at least one customer per cluster."
        )
    return CLUSTERERS[algorithm](matrix, k, seed)


def fit_range(
    matrix: np.ndarray,
    algorithm: str = "kmeans",
    *,
    k_min: int = MIN_CLUSTERS,
    k_max: int = DEFAULT_MAX_CLUSTERS,
    seed: int = DEFAULT_SEED,
) -> dict[int, ClusterResult]:
    """Fit every k in a range, so the quality indices have a curve to read.

    Choosing k is not a decision the data makes on its own: the indices
    disagree, and `quality.py` reports all of them rather than returning a
    single number dressed up as an answer.
    """
    if k_max < k_min:
        raise ValueError(f"k_max ({k_max}) must be at least k_min ({k_min}).")

    results: dict[int, ClusterResult] = {}
    ceiling = min(k_max, matrix.shape[0] - 1)
    for k in range(k_min, ceiling + 1):
        results[k] = cluster(matrix, k, algorithm, seed=seed)
    return results
