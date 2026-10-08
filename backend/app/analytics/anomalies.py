"""Anomaly detection on an aggregate series (architecture §12.8).

Deliberately simple and explainable: build a baseline for what each period
*should* have been, then flag periods whose deviation from it has a robust
z-score above the threshold. The output reads as a sentence - "this week was
4.1 robust standard deviations above what trend and seasonality predict" -
which a retail manager can act on. Isolation Forest was considered and
rejected in the architecture: harder to explain, and unnecessary for one series.

**Everything here is a median, not a mean, and that is the whole design.** An
anomaly detector built on means is self-defeating, because the anomaly it is
looking for distorts the baseline it is measured against. Two ways that bites,
both measured rather than assumed (see `tests/unit/test_anomalies.py`):

* a centred *moving average* trend spreads one spike across the whole window -
  a single outlier shifted the baseline for 52 weeks either side of itself and
  flagged 10% of the series;
* a *mean* seasonal profile lets one extreme week reshape its own week-of-year,
  pushing an equal and opposite residual onto that week in every other year.

A rolling median trend and a per-phase median seasonal profile both have a
breakdown point of 50%: the baseline does not move until half the data is
anomalous.

The seasonal component is only subtracted when there is enough history for it
to mean anything - see `MIN_CYCLES_FOR_SEASONAL`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_THRESHOLD = 3.5
_MAD_TO_SIGMA = 0.6745
_MEAN_DEVIATION_TO_SIGMA = 1.2533

# How many full cycles of history before a seasonal profile is worth
# subtracting. A 52-week profile has 52 free parameters; with two or three
# cycles each is estimated from two or three observations, so it fits noise and
# the residuals lose any stable scale. Measured on pure noise containing no
# anomaly at all, a 52-phase seasonal basis flagged 47% of periods at 2.3
# cycles and 14% at 4 cycles, against 0.2% at 10. Below the bar the detector
# removes the trend and claims nothing about seasonality.
MIN_CYCLES_FOR_SEASONAL = 8

# Trend window when there is not enough history for the seasonal period.
SHORT_TREND_WINDOW = 13


def _robust_scale(values: pd.Series) -> float:
    """MAD, scaled to be comparable to a standard deviation.

    0.6745 is the 75th percentile of the standard normal, so for normal data
    this matches an ordinary z-score. When more than half the values are
    identical the MAD is 0, and the scaled mean absolute deviation stands in.
    """
    clean = values.dropna()
    if clean.empty:
        return 0.0
    deviation = (clean - clean.median()).abs()
    mad = float(deviation.median())
    if mad > 0:
        return mad
    return float(deviation.mean()) * _MEAN_DEVIATION_TO_SIGMA


def _phase(timestamps: pd.Series, period: int, observations: int) -> pd.Series:
    """Which seasonal slot each period belongs to.

    Taken from the **calendar**, not from the row number. A year is 52.18 weeks,
    so a phase of `index % 52` slides against the calendar by about a week a
    year: after a decade, December sits in a different slot than it did at the
    start, the seasonal profile smears across slots, and every December looks
    unusual. ISO week number does not drift.
    """
    if period == 52:
        return timestamps.dt.isocalendar().week.astype(int).clip(upper=52)
    if period == 12:
        return timestamps.dt.month.astype(int)
    if period == 7:
        return timestamps.dt.dayofweek.astype(int)
    return pd.Series(np.arange(observations) % period, index=timestamps.index)


def _baseline(
    series: pd.Series, timestamps: pd.Series, period: int
) -> tuple[pd.Series, str, bool]:
    """Expected value per period, and whether the model is multiplicative.

    Retail seasonality is usually *multiplicative*: December is three times a
    normal week, not a fixed number of pounds above one. An additive seasonal
    offset cannot track that while the level grows - the offset fitted to early
    Decembers is far too small for later ones, and every December gets flagged.
    So when the series is strictly positive the seasonal profile is estimated
    as a **ratio** to the trend, and residuals are scored relative to the
    expected value rather than in absolute money.
    """
    observations = len(series)
    cycles = observations / period if period >= 2 else 0.0
    multiplicative = bool((series > 0).all())

    if cycles >= MIN_CYCLES_FOR_SEASONAL:
        window = period if period % 2 else period + 1  # odd window centres cleanly
        trend = series.rolling(window=window, center=True, min_periods=max(3, period // 2)).median()
        phase = _phase(timestamps, period, observations)
        shape = "multiplicative" if multiplicative else "additive"

        if multiplicative:
            ratio = series / trend.replace(0, np.nan)
            seasonal = ratio.groupby(phase).transform("median")
            centre = float(seasonal.median())
            seasonal = seasonal / centre if centre else seasonal
            expected = trend * seasonal
        else:
            detrended = series - trend
            seasonal = detrended.groupby(phase).transform("median")
            seasonal = seasonal - seasonal.median()  # the trend carries the level
            expected = trend + seasonal

        basis = (
            f"robust trend ({window}-period rolling median) and a {period}-phase "
            f"{shape} seasonal profile estimated by median"
        )
        return expected, basis, multiplicative

    window = max(3, min(SHORT_TREND_WINDOW, (observations // 3) * 2 + 1))
    trend = series.rolling(window=window, center=True, min_periods=1).median()
    basis = f"deviation from a centred {window}-period rolling median"
    if period >= 2 and cycles > 0:
        basis += (
            f" (only {cycles:.1f} cycles of history; {MIN_CYCLES_FOR_SEASONAL} are "
            f"needed before a {period}-phase seasonal profile is more signal than noise)"
        )
    return trend, basis, multiplicative


def detect_anomalies(
    frame: pd.DataFrame,
    *,
    value: str = "gross_revenue",
    period: int = 52,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, object]:
    """Flag unusual periods in an aggregated series."""
    if frame.empty or value not in frame.columns:
        return {"available": False, "reason": "No data in range.", "anomalies": []}

    data = frame.copy()
    data["period"] = pd.to_datetime(data["period"])
    data = data.sort_values("period").reset_index(drop=True)
    series = pd.to_numeric(data[value], errors="coerce").fillna(0.0).astype("float64")

    if len(series) < 8:
        return {"available": False, "reason": "Too few periods to judge.", "anomalies": []}

    expected, basis, multiplicative = _baseline(series, data["period"], period)
    residual = series - expected

    # What gets scored. With a growing trend the absolute residual grows too,
    # so a 10% miss late in the series dwarfs a 10% miss early on and the
    # detector flags whichever end happens to be larger. Scoring the
    # *proportional* miss removes that, whenever the series allows it.
    if multiplicative:
        scored = series / expected.replace(0, np.nan) - 1.0
        scale_basis = "proportional deviation from the expected value"
    else:
        scored = residual
        scale_basis = "absolute deviation from the expected value"

    usable = scored.dropna()
    if len(usable) < 5:
        return {"available": False, "reason": "Too few periods to judge.", "anomalies": []}

    median = float(usable.median())
    scale = _robust_scale(usable)

    # Guard against a scale that is numerically zero rather than genuinely so.
    # Floating-point dust in the denominator turns an ordinary week into a
    # thousand-sigma event, so the scale must be meaningful next to the spread
    # of the series it came from.
    reference = usable.abs().median() if multiplicative else float(
        np.percentile(series, 75) - np.percentile(series, 25)
    )
    floor = 1e-6 * max(float(reference), abs(float(series.median())), 1.0)
    if scale <= floor:
        return {
            "available": False,
            "reason": (
                "The residuals have effectively no spread, so no period can be "
                "called unusual."
            ),
            "anomalies": [],
        }

    robust_z = _MAD_TO_SIGMA * (scored - median).abs() / scale
    flagged = (robust_z > threshold).fillna(False)

    anomalies = []
    for position in np.flatnonzero(flagged.to_numpy()):
        direction = "above" if residual.iloc[position] > median else "below"
        anomalies.append({
            "period": data["period"].iloc[position].date().isoformat(),
            "observed": float(series.iloc[position]),
            "expected": float(expected.iloc[position]),
            "residual": float(residual.iloc[position]),
            "robust_z": float(robust_z.iloc[position]),
            "direction": direction,
            "explanation": (
                f"{robust_z.iloc[position]:.1f} robust standard deviations {direction} "
                f"the expected {float(expected.iloc[position]):,.0f}."
            ),
        })

    anomalies.sort(key=lambda row: row["robust_z"], reverse=True)
    return {
        "available": True,
        "basis": basis,
        "scored_on": scale_basis,
        "threshold": threshold,
        "periods_assessed": int(len(usable)),
        "anomaly_count": len(anomalies),
        "anomaly_rate": float(len(anomalies) / len(usable)),
        "anomalies": anomalies,
        "note": (
            "A flag is a prompt to look, not a verdict. A spike can be a real "
            "wholesale order, a correction, or a data problem. The baseline is "
            "built from medians so that the anomalies themselves do not move it."
        ),
    }
