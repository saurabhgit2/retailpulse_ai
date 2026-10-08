"""Feature analysis for the forecasting problem (architecture §12.7).

Builds the candidate feature table for weekly SKU demand and scores each
feature against the target by two independent methods:

1. **Discretised mutual information** - the target is cut into quantile bins
   and I(Y;X) comes from the contingency table. Reported at 3, 5 and 10 bins,
   because binning changes the answer and hiding that would be dishonest.
2. **k-nearest-neighbour mutual information** (`mutual_info_regression`), which
   needs no binning and handles continuous features directly.

Then the two rankings are compared with Spearman and Kendall rank correlation.
Agreement is reassuring; disagreement is a finding worth discussing.

**What is missing until Phase 5:** model-based importance - XGBoost gain and
permutation importance on the validation fold - needs a trained model. The
third comparison arrives with the forecasting engine; the architecture's full
§12.7 comparison is complete then.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_regression

from app.analytics.entropy import profile_categorical

RANDOM_STATE = 2026
LAGS = (1, 2, 4, 8)
ROLLING_WINDOWS = (4, 12)
MIN_ROWS = 60


def build_feature_table(
    weekly: pd.DataFrame,
    *,
    key: str = "product_code",
    period_column: str = "period",
    target_column: str = "units",
) -> pd.DataFrame:
    """Lagged and calendar features for weekly demand, one row per SKU-week.

    Every feature is built from information available **before** the week it
    predicts: lags and rolling statistics are shifted by one period first. A
    rolling mean that includes the current week would leak the answer into the
    features, and the model would look brilliant and forecast nothing.
    """
    if weekly.empty:
        return pd.DataFrame()

    frame = weekly.copy()
    frame[period_column] = pd.to_datetime(frame[period_column])
    frame[target_column] = (
        pd.to_numeric(frame[target_column], errors="coerce").fillna(0.0).astype("float64")
    )
    frame = frame.sort_values([key, period_column]).reset_index(drop=True)

    grouped = frame.groupby(key, observed=True)[target_column]
    for lag in LAGS:
        frame[f"lag_{lag}"] = grouped.shift(lag)

    shifted = grouped.shift(1)  # strictly past values
    for window in ROLLING_WINDOWS:
        rolled = shifted.groupby(frame[key], observed=True)
        frame[f"roll_mean_{window}"] = rolled.transform(
            lambda series, w=window: series.rolling(w, min_periods=2).mean()
        )
        frame[f"roll_std_{window}"] = rolled.transform(
            lambda series, w=window: series.rolling(w, min_periods=2).std()
        )

    periods = frame[period_column].dt
    frame["week_of_year"] = periods.isocalendar().week.astype("float64")
    frame["month"] = periods.month.astype("float64")
    frame["weeks_to_christmas"] = frame[period_column].apply(_weeks_to_christmas)

    # SKU age: how long this product has been selling, in weeks.
    first_seen = frame.groupby(key, observed=True)[period_column].transform("min")
    frame["sku_age_weeks"] = (frame[period_column] - first_seen).dt.days / 7.0

    if "avg_unit_price" in frame.columns:
        frame["avg_unit_price"] = pd.to_numeric(frame["avg_unit_price"], errors="coerce")
        median_price = frame.groupby(key, observed=True)["avg_unit_price"].transform("median")
        # Price relative to the SKU's own median: the discount proxy (F3).
        frame["price_ratio"] = frame["avg_unit_price"] / median_price.replace(0, np.nan)

    for optional in ("distinct_customers", "distinct_regions"):
        if optional in frame.columns:
            frame[optional] = pd.to_numeric(frame[optional], errors="coerce")

    return frame


def _weeks_to_christmas(timestamp: pd.Timestamp) -> float:
    christmas = pd.Timestamp(year=timestamp.year, month=12, day=25)
    if timestamp > christmas:
        christmas = pd.Timestamp(year=timestamp.year + 1, month=12, day=25)
    return float((christmas - timestamp).days) / 7.0


def numeric_feature_columns(frame: pd.DataFrame, target_column: str) -> list[str]:
    candidates = [
        column for column in frame.columns
        if column != target_column
        and pd.api.types.is_numeric_dtype(frame[column])
        and frame[column].notna().any()
    ]
    # An identifier-like column has maximal mutual information and zero
    # generalisation (§12.7 limitations), so it is never scored.
    return [c for c in candidates if not c.endswith("_id")]


def score_features(
    frame: pd.DataFrame,
    *,
    target_column: str = "units",
    categorical_columns: tuple[str, ...] = (),
    bin_options: tuple[int, ...] = (3, 5, 10),
    max_rows: int = 200_000,
) -> dict[str, object]:
    """Rank candidate features by two mutual-information estimators."""
    if frame.empty:
        return {"available": False, "reason": "No data."}

    numeric_columns = numeric_feature_columns(frame, target_column)
    if not numeric_columns:
        return {"available": False, "reason": "No numeric candidate features."}

    usable = frame[numeric_columns + [target_column]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(usable) < MIN_ROWS:
        return {
            "available": False,
            "reason": (
                f"Only {len(usable)} complete rows after building lagged features; "
                f"at least {MIN_ROWS} are needed."
            ),
        }

    sampled = usable
    if len(usable) > max_rows:
        # The kNN estimator is O(n log n) per feature; a fixed seed keeps the
        # sample reproducible.
        sampled = usable.sample(max_rows, random_state=RANDOM_STATE)

    target = sampled[target_column]
    knn_scores = mutual_info_regression(
        sampled[numeric_columns].to_numpy(dtype=float),
        target.to_numpy(dtype=float),
        random_state=RANDOM_STATE,
    )

    rows = []
    for column, knn in zip(numeric_columns, knn_scores, strict=True):
        binned_scores = {}
        for bins in bin_options:
            # Both sides are discretised so the contingency table is finite.
            feature_bins = pd.qcut(sampled[column], q=bins, duplicates="drop")
            target_bins = pd.qcut(target, q=bins, duplicates="drop")
            binned_scores[bins] = _contingency_mi(target_bins, feature_bins)

        default_bins = 5 if 5 in binned_scores else bin_options[0]
        rows.append({
            "feature": column,
            "mi_knn": float(knn),
            "mi_binned": binned_scores[default_bins],
            "mi_by_bins": {str(k): round(v, 4) for k, v in binned_scores.items()},
            "bin_sensitivity": float(
                max(binned_scores.values()) - min(binned_scores.values())
            ),
        })

    table = pd.DataFrame(rows)
    table["rank_knn"] = table["mi_knn"].rank(ascending=False)
    table["rank_binned"] = table["mi_binned"].rank(ascending=False)

    agreement = _rank_agreement(table["rank_knn"], table["rank_binned"])

    categorical = [
        profile_categorical(frame, column, frame[target_column], bin_options).as_dict()
        for column in categorical_columns
        if column in frame.columns
    ]

    ranked = table.sort_values("mi_knn", ascending=False)
    return {
        "available": True,
        "target": target_column,
        "rows_used": int(len(sampled)),
        "rows_available": int(len(usable)),
        "sampled": bool(len(usable) > max_rows),
        "features": ranked.to_dict(orient="records"),
        "categorical": categorical,
        "rank_agreement": agreement,
        "model_importance": None,
        "limitations": [
            "Mutual information is biased towards high-cardinality features; "
            "identifier-like columns are excluded for that reason.",
            "Discretised MI depends on the number of bins, which is why three "
            "bin counts are reported rather than one.",
            "Marginal MI ignores redundancy between features (lag 1 and a "
            "4-week rolling mean overlap) and ignores interactions.",
            "None of these measures is causal.",
            "Model-based importance (XGBoost gain and permutation importance) "
            "arrives with the forecasting engine in Phase 5.",
        ],
    }


def _contingency_mi(target_bins: pd.Series, feature_bins: pd.Series) -> float:
    from app.analytics.entropy import mutual_information

    return mutual_information(
        target_bins.astype("object"), feature_bins.astype("object")
    )


def _rank_agreement(first: pd.Series, second: pd.Series) -> dict[str, object]:
    if len(first) < 3:
        return {"available": False, "reason": "Too few features to compare rankings."}
    spearman = stats.spearmanr(first, second)
    kendall = stats.kendalltau(first, second)
    return {
        "available": True,
        "spearman": float(spearman.statistic),
        "spearman_p": float(spearman.pvalue),
        "kendall": float(kendall.statistic),
        "kendall_p": float(kendall.pvalue),
        "note": (
            "High agreement means the two estimators pick the same features. "
            "Where they disagree, the binned estimate is seeing a relationship "
            "only at coarse resolution, or the kNN estimate is picking up "
            "structure the bins hide."
        ),
    }
