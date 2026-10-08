"""Shannon entropy and mutual information (architecture §12.7).

Deliberately written from the definitions rather than imported, because the
report has to explain them and a formula you implemented is a formula you can
defend.

    H(X)   = - sum p_i log2 p_i                     (bits)
    H(X|Y) = sum_y p(y) H(X | Y = y)
    I(X;Y) = H(X) - H(X|Y) = H(X) + H(Y) - H(X,Y)

H = 0 when every record has the same value (no uncertainty). H = log2 k when all
k categories are equally likely (maximum uncertainty). Because that maximum
depends on k, `normalised_entropy` divides by log2 k so features with different
numbers of categories can be compared on a 0-1 scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Values below this are treated as zero when normalising, so a column with a
# single category does not divide by log2(1) = 0.
_EPSILON = 1e-12


def entropy_from_counts(counts: np.ndarray | pd.Series | list[float]) -> float:
    """Shannon entropy in bits from raw counts (or any non-negative weights)."""
    values = np.asarray(counts, dtype=float)
    values = values[values > 0]
    total = values.sum()
    if total <= 0 or values.size == 0:
        return 0.0
    probabilities = values / total
    return float(-np.sum(probabilities * np.log2(probabilities)))


def entropy(values: pd.Series) -> float:
    """Entropy of a categorical column, ignoring missing values."""
    return entropy_from_counts(values.dropna().value_counts().to_numpy())


def max_entropy(category_count: int) -> float:
    """log2 k: the entropy of k equally likely categories."""
    return float(np.log2(category_count)) if category_count > 1 else 0.0


def normalised_entropy(values: pd.Series) -> float:
    """H / log2 k, in [0, 1]. 0 means one value dominates completely."""
    clean = values.dropna()
    distinct = int(clean.nunique())
    ceiling = max_entropy(distinct)
    if ceiling <= _EPSILON:
        return 0.0
    return float(entropy_from_counts(clean.value_counts().to_numpy()) / ceiling)


def joint_entropy(left: pd.Series, right: pd.Series) -> float:
    """H(X, Y) from the contingency table of two aligned categorical columns."""
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if frame.empty:
        return 0.0
    counts = frame.groupby(["left", "right"], observed=True).size().to_numpy()
    return entropy_from_counts(counts)


def conditional_entropy(target: pd.Series, given: pd.Series) -> float:
    """H(target | given): the uncertainty about the target once `given` is known."""
    return joint_entropy(target, given) - entropy(given.dropna())


def mutual_information(left: pd.Series, right: pd.Series) -> float:
    """I(X; Y) in bits. Zero when independent; never negative.

    Computed as H(X) + H(Y) - H(X, Y) on the rows where both are present, so
    the three terms come from the same sample.
    """
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if frame.empty:
        return 0.0
    score = (
        entropy(frame["left"]) + entropy(frame["right"]) - joint_entropy(frame["left"], frame["right"])
    )
    # Floating point can leave a value like -2e-16 on independent columns.
    return float(max(score, 0.0))


def symmetric_uncertainty(left: pd.Series, right: pd.Series) -> float:
    """2 I(X;Y) / (H(X) + H(Y)): mutual information on a 0-1 scale.

    Raw mutual information is biased towards high-cardinality features - an ID
    column has maximal MI and zero generalisation (§12.7 limitations). Dividing
    by the entropies dampens that, and makes features comparable.
    """
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if frame.empty:
        return 0.0
    denominator = entropy(frame["left"]) + entropy(frame["right"])
    if denominator <= _EPSILON:
        return 0.0
    return float(2.0 * mutual_information(frame["left"], frame["right"]) / denominator)


def quantile_bins(values: pd.Series, bins: int) -> pd.Series:
    """Discretise a numeric target into quantile bins, for the contingency table.

    Quantile bins rather than equal-width bins because retail values are heavily
    right-skewed: equal-width bins would put almost every row in the first one.
    Duplicate edges are dropped, so the result can have fewer than `bins` levels
    when the data is concentrated - which is itself worth reporting.
    """
    clean = pd.to_numeric(values, errors="coerce")
    try:
        binned = pd.qcut(clean, q=bins, duplicates="drop")
    except ValueError:
        return pd.Series(pd.NA, index=values.index, dtype="object")
    return binned.astype("object")


@dataclass
class FeatureEntropy:
    """Entropy of one categorical feature, and its dependence on the target."""

    feature: str
    distinct_values: int
    entropy_bits: float
    max_entropy_bits: float
    normalised_entropy: float
    mutual_information_bits: float | None = None
    symmetric_uncertainty: float | None = None
    # I(Y;X) recomputed at 3, 5 and 10 target bins. Binning changes the answer,
    # so the sensitivity is reported rather than one number being presented as
    # the truth (§12.7).
    mi_by_bins: dict[int, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "distinct_values": self.distinct_values,
            "entropy_bits": round(self.entropy_bits, 4),
            "max_entropy_bits": round(self.max_entropy_bits, 4),
            "normalised_entropy": round(self.normalised_entropy, 4),
            "mutual_information_bits": (
                None if self.mutual_information_bits is None
                else round(self.mutual_information_bits, 4)
            ),
            "symmetric_uncertainty": (
                None if self.symmetric_uncertainty is None
                else round(self.symmetric_uncertainty, 4)
            ),
            "mi_by_bins": {str(k): round(v, 4) for k, v in self.mi_by_bins.items()},
        }


def profile_categorical(
    frame: pd.DataFrame,
    feature: str,
    target: pd.Series | None = None,
    bin_options: tuple[int, ...] = (3, 5, 10),
) -> FeatureEntropy:
    """Entropy of one categorical column, plus its mutual information with a
    numeric target discretised at several bin counts."""
    values = frame[feature]
    clean = values.dropna()
    distinct = int(clean.nunique())

    profile = FeatureEntropy(
        feature=feature,
        distinct_values=distinct,
        entropy_bits=entropy(values),
        max_entropy_bits=max_entropy(distinct),
        normalised_entropy=normalised_entropy(values),
    )

    if target is not None and len(target) == len(values):
        for bins in bin_options:
            binned = quantile_bins(target, bins)
            profile.mi_by_bins[bins] = mutual_information(binned, values)
        default_bins = 5 if 5 in profile.mi_by_bins else bin_options[0]
        profile.mutual_information_bits = profile.mi_by_bins[default_bins]
        profile.symmetric_uncertainty = symmetric_uncertainty(
            quantile_bins(target, default_bins), values
        )

    return profile
