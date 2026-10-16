"""Turning R, F and M into a matrix k-means can be run on, explicitly.

This module exists because of one sentence in the paper behind this dataset.
Chen, Sain & Guo (2012) state that k-means is sensitive to outliers and to
variables measured on incomparable scales. Recency is in days (0-700),
frequency is a count (1-200) and monetary is money (-1,343 to 280,000). Run
k-means on those raw columns and Euclidean distance is almost entirely
monetary distance: the clusters are "big spenders / everyone else", and
recency and frequency contribute nothing.

So every transform is a decision, each one is recorded in the output, and the
config has to name them. "We standardised" is not a method description; which
transform, applied to which variable, in which order, is.

**The negative-monetary problem.** `analytics/rfm.py` already found it on the
real data: monetary is net of returns, so customers who returned more than
they bought have negative value - the minimum was -1,343.24. A log transform
is undefined there. Three options are implemented and the choice is explicit:

* `signed_log`  - sign(x) * log1p(|x|). Keeps every customer, compresses both
                  tails, and is monotonic. The default.
* `shift_log`   - log1p(x - min + 1). Keeps everyone but makes the transform
                  depend on the most extreme customer in the window, which
                  means two windows get different transforms. Bad for stability
                  work; offered because it is common.
* `exclude`     - drop them and report how many. Honest, but it removes the
                  customers a returns-reduction intervention would target.

**Recency is inverted before scaling**, so that larger means better on all
three axes. Without it the cluster centroids are uninterpretable: a "high"
centroid would mean high spend and *stale*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

Transform = Literal["none", "log", "signed_log", "shift_log"]
Scaler = Literal["standard", "robust", "minmax", "none"]
NegativeHandling = Literal["signed_log", "shift_log", "exclude"]

DEFAULT_FEATURES = ("recency_days", "frequency", "monetary")

# Below this many customers a clustering is describing noise. Chen et al. had
# thousands; a window with fewer than this should be reported, not clustered.
MIN_CUSTOMERS = 50


@dataclass
class MatrixResult:
    """The feature matrix and every decision that produced it."""

    matrix: np.ndarray
    customers: list[str]
    features: list[str]
    transforms: dict[str, str]
    scaler: str
    excluded: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, int]:
        return self.matrix.shape

    def as_dict(self) -> dict[str, Any]:
        return {
            "customers": len(self.customers),
            "features": self.features,
            "transforms": self.transforms,
            "scaler": self.scaler,
            "excluded": self.excluded,
            "notes": self.notes,
        }


def _apply_transform(values: pd.Series, how: Transform) -> tuple[pd.Series, str]:
    """One variable, one transform, and the description that goes in the record."""
    numbers = pd.to_numeric(values, errors="coerce").astype("float64")

    if how == "none":
        return numbers, "none"
    if how == "log":
        if (numbers <= -1).any():
            raise ValueError(
                "A plain log transform was requested on a variable containing "
                "values at or below -1, where log1p is undefined. Use "
                "'signed_log' or 'shift_log', or exclude those customers."
            )
        return np.log1p(numbers), "log1p(x)"
    if how == "signed_log":
        # Monotonic across the whole real line and symmetric about zero, so a
        # customer at -500 and one at +500 are equally far from the middle.
        return np.sign(numbers) * np.log1p(numbers.abs()), "sign(x) * log1p(|x|)"
    if how == "shift_log":
        offset = float(numbers.min())
        shifted = np.log1p(numbers - offset)
        return shifted, f"log1p(x - ({offset:.2f}))"
    raise ValueError(f"Unknown transform '{how}'.")


def _apply_scaler(matrix: np.ndarray, how: Scaler) -> tuple[np.ndarray, str]:
    """Put the columns on a comparable footing. This is Chen et al.'s warning."""
    if how == "none":
        return matrix, "none"

    if how == "standard":
        centre = matrix.mean(axis=0)
        spread = matrix.std(axis=0, ddof=0)
    elif how == "robust":
        # Median and IQR: one extreme customer should not set the scale every
        # other customer is divided by, and retail monetary has exactly that
        # shape.
        centre = np.median(matrix, axis=0)
        spread = np.percentile(matrix, 75, axis=0) - np.percentile(matrix, 25, axis=0)
    elif how == "minmax":
        centre = matrix.min(axis=0)
        spread = matrix.max(axis=0) - matrix.min(axis=0)
    else:
        raise ValueError(f"Unknown scaler '{how}'.")

    # A constant column has zero spread. Dividing by it gives NaN and the
    # clustering fails somewhere far from here with an unhelpful message.
    spread = np.where(np.abs(spread) < 1e-12, 1.0, spread)
    return (matrix - centre) / spread, how


def build_matrix(
    customers: pd.DataFrame,
    *,
    features: tuple[str, ...] = DEFAULT_FEATURES,
    transforms: dict[str, Transform] | None = None,
    scaler: Scaler = "standard",
    negative_monetary: NegativeHandling = "signed_log",
    invert_recency: bool = True,
    customer_column: str = "customer",
) -> MatrixResult:
    """Feature matrix from an RFM table, with every decision recorded.

    `customers` is the table `analytics.rfm.build_rfm` puts in its `table` key:
    one row per customer with `recency_days`, `frequency` and `monetary`.
    """
    if customers.empty:
        raise ValueError("No customers to cluster.")

    missing = [name for name in features if name not in customers.columns]
    if missing:
        raise KeyError(
            f"The RFM table is missing {missing}. Expected the columns produced "
            f"by analytics.rfm.build_rfm: {list(DEFAULT_FEATURES)}."
        )

    frame = customers.copy()
    notes: list[str] = []
    excluded: dict[str, Any] = {}

    chosen: dict[str, Transform] = {
        "recency_days": "none",
        "frequency": "log",
        "monetary": negative_monetary if negative_monetary != "exclude" else "log",
    }
    if transforms:
        chosen.update(transforms)   # type: ignore[arg-type]

    if "monetary" in features and negative_monetary == "exclude":
        negative = frame["monetary"] <= 0
        if negative.any():
            excluded["negative_monetary_customers"] = int(negative.sum())
            excluded["minimum_monetary"] = float(frame["monetary"].min())
            notes.append(
                f"{int(negative.sum())} customers with net monetary value at or "
                f"below zero were excluded so a log transform could be applied. "
                f"They are real customers - their returns exceeded their "
                f"purchases - and they are exactly who a returns-reduction "
                f"intervention would target, so their absence belongs in the "
                f"limitations."
            )
            frame = frame[~negative]

    if len(frame) < MIN_CUSTOMERS:
        notes.append(
            f"Only {len(frame)} customers after preparation; below {MIN_CUSTOMERS} "
            f"a clustering describes noise. Treat any segments as indicative."
        )

    if invert_recency and "recency_days" in features:
        # Larger is better on every axis, so a high centroid reads as "recent,
        # frequent, high value" rather than needing a mental flip on one column.
        frame["recency_days"] = -frame["recency_days"]
        notes.append(
            "Recency is negated before scaling so that larger means better on "
            "all three axes; cluster centroids are otherwise uninterpretable."
        )

    columns = []
    applied: dict[str, str] = {}
    for name in features:
        transformed, description = _apply_transform(frame[name], chosen.get(name, "none"))
        columns.append(transformed.to_numpy())
        applied[name] = description

    matrix = np.column_stack(columns)
    usable = ~np.isnan(matrix).any(axis=1)
    dropped = int((~usable).sum())
    if dropped:
        excluded["non_numeric_rows"] = dropped
        notes.append(f"{dropped} rows had a missing or unreadable value and were dropped.")
    matrix = matrix[usable]

    scaled, scaler_name = _apply_scaler(matrix, scaler)

    return MatrixResult(
        matrix=scaled,
        customers=[str(value) for value in frame.loc[usable, customer_column]],
        features=list(features),
        transforms=applied,
        scaler=scaler_name,
        excluded=excluded,
        notes=notes,
    )


def scale_features(matrix: np.ndarray, how: Scaler = "standard") -> np.ndarray:
    """Scaler on its own, for callers that built their own matrix."""
    return _apply_scaler(matrix, how)[0]
