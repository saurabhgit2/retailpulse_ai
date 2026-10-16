"""Customer segmentation: RQ2.

Same rule as `app/analytics/`, `app/preprocessing/` and `app/forecasting/`:
**no web framework and no ORM in here.** Frames in, plain data out.

The question RQ2 asks is whether the segments a clustering produces are
*stable* - whether they describe the business or the particular slice of time
they were fitted to. That shapes the whole package:

1. `windows`    - the same customers measured at several as-of dates, so there
                  is something to compare across.
2. `scaling`    - the transform decisions Chen et al. warn about, made
                  explicitly and recorded, because k-means on unscaled RFM is
                  k-means on monetary value alone.
3. `clustering` - three families, one interface: partitioning (k-means),
                  hierarchical (Ward) and model-based (Gaussian mixture).
4. `quality`    - silhouette, Davies-Bouldin, Calinski-Harabasz, the elbow and
                  the gap statistic.
5. `stability`  - do the same customers stay together when the window moves?
6. `profiles`   - what each cluster is, in words a category manager can check.

**Grounding, and a warning about it.**

Chen, Sain & Guo (2012) is the paper behind this dataset: RFM aggregated per
customer, then k-means. `app/analytics/rfm.py` implements their aggregation and
carries their explicit warning forward - k-means is sensitive to outliers and
to variables on incomparable scales. That warning is why `scaling` is its own
module rather than a line inside the clustering call.

The quality indices here (silhouette, Davies-Bouldin, Calinski-Harabasz,
elbow, gap) were chosen because a review of the seventeen supplied papers found
those to be the indices in use in the segmentation literature of that set.
**That review was done when the papers were to hand and is recorded in the
project's backend guide; re-verify it against your own copies before citing
any of it.** Do not take the attribution from this docstring alone.

**The Adjusted Rand Index is not from that literature.** The same review found
"Adjusted Rand" absent from the supplied segmentation papers entirely. It is
used here because it is the standard way to ask whether two partitions of the
same objects agree, which is exactly the RQ2 question, and because the
alternative - eyeballing whether segments "look similar" - is not a measure.
Present it as a measurement choice of your own with that reasoning, or find and
read a reference for it. The same applies to the migration matrix.

This is the same position §12.7's entropy/mutual-information analysis was in,
and it was resolved the same way: by comparing the unsupported measure against
something standard and reporting whatever came out. `stability` therefore
reports ARI alongside the share of customers who simply stayed in the same
cluster, which needs no citation at all and which any reader can interpret.
"""

from __future__ import annotations

from app.segmentation.clustering import CLUSTERERS, cluster, fit_range
from app.segmentation.profiles import describe_clusters
from app.segmentation.quality import elbow, gap_statistic, quality_indices
from app.segmentation.scaling import build_matrix, scale_features
from app.segmentation.stability import migration_matrix, stability_across_windows
from app.segmentation.windows import make_windows

__all__ = [
    "CLUSTERERS",
    "build_matrix",
    "cluster",
    "describe_clusters",
    "elbow",
    "fit_range",
    "gap_statistic",
    "make_windows",
    "migration_matrix",
    "quality_indices",
    "scale_features",
    "stability_across_windows",
]
