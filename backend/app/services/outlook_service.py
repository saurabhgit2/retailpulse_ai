"""The business outlook: fetch the weekly series, hand them to the pure core, cache.

Same shape as `analytics_service`: ask the repositories for aggregated data,
call `app.forecasting.outlook`, return plain data. The result is cached in the
analysis cache because a top-products outlook back-tests every product with
several methods, and the answer cannot change until the dataset does.

This is deliberately separate from `forecast_service`, which runs the RQ1
experiment. The experiment's protocol and stored results are untouched; the
outlook answers a different question with its own method.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.db.models.dataset import Dataset
from app.db.repositories import forecasts as repo
from app.db.repositories.analytics import Filters
from app.forecasting import outlook as core
from app.services.analytics_service import cached, ensure_ready

ANALYSIS_TYPE = "forecast_outlook"

MEASURES = {
    "net_revenue": "Net revenue",
    "net_units": "Units sold (net of returns)",
}

MAX_HORIZON = 26
MAX_PRODUCTS = 50


def get_outlook(
    session: Session, dataset: Dataset, *, horizon: int = 12, products: int = 20
) -> dict[str, Any]:
    """Revenue, units and top-product forecasts for the weeks after the data ends."""
    ensure_ready(dataset)
    if not 4 <= horizon <= MAX_HORIZON:
        raise ValidationFailed(f"Horizon must be between 4 and {MAX_HORIZON} weeks.")
    if not 0 <= products <= MAX_PRODUCTS:
        raise ValidationFailed(f"Products must be between 0 and {MAX_PRODUCTS}.")

    def compute() -> dict[str, Any]:
        return _compute(session, dataset, horizon=horizon, products=products)

    return cached(
        session, dataset, ANALYSIS_TYPE,
        {"version": core.OUTLOOK_VERSION, "horizon": horizon, "products": products},
        compute,
    )


def _compute(session: Session, dataset: Dataset, *, horizon: int, products: int) -> dict[str, Any]:
    date_max = pd.Timestamp(dataset.date_max) if dataset.date_max else None
    measures: dict[str, Any] = {}
    calendar: pd.DatetimeIndex | None = None
    closed: set[pd.Timestamp] = set()
    series_meta: dict[str, Any] = {}

    for measure, label in MEASURES.items():
        series, meta = repo.weekly_series(
            session, dataset.id, Filters(),
            granularity="week", value_column=measure, date_max=date_max,
        )
        if not meta.get("available"):
            measures[measure] = {"available": False, "label": label,
                                 "reason": meta.get("reason")}
            continue
        series.index = _naive(series.index)
        closed = {pd.Timestamp(p) for p in meta.get("gap_periods", [])}
        outcome = core.forecast_series(series, closed_periods=closed, horizon=horizon)
        measures[measure] = {"label": label, **outcome}
        if calendar is None:
            calendar = pd.DatetimeIndex(series.index)
            series_meta = {
                "first_period": meta.get("first_period"),
                "last_period": meta.get("last_period"),
                "periods": meta.get("periods"),
                "closed_weeks": meta.get("gap_periods", []),
                "incomplete_final_dropped": meta.get("incomplete_final_periods_dropped", 0),
            }

    product_block: dict[str, Any] = {"available": False, "rows": [], "limit": products}
    if products and calendar is not None:
        product_block = _products(session, dataset, calendar, closed, horizon, products)

    return {
        "available": any(m.get("available") for m in measures.values()),
        "version": core.OUTLOOK_VERSION,
        "horizon": horizon,
        "series": series_meta,
        "measures": measures,
        "products": product_block,
        "method_note": (
            "Each method is back-tested from several recent weeks: it forecasts the "
            "following weeks using only the data before them, and its forecast is "
            "compared with what actually happened. The method with the smallest "
            "typical error is used. Weeks the business did not trade are filled "
            "from their neighbours before fitting and are not scored."
        ),
    }


def _products(
    session: Session,
    dataset: Dataset,
    calendar: pd.DatetimeIndex,
    closed: set[pd.Timestamp],
    horizon: int,
    limit: int,
) -> dict[str, Any]:
    frame, ranked = repo.top_product_units(session, dataset.id, limit=limit)
    if frame.empty:
        return {"available": False, "rows": [], "limit": limit,
                "reason": "No product sales to forecast."}
    frame["period"] = _naive(pd.to_datetime(frame["period"]))
    frame = frame[frame["period"].isin(calendar)]
    # Keep revenue order: the biggest earners first.
    frame["series_id"] = pd.Categorical(frame["series_id"], categories=ranked, ordered=True)
    frame = frame.sort_values(["series_id", "period"])
    frame["series_id"] = frame["series_id"].astype(str)

    labels = repo.product_names(session, dataset.id, ranked)
    rows, skipped = core.product_outlook(
        frame, calendar, closed_periods=closed, horizon=horizon, labels=labels
    )
    ranked_count = len(ranked)
    shortfall = (
        f" {len(skipped)} of the top {ranked_count} launched too recently to "
        f"check a forecast against, so {'it is' if len(skipped) == 1 else 'they are'} "
        f"left out."
        if skipped else ""
    )
    return {
        "available": bool(rows),
        "limit": limit,
        "rows": rows,
        "skipped": [{"product_code": c, "description": labels.get(c)} for c in skipped],
        "note": (
            f"The products with the highest revenue, forecast in units net of returns. "
            f"Each product keeps the method that suited its own history best, starting "
            f"from its first sale, with one-off bulk weeks capped before fitting. Single "
            f"products swing far more than the business total, so expect wider bands "
            f"and lower confidence.{shortfall}"
        ),
    }


def _naive(index) -> pd.DatetimeIndex:
    """Drop any time zone so database weeks and pandas weeks compare equal."""
    index = pd.DatetimeIndex(index)
    return index.tz_localize(None) if index.tz is not None else index
