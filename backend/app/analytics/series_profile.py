"""Per-series forecastability profile (architecture §12.7, PROPOSED P1).

This is the module that connects entropy to the forecasting question. Each
product's weekly demand series gets a profile:

* **length** and **zero share** - how much history there is, and how sparse;
* **ADI** (average demand interval) - the mean gap, in periods, between weeks
  with demand. 1.0 means it sells every week;
* **CV squared** - squared coefficient of variation of the non-zero demands:
  how variable the size of a sale is;
* **intermittency class** - the Syntetos-Boylan quadrant from ADI and CV²,
  with the conventional cut-offs ADI = 1.32 and CV² = 0.49;
* **spectral entropy** - how noise-like the series is. Low means regular or
  seasonal, and more forecastable; high (near 1) means close to white noise.

RQ1 then asks whether the winning model family changes with this profile,
rather than reporting one accuracy number for a whole dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

# Syntetos & Boylan's conventional boundaries.
ADI_CUTOFF = 1.32
CV2_CUTOFF = 0.49

MIN_PERIODS = 8


def spectral_entropy(values: np.ndarray) -> float | None:
    """Shannon entropy of the normalised power spectrum, scaled to 0-1.

    The periodogram says how much of the series' variance sits at each
    frequency. Treating that as a probability distribution and taking its
    entropy measures how spread out the variance is: a pure sine wave puts
    everything at one frequency (entropy 0), white noise spreads it evenly
    (entropy 1).
    """
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size < MIN_PERIODS or np.allclose(array, array[0]):
        return None

    # Remove the mean so the zero-frequency term does not dominate.
    _, power = signal.periodogram(array - array.mean())
    power = power[power > 0]
    if power.size < 2:
        return None

    density = power / power.sum()
    entropy_bits = float(-np.sum(density * np.log2(density)))
    return float(entropy_bits / np.log2(density.size))


def classify(adi: float | None, cv_squared: float | None) -> str:
    """The Syntetos-Boylan quadrant name."""
    if adi is None or cv_squared is None:
        return "unknown"
    if adi < ADI_CUTOFF:
        return "smooth" if cv_squared < CV2_CUTOFF else "erratic"
    return "intermittent" if cv_squared < CV2_CUTOFF else "lumpy"


def profile_series(values: pd.Series) -> dict[str, object]:
    """Profile one regularly spaced demand series (zeros included)."""
    array = (
        pd.to_numeric(pd.Series(values), errors="coerce")
        .fillna(0.0).astype("float64").to_numpy(dtype=float)
    )
    periods = int(array.size)
    if periods == 0:
        return {"periods": 0}

    non_zero = array[array > 0]
    zero_share = float((array <= 0).sum() / periods)

    # ADI counts periods per demand occurrence. With no demand at all it is
    # undefined rather than infinite.
    adi = float(periods / non_zero.size) if non_zero.size else None
    if non_zero.size > 1 and non_zero.mean() > 0:
        cv_squared = float((non_zero.std(ddof=1) / non_zero.mean()) ** 2)
    else:
        cv_squared = None

    return {
        "periods": periods,
        "total": float(array.sum()),
        "mean": float(array.mean()),
        "mean_non_zero": float(non_zero.mean()) if non_zero.size else None,
        "zero_share": zero_share,
        "adi": adi,
        "cv_squared": cv_squared,
        "intermittency_class": classify(adi, cv_squared),
        "spectral_entropy": spectral_entropy(array),
    }


def profile_many(
    frame: pd.DataFrame,
    *,
    key: str = "product_code",
    period_column: str = "period",
    value_column: str = "units",
    min_periods: int = 26,
) -> dict[str, object]:
    """Profile every series in a long frame of (key, period, value) rows.

    Missing periods are filled with zero across the **dataset's** full span, not
    each product's own span: a product that stopped selling has real zeros
    afterwards, and dropping them would flatter its regularity.
    """
    if frame.empty:
        return {"series": [], "summary": None, "min_periods": min_periods}

    data = frame.copy()
    data[period_column] = pd.to_datetime(data[period_column])
    # astype("float64") matters: the cleaning pipeline produces pandas' nullable
    # dtypes (Int64/Float64), and pivot_table cannot fill those.
    data[value_column] = (
        pd.to_numeric(data[value_column], errors="coerce").fillna(0.0).astype("float64")
    )

    wide = (
        data.pivot_table(index=period_column, columns=key, values=value_column,
                         aggfunc="sum", fill_value=0.0)
        .sort_index()
    )
    full_index = pd.date_range(wide.index.min(), wide.index.max(), freq="W-MON")
    wide = wide.reindex(full_index, fill_value=0.0)

    profiles = []
    for name in wide.columns:
        series = wide[name]
        # A product's history starts at its first sale: zeros before that are
        # "not stocked yet", not "did not sell".
        first_sale = series.to_numpy().nonzero()[0]
        if first_sale.size == 0:
            continue
        trimmed = series.iloc[first_sale[0]:]
        if len(trimmed) < min_periods:
            continue
        profile = profile_series(trimmed)
        profile[key] = name
        profiles.append(profile)

    if not profiles:
        return {
            "series": [], "summary": None, "min_periods": min_periods,
            "reason": f"No series has at least {min_periods} periods of history.",
        }

    table = pd.DataFrame(profiles)
    class_counts = table["intermittency_class"].value_counts().to_dict()

    return {
        "min_periods": min_periods,
        "series_count": int(len(table)),
        "series_excluded": int(wide.shape[1] - len(table)),
        "classes": {str(k): int(v) for k, v in class_counts.items()},
        "class_boundaries": {"adi": ADI_CUTOFF, "cv_squared": CV2_CUTOFF},
        "summary": {
            "median_periods": float(table["periods"].median()),
            "median_zero_share": float(table["zero_share"].median()),
            "median_adi": float(table["adi"].median(skipna=True)),
            "median_cv_squared": float(table["cv_squared"].median(skipna=True)),
            "median_spectral_entropy": (
                None if table["spectral_entropy"].isna().all()
                else float(table["spectral_entropy"].median(skipna=True))
            ),
        },
        "series": profiles,
        "note": (
            "Spectral entropy near 1 means the series is close to white noise "
            "and hard to forecast; near 0 means regular or strongly seasonal. "
            "Classes follow Syntetos and Boylan's ADI/CV-squared quadrants."
        ),
    }
