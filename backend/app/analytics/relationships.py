"""Relationships between variables (architecture §12.5, §12.6).

Pearson and Spearman are always reported **side by side**, because the
difference between them is itself the finding: Pearson measures linear
association and is dragged around by the wholesale outliers; Spearman works on
ranks, so it survives the skew. When they disagree sharply, the relationship is
monotonic but not linear - which is the normal case for price and quantity.

Nothing here is causal, and the price-elasticity figure is a **proxy**: this
dataset has no promotion or cost columns, so what looks like a discount effect
can equally be product mix, seasonality, or wholesale customers buying cheaper
lines in bulk. That caveat travels with the number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

MIN_PAIRS = 10


def _clean_pair(left: pd.Series, right: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame({"left": pd.to_numeric(left, errors="coerce"),
                          "right": pd.to_numeric(right, errors="coerce")}).dropna()
    return frame[np.isfinite(frame["left"]) & np.isfinite(frame["right"])]


def correlation_pair(left: pd.Series, right: pd.Series) -> dict[str, object]:
    """Pearson and Spearman for one pair, with p-values and the sample size."""
    pair = _clean_pair(left, right)
    if len(pair) < MIN_PAIRS or pair["left"].nunique() < 2 or pair["right"].nunique() < 2:
        return {"n": int(len(pair)), "pearson": None, "pearson_p": None,
                "spearman": None, "spearman_p": None}

    pearson = stats.pearsonr(pair["left"], pair["right"])
    spearman = stats.spearmanr(pair["left"], pair["right"])
    return {
        "n": int(len(pair)),
        "pearson": float(pearson.statistic),
        "pearson_p": float(pearson.pvalue),
        "spearman": float(spearman.statistic),
        "spearman_p": float(spearman.pvalue),
    }


def correlation_matrix(frame: pd.DataFrame, columns: list[str]) -> dict[str, object]:
    """Both correlation matrices over the given numeric columns."""
    usable = [column for column in columns if column in frame.columns]
    numeric = frame[usable].apply(pd.to_numeric, errors="coerce")

    pearson = numeric.corr(method="pearson")
    spearman = numeric.corr(method="spearman")

    def as_rows(matrix: pd.DataFrame) -> list[dict[str, object]]:
        return [
            {"row": row, **{column: (None if pd.isna(value) else float(value))
                            for column, value in matrix.loc[row].items()}}
            for row in matrix.index
        ]

    # The largest gap between the two methods: where the skew bites hardest.
    disagreements = []
    for i, first in enumerate(usable):
        for second in usable[i + 1:]:
            p, s = pearson.loc[first, second], spearman.loc[first, second]
            if pd.notna(p) and pd.notna(s):
                disagreements.append({
                    "pair": [first, second],
                    "pearson": float(p),
                    "spearman": float(s),
                    "difference": float(abs(p - s)),
                })
    disagreements.sort(key=lambda row: row["difference"], reverse=True)

    return {
        "columns": usable,
        "n": int(len(numeric.dropna())),
        "pearson": as_rows(pearson),
        "spearman": as_rows(spearman),
        "largest_disagreements": disagreements[:5],
        "note": (
            "Pearson measures linear association; Spearman measures monotonic "
            "association on ranks and is robust to the right-skew in retail "
            "values. A large gap means the relationship is not linear. "
            "Correlation is not causation, and both variables trending over "
            "time can produce a correlation with no direct relationship."
        ),
    }


def price_quantity_relationship(product_periods: pd.DataFrame) -> dict[str, object]:
    """Log-log slope of quantity against unit price: an elasticity *proxy*.

    `product_periods` has one row per product per period with `avg_unit_price`
    and `units`. Fitting log(units) on log(price) gives a slope that reads as a
    percentage change in units per percentage change in price. It is a proxy
    because price here is an average of what was actually charged, not an
    experiment: nothing was held constant.
    """
    frame = product_periods.copy()
    for column in ("avg_unit_price", "units"):
        if column not in frame.columns:
            return {"available": False, "reason": f"missing column {column!r}"}
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame[(frame["avg_unit_price"] > 0) & (frame["units"] > 0)].dropna(
        subset=["avg_unit_price", "units"]
    )
    if len(frame) < MIN_PAIRS:
        return {"available": False, "reason": "Not enough price/quantity pairs."}

    log_price = np.log(frame["avg_unit_price"].to_numpy(dtype=float))
    log_units = np.log(frame["units"].to_numpy(dtype=float))
    fit = stats.linregress(log_price, log_units)

    return {
        "available": True,
        "n": int(len(frame)),
        "elasticity_proxy": float(fit.slope),
        "intercept": float(fit.intercept),
        "r_squared": float(fit.rvalue ** 2),
        "p_value": float(fit.pvalue),
        "standard_error": float(fit.stderr),
        "correlation": correlation_pair(frame["avg_unit_price"], frame["units"]),
        "interpretation": (
            f"A 1% higher average unit price is associated with "
            f"{fit.slope:+.2f}% units, across products and periods."
        ),
        "caveats": [
            "Association, not causation: nothing was held constant.",
            "Average price per period hides within-period variation and mix.",
            "This dataset has no promotion, cost or margin columns, so a genuine "
            "discount cannot be distinguished from a change in product mix.",
            "Products are pooled, so cheap high-volume lines dominate the fit.",
        ],
    }


def discount_proxy(product_periods: pd.DataFrame) -> dict[str, object]:
    """Price relative to each product's own median price, against quantity.

    Comparing a product with itself removes the mix problem above: a ratio below
    1 means the product sold below its usual price that period. It still is not
    a promotion flag - the dataset has none - but it is a better proxy (F3).
    """
    frame = product_periods.copy()
    required = {"product_code", "avg_unit_price", "units"}
    if not required.issubset(frame.columns):
        return {"available": False, "reason": f"needs columns {sorted(required)}"}

    frame["avg_unit_price"] = pd.to_numeric(frame["avg_unit_price"], errors="coerce")
    frame["units"] = pd.to_numeric(frame["units"], errors="coerce")
    frame = frame[(frame["avg_unit_price"] > 0) & (frame["units"] > 0)].dropna(
        subset=["avg_unit_price", "units", "product_code"]
    )
    if len(frame) < MIN_PAIRS:
        return {"available": False, "reason": "Not enough product periods."}

    median_price = frame.groupby("product_code")["avg_unit_price"].transform("median")
    frame = frame[median_price > 0].copy()
    frame["price_ratio"] = frame["avg_unit_price"] / median_price[median_price > 0]

    # Buckets are reported rather than only a correlation, because the shape is
    # usually non-linear: a small discount does little, a large one moves volume.
    edges = [0, 0.8, 0.95, 1.05, 1.2, np.inf]
    labels = ["<80% of usual", "80-95%", "around usual", "105-120%", ">120%"]
    frame["band"] = pd.cut(frame["price_ratio"], bins=edges, labels=labels, right=False)

    bands = []
    overall_median_units = float(frame["units"].median())
    for label, group in frame.groupby("band", observed=True):
        bands.append({
            "band": str(label),
            "product_periods": int(len(group)),
            "median_units": float(group["units"].median()),
            "mean_units": float(group["units"].mean()),
            "relative_to_overall": (
                float(group["units"].median() / overall_median_units)
                if overall_median_units else None
            ),
        })

    return {
        "available": True,
        "n": int(len(frame)),
        "overall_median_units": overall_median_units,
        "bands": bands,
        "correlation": correlation_pair(frame["price_ratio"], frame["units"]),
        "caveats": [
            "A price below a product's median is not necessarily a promotion: it "
            "can be a wholesale order, a different market, or a price change.",
            "Products with few periods have an unstable median.",
        ],
    }
