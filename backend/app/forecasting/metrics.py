"""Forecast error measures, and what each one does when the actual is zero.

Finding F7 in the architecture is the reason this module is careful: weekly
sales for an individual SKU are often zero, and the percentage measures are
either undefined or explosive there. A library that silently drops those rows
reports an error computed on a different, easier dataset than the one it claims.

So every measure here returns a `Metric` carrying the value **and** the number
of observations it was actually computed on. If MAPE skipped 14 of 52 weeks,
that shows up in the results table next to the number.

**Several measures, not one.** Chu & Zhang (2003) used RMSE, MAE and MAPE
together, noting that "there is no universally agreed-upon performance measure
that can be applied to every forecasting situation, multiple criteria are
therefore often needed to give a comprehensive assessment". Aras et al. (2017)
used RMSE, MAE, MAPE, sMAPE and Theil's U for the same reason. Reporting one
number invites the suspicion that it was the flattering one.

**On WAPE, carefully.** Auppakorn & Phumchusri (2022) report "WAPE" as their
headline measure, but their definition is a *revenue-weighted average of
per-product MAPEs* - "the weight is calculated from the %contribution of
revenue from that product to all considered products". That is not the common
WAPE, which is a single ratio of summed absolute error to summed actuals. Both
are implemented, under different names (`wape` and `revenue_weighted_mape`),
and the paper supports only the second. Getting this wrong in the report would
be a misattribution that a careful examiner would catch.

**On MASE.** It appears nowhere in the seventeen supplied papers. It is
included because it is finite and interpretable on zero weeks where MAPE is
not, and because it compares a model against the seasonal naive benchmark on
the model's own training data. The usual reference is Hyndman & Koehler (2006),
"Another look at measures of forecast accuracy", *International Journal of
Forecasting* - **outside the supplied set, so read it before citing it.** If
you would rather not add a reference, present MASE as your own measurement
choice and justify it with the zero-week argument, which stands on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# MAPE on a near-zero actual is arbitrarily large and swamps the average. The
# rows are excluded and counted rather than clipped, because clipping invents a
# denominator that was never in the data.
MAPE_FLOOR = 1e-9


@dataclass(frozen=True)
class Metric:
    """A value, how many points produced it, and how many were unusable."""

    name: str
    value: float | None
    used: int
    excluded: int = 0
    note: str | None = None

    def as_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "name": self.name,
            "value": self.value,
            "observations_used": self.used,
        }
        if self.excluded:
            record["observations_excluded"] = self.excluded
        if self.note:
            record["note"] = self.note
        return record


def _aligned(actual, predicted) -> tuple[np.ndarray, np.ndarray]:
    """Two float arrays of equal length, with any NaN pair removed."""
    y = np.asarray(pd.Series(actual).to_numpy(), dtype="float64")
    f = np.asarray(pd.Series(predicted).to_numpy(), dtype="float64")
    if y.shape != f.shape:
        raise ValueError(
            f"Actual and predicted must be the same length; got {y.shape[0]} "
            f"and {f.shape[0]}. A length mismatch here usually means the forecast "
            f"was generated for a different horizon than the test window."
        )
    usable = ~(np.isnan(y) | np.isnan(f))
    return y[usable], f[usable]


def mae(actual, predicted) -> Metric:
    """Mean absolute error. Scale-dependent; comparable only within one series."""
    y, f = _aligned(actual, predicted)
    if y.size == 0:
        return Metric("MAE", None, 0, note="No usable observations.")
    return Metric("MAE", float(np.mean(np.abs(y - f))), int(y.size))


def rmse(actual, predicted) -> Metric:
    """Root mean squared error. Punishes a few large misses more than MAE does."""
    y, f = _aligned(actual, predicted)
    if y.size == 0:
        return Metric("RMSE", None, 0, note="No usable observations.")
    return Metric("RMSE", float(np.sqrt(np.mean((y - f) ** 2))), int(y.size))


def mape(actual, predicted) -> Metric:
    """Mean absolute percentage error, on non-zero actuals only.

    The excluded count is part of the result, not a footnote. A MAPE computed
    on 38 of 52 weeks is a statement about those 38 weeks.
    """
    y, f = _aligned(actual, predicted)
    if y.size == 0:
        return Metric("MAPE", None, 0, note="No usable observations.")

    usable = np.abs(y) > MAPE_FLOOR
    excluded = int((~usable).sum())
    if not usable.any():
        return Metric(
            "MAPE", None, 0, excluded,
            note="Every actual in this window is zero, so MAPE is undefined.",
        )

    value = float(np.mean(np.abs((y[usable] - f[usable]) / y[usable])) * 100)
    note = (
        None if excluded == 0
        else f"{excluded} of {y.size} periods had a zero actual and are excluded."
    )
    return Metric("MAPE", value, int(usable.sum()), excluded, note)


def smape(actual, predicted) -> Metric:
    """Symmetric MAPE, as used by Aras et al. (2017).

    Defined wherever |y| + |f| > 0, so a zero actual is only a problem when the
    forecast is zero too - in which case the error is genuinely zero and the
    period is simply skipped.
    """
    y, f = _aligned(actual, predicted)
    if y.size == 0:
        return Metric("sMAPE", None, 0, note="No usable observations.")

    denominator = (np.abs(y) + np.abs(f)) / 2
    usable = denominator > MAPE_FLOOR
    excluded = int((~usable).sum())
    if not usable.any():
        return Metric("sMAPE", None, 0, excluded, note="Actual and forecast are both zero throughout.")

    value = float(np.mean(np.abs(y[usable] - f[usable]) / denominator[usable]) * 100)
    return Metric("sMAPE", value, int(usable.sum()), excluded)


def wape(actual, predicted) -> Metric:
    """Weighted absolute percentage error: sum|y - f| / sum|y|.

    The ratio of total error to total volume. Defined whenever the window has
    any volume at all, which makes it the natural percentage measure for
    intermittent SKUs, and it weights each period by its size rather than
    treating a 100% miss on a one-unit week as equal to a 100% miss on a
    thousand-unit week.

    Note the attribution: this aggregate form is **not** the definition used by
    Auppakorn & Phumchusri (2022), despite the shared name. See the module
    docstring and `revenue_weighted_mape`.
    """
    y, f = _aligned(actual, predicted)
    if y.size == 0:
        return Metric("WAPE", None, 0, note="No usable observations.")

    volume = float(np.sum(np.abs(y)))
    if volume <= MAPE_FLOOR:
        return Metric(
            "WAPE", None, 0, int(y.size),
            note="Total actual volume in this window is zero, so WAPE is undefined.",
        )
    return Metric("WAPE", float(np.sum(np.abs(y - f)) / volume * 100), int(y.size))


def bias(actual, predicted) -> Metric:
    """Mean error, signed. Positive means the model under-forecasts.

    Separated from MAE deliberately: two models with identical MAE, one
    unbiased and one consistently 10% low, have very different consequences for
    stock decisions, and an accuracy table that reports only magnitudes hides
    that completely.
    """
    y, f = _aligned(actual, predicted)
    if y.size == 0:
        return Metric("Bias", None, 0, note="No usable observations.")
    return Metric("Bias", float(np.mean(y - f)), int(y.size))


def mase(actual, predicted, training, season_length: int = 1) -> Metric:
    """Mean absolute scaled error: MAE divided by the in-sample naive MAE.

    The scaling denominator is the mean absolute error of the **seasonal naive**
    forecast on the *training* data - not the test data, which would leak. A
    value of 1 means the model matched seasonal naive; below 1 means it beat it.

    This is the measure that survives zero weeks, and it is the reason the
    results table can rank models on intermittent SKUs at all. See the module
    docstring on its provenance before citing it.
    """
    y, f = _aligned(actual, predicted)
    history = np.asarray(pd.Series(training).dropna().to_numpy(), dtype="float64")

    if y.size == 0:
        return Metric("MASE", None, 0, note="No usable observations.")
    if season_length < 1:
        raise ValueError(f"season_length must be at least 1; got {season_length}.")
    if history.size <= season_length:
        return Metric(
            "MASE", None, int(y.size),
            note=(
                f"The training window has {history.size} observations, too few to "
                f"scale against a seasonal naive of period {season_length}."
            ),
        )

    scale = float(np.mean(np.abs(history[season_length:] - history[:-season_length])))
    if scale <= MAPE_FLOOR:
        return Metric(
            "MASE", None, int(y.size),
            note=(
                "The seasonal naive forecast is exact on the training data "
                "(a constant or perfectly periodic series), so the scaling "
                "denominator is zero and MASE is undefined."
            ),
        )

    return Metric(
        "MASE", float(np.mean(np.abs(y - f)) / scale), int(y.size),
        note=f"Scaled against seasonal naive with period {season_length} on the training window.",
    )


def evaluate(
    actual,
    predicted,
    *,
    training=None,
    season_length: int = 1,
) -> dict[str, Metric]:
    """Every measure at once, keyed by name.

    `training` is needed only for MASE. When it is absent MASE is reported as
    unavailable with the reason, rather than being quietly omitted - an absent
    row in a results table reads as "the model failed", which is different.
    """
    results = {
        "MAE": mae(actual, predicted),
        "RMSE": rmse(actual, predicted),
        "MAPE": mape(actual, predicted),
        "sMAPE": smape(actual, predicted),
        "WAPE": wape(actual, predicted),
        "Bias": bias(actual, predicted),
    }
    if training is None:
        results["MASE"] = Metric(
            "MASE", None, 0,
            note="No training window supplied, so the scaling denominator is unknown.",
        )
    else:
        results["MASE"] = mase(actual, predicted, training, season_length)
    return results


def revenue_weighted_mape(per_series: pd.DataFrame) -> Metric:
    """The aggregate measure used by Auppakorn & Phumchusri (2022).

    They forecast seven product groups and combined the per-product MAPEs into
    one figure by weighting each product by its share of revenue, so that an
    error on a product carrying 22% of revenue counts more than the same
    percentage error on one carrying 7%. They call the result WAPE; this
    function keeps the paper's definition under a name that cannot be confused
    with the aggregate ratio in `wape`.

    `per_series` needs a `mape` column and a `weight` column. Weights are
    renormalised over the series that have a usable MAPE, so a product whose
    actuals were all zero does not silently shrink the total.
    """
    if per_series.empty or "mape" not in per_series or "weight" not in per_series:
        return Metric(
            "Revenue-weighted MAPE", None, 0,
            note="Needs a frame with 'mape' and 'weight' columns.",
        )

    frame = per_series.copy()
    frame["mape"] = pd.to_numeric(frame["mape"], errors="coerce")
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
    usable = frame[frame["mape"].notna() & (frame["weight"] > 0)]
    excluded = int(len(frame) - len(usable))

    total_weight = float(usable["weight"].sum())
    if usable.empty or total_weight <= 0:
        return Metric(
            "Revenue-weighted MAPE", None, 0, excluded,
            note="No series had both a usable MAPE and a positive weight.",
        )

    value = float((usable["mape"] * usable["weight"]).sum() / total_weight)
    note = (
        None if excluded == 0
        else f"{excluded} of {len(frame)} series had no usable MAPE and are excluded; "
             f"weights are renormalised over the rest."
    )
    return Metric("Revenue-weighted MAPE", value, int(len(usable)), excluded, note)
