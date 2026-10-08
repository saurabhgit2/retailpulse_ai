"""Univariate distributions (architecture §12.5, §12.6).

Retail money is heavily right-skewed: most orders are small, a few wholesale
orders are enormous. So this module always reports the **median beside the
mean** - seeing both is what shows the skew - and measures spread robustly with
the IQR as well as the standard deviation.

Outliers are counted by two fences, never removed:

* Tukey: outside Q1 - 1.5 IQR .. Q3 + 1.5 IQR
* robust z: |0.6745 (x - median) / MAD| > threshold

Both are robust: unlike a mean/SD rule, the outliers themselves do not inflate
the threshold that is meant to catch them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
DEFAULT_BINS = 40
ROBUST_Z_THRESHOLD = 3.5
# 0.6745 is the 75th percentile of the standard normal: it scales the MAD so
# that, for normal data, the robust z matches an ordinary z-score.
_MAD_TO_SIGMA = 0.6745
# For a normal distribution, mean absolute deviation = sigma * sqrt(2/pi),
# so this factor converts it back. Used when the MAD is zero.
_MEAN_DEVIATION_TO_SIGMA = 1.2533


def _histogram(values: np.ndarray, bins: int, log_scale: bool) -> dict[str, object]:
    usable = values[values > 0] if log_scale else values
    if usable.size == 0:
        return {"log_scale": log_scale, "edges": [], "counts": []}

    if log_scale:
        edges = np.logspace(np.log10(usable.min()), np.log10(usable.max()), bins + 1)
    else:
        edges = np.linspace(usable.min(), usable.max(), bins + 1)

    if np.allclose(edges[0], edges[-1]):  # every value identical
        return {
            "log_scale": log_scale,
            "edges": [float(edges[0]), float(edges[0])],
            "counts": [int(usable.size)],
        }

    counts, _ = np.histogram(usable, bins=edges)
    return {
        "log_scale": log_scale,
        "edges": [float(edge) for edge in edges],
        "counts": [int(count) for count in counts],
        "excluded_non_positive": int(values.size - usable.size) if log_scale else 0,
    }


def describe_distribution(
    values: pd.Series, *, bins: int = DEFAULT_BINS, field: str = "value"
) -> dict[str, object]:
    """Summary statistics, percentiles, a histogram and outlier counts."""
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    numeric = numeric[np.isfinite(numeric)]

    if numeric.empty:
        return {"field": field, "count": 0, "summary": None, "percentiles": {},
                "histogram": None, "outliers": None}

    array = numeric.to_numpy(dtype=float)
    mean = float(array.mean())
    median = float(np.median(array))
    sd = float(array.std(ddof=1)) if array.size > 1 else 0.0

    quartile_1, quartile_3 = (float(x) for x in np.percentile(array, [25, 75]))
    iqr = quartile_3 - quartile_1
    lower_fence, upper_fence = quartile_1 - 1.5 * iqr, quartile_3 + 1.5 * iqr

    deviation = np.abs(array - median)
    mad = float(np.median(deviation))
    # When more than half the values are identical the MAD is 0 and the robust
    # z is undefined; fall back to the scaled mean absolute deviation.
    scale = mad if mad > 0 else float(deviation.mean()) * _MEAN_DEVIATION_TO_SIGMA
    if scale > 0:
        robust_z = _MAD_TO_SIGMA * deviation / scale
        robust_outliers = int((robust_z > ROBUST_Z_THRESHOLD).sum())
    else:
        robust_outliers = 0  # every value is the same: nothing can be unusual

    # Skewness and kurtosis from the definitions (Fisher: normal has kurtosis 0)
    if array.size > 2 and sd > 0:
        standardised = (array - mean) / sd
        skewness = float((standardised ** 3).mean())
        kurtosis = float((standardised ** 4).mean() - 3.0)
    else:
        skewness = kurtosis = 0.0

    percentiles = {
        str(p): float(np.percentile(array, p)) for p in PERCENTILES
    }

    return {
        "field": field,
        "count": int(array.size),
        "summary": {
            "mean": mean,
            "median": median,
            "std_dev": sd,
            # CV compares volatility across series of different sizes; it is
            # meaningless when the mean is near zero, so it is withheld then.
            "coefficient_of_variation": float(sd / mean) if abs(mean) > 1e-9 else None,
            "min": float(array.min()),
            "max": float(array.max()),
            "sum": float(array.sum()),
            "iqr": iqr,
            "skewness": skewness,
            "kurtosis_excess": kurtosis,
            # A rule of thumb worth stating rather than hiding: |skew| > 1 is
            # strongly skewed, and the mean stops describing a typical case.
            "strongly_skewed": bool(abs(skewness) > 1.0),
        },
        "percentiles": percentiles,
        "histogram": _histogram(array, bins, log_scale=False),
        "histogram_log": _histogram(array, bins, log_scale=True),
        "outliers": {
            "tukey_lower_fence": lower_fence,
            "tukey_upper_fence": upper_fence,
            "tukey_count": int(((array < lower_fence) | (array > upper_fence)).sum()),
            "robust_z_threshold": ROBUST_Z_THRESHOLD,
            "robust_z_count": robust_outliers,
            "note": "Outliers are flagged for inspection, never removed.",
        },
    }
