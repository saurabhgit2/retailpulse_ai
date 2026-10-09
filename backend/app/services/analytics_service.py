"""Analytics use cases: fetch aggregates, compute, cache (architecture §11.2).

Each function does the same three things - ask the repository for an aggregated
DataFrame, hand it to the pure core, return plain data - so the shape is easy
to follow and easy to extend in Phase 5.

Caching is applied only where it earns its keep. A KPI block is a single SQL
`SUM` and is faster to recompute than to look up; a feature analysis builds
lagged features over every SKU-week and is not. The expensive ones are listed
in `CACHED_ANALYSES`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics import anomalies as anomaly_core
from app.analytics import breakdowns as breakdown_core
from app.analytics import distributions as distribution_core
from app.analytics import features as feature_core
from app.analytics import kpis as kpi_core
from app.analytics import relationships as relationship_core
from app.analytics import rfm as rfm_core
from app.analytics import seasonality as seasonality_core
from app.analytics import series_profile as series_core
from app.analytics import statistics as statistics_core
from app.analytics import trends as trend_core
from app.core.errors import Conflict, ValidationFailed
from app.db.models.analysis import AnalysisResult
from app.db.models.dataset import Dataset
from app.db.repositories import analytics as repo
from app.db.repositories.analytics import Filters

logger = logging.getLogger(__name__)

CACHED_ANALYSES = frozenset(
    {"statistics", "features", "series_profile", "seasonality", "relationships",
     "distributions", "anomalies", "rfm", "baskets"}
)

# How many SKUs the per-series analyses look at. The long tail of a retail
# catalogue is mostly single sales, and profiling 4,000 noisy series costs time
# without changing a conclusion. The cut-off is reported in the response so the
# number is never mistaken for "all products".
DEFAULT_TOP_PRODUCTS = 300


def ensure_ready(dataset: Dataset) -> None:
    """Analytics only make sense once the pipeline has stored cleaned rows."""
    if dataset.status != "ready":
        raise Conflict(
            "This dataset has not finished processing yet.",
            code="DATASET_NOT_READY",
            details={"status": dataset.status},
        )


def require_capability(dataset: Dataset, capability: str) -> None:
    """Refuse an analysis the dataset's columns cannot support.

    The frontend already hides these, but a hidden control is not a check: the
    endpoint is still reachable, so the rule is enforced here too.
    """
    capabilities = {c["key"]: c.get("enabled") for c in (dataset.capabilities or [])}
    if capabilities.get(capability) is False:
        raise Conflict(
            f"This dataset does not have the columns needed for {capability.replace('_', ' ')}.",
            code="CAPABILITY_UNAVAILABLE",
            details={"capability": capability},
        )


def params_hash(payload: dict[str, Any]) -> str:
    """Stable hash of filters and parameters.

    `sort_keys` is what makes it stable: without it, two identical filter sets
    could serialise differently and miss each other in the cache.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cached(
    session: Session,
    dataset: Dataset,
    analysis_type: str,
    key_payload: dict[str, Any],
    compute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Return a stored result, or compute, store and return one."""
    if analysis_type not in CACHED_ANALYSES:
        return compute()

    digest = params_hash(key_payload)
    version = dataset.pipeline_version or "unknown"

    stored = session.execute(
        select(AnalysisResult).where(
            AnalysisResult.dataset_id == dataset.id,
            AnalysisResult.analysis_type == analysis_type,
            AnalysisResult.params_hash == digest,
            AnalysisResult.pipeline_version == version,
        )
    ).scalar_one_or_none()

    if stored is not None:
        result = dict(stored.result)
        result["_cache"] = {"hit": True, "computed_ms": stored.computed_ms,
                            "computed_at": stored.created_at.isoformat()}
        return result

    started = time.perf_counter()
    result = compute()
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    entry = AnalysisResult(
        dataset_id=dataset.id,
        analysis_type=analysis_type,
        params_hash=digest,
        pipeline_version=version,
        result=result,
        computed_ms=elapsed_ms,
    )
    session.add(entry)
    try:
        session.flush()
    except IntegrityError:
        # Two requests computed the same analysis at once. Harmless: the other
        # one won, and its result is equivalent.
        session.rollback()
        logger.info("Analysis %s for %s was cached concurrently", analysis_type, dataset.id)

    result = dict(result)
    result["_cache"] = {"hit": False, "computed_ms": elapsed_ms}
    return result


# --- the analyses -----------------------------------------------------------


def get_kpis(session: Session, dataset: Dataset, filters: Filters) -> dict[str, Any]:
    ensure_ready(dataset)
    current = repo.totals(session, dataset.id, filters)

    previous_totals = None
    comparable = False
    note = None

    if filters.date_from and filters.date_to:
        span = filters.date_to - filters.date_from
        previous = Filters(**{**filters.__dict__, "date_from": filters.date_from - span,
                              "date_to": filters.date_from})
        previous_totals = repo.totals(session, dataset.id, previous)
        data_min = dataset.date_min
        if data_min is not None and previous.date_from < data_min:
            note = (
                "The comparison period starts before the data does, so growth "
                "would compare a full period against a partial one."
            )
        else:
            comparable = True
    else:
        note = "Select a date range to compare against the preceding period."

    return kpi_core.build_kpis(
        current, previous_totals, periods_comparable=comparable, comparison_note=note
    )


def get_trends(
    session: Session, dataset: Dataset, filters: Filters, granularity: str, ma_window: int
) -> dict[str, Any]:
    ensure_ready(dataset)
    if granularity not in trend_core.GRANULARITIES:
        raise ValidationFailed(
            f"granularity must be one of {', '.join(trend_core.GRANULARITIES)}.",
            code="INVALID_GRANULARITY",
        )
    frame = repo.trend(session, dataset.id, filters, granularity)
    return trend_core.build_trend(
        frame, granularity, data_max=dataset.date_max, ma_window=ma_window
    )


def get_breakdown(
    session: Session,
    dataset: Dataset,
    filters: Filters,
    *,
    dimension: str,
    sort: str,
    descending: bool,
    limit: int,
) -> dict[str, Any]:
    ensure_ready(dataset)
    if dimension == "category":
        require_capability(dataset, "category_analysis")
    if dimension == "customer":
        require_capability(dataset, "segmentation")

    frame = repo.breakdown(session, dataset.id, filters, dimension)
    key = {"product": "product_code", "region": "region",
           "category": "category", "customer": "customer"}[dimension]
    return breakdown_core.rank_breakdown(
        frame, key=key, sort=sort, descending=descending, limit=limit,
        label_column="label" if dimension == "product" else None,
    )


def get_distribution(
    session: Session, dataset: Dataset, filters: Filters, field_name: str, bins: int
) -> dict[str, Any]:
    ensure_ready(dataset)
    if field_name not in repo.DISTRIBUTION_FIELDS:
        raise ValidationFailed(
            f"field must be one of {', '.join(repo.DISTRIBUTION_FIELDS)}.",
            code="INVALID_FIELD",
        )

    def compute() -> dict[str, Any]:
        values = repo.distribution_values(session, dataset.id, filters, field_name)
        return distribution_core.describe_distribution(values, bins=bins, field=field_name)

    return cached(
        session, dataset, "distributions",
        {"filters": filters.cache_key(), "field": field_name, "bins": bins}, compute,
    )


def get_seasonality(session: Session, dataset: Dataset, filters: Filters) -> dict[str, Any]:
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        daily = repo.daily_with_hour(session, dataset.id, filters)
        weekly = repo.trend(session, dataset.id, filters, "week")
        return {
            "calendar": seasonality_core.calendar_indices(daily),
            "decomposition": seasonality_core.weekly_seasonality(weekly),
        }

    return cached(
        session, dataset, "seasonality", {"filters": filters.cache_key()}, compute
    )


def get_relationships(session: Session, dataset: Dataset, filters: Filters) -> dict[str, Any]:
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        periods = repo.product_periods(
            session, dataset.id, filters, limit_products=DEFAULT_TOP_PRODUCTS
        )
        correlation_columns = [
            c for c in ("units", "gross_revenue", "avg_unit_price", "distinct_customers")
            if c in periods.columns
        ]
        return {
            "top_products_analysed": DEFAULT_TOP_PRODUCTS,
            "correlations": relationship_core.correlation_matrix(periods, correlation_columns),
            "price_quantity": relationship_core.price_quantity_relationship(periods),
            "discount_proxy": relationship_core.discount_proxy(periods),
        }

    return cached(
        session, dataset, "relationships", {"filters": filters.cache_key()}, compute
    )


def get_statistics(
    session: Session, dataset: Dataset, filters: Filters, *, group: str, value: str
) -> dict[str, Any]:
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        frame = repo.group_values(session, dataset.id, filters, group=group, value=value)
        if frame.empty:
            return {"value": value, "group": group, "descriptive": None, "comparison": None}
        return {
            "value": value,
            "group": group,
            "descriptive": statistics_core.describe(frame["value"]),
            "normality": statistics_core.normality_check(frame["value"]),
            "comparison": statistics_core.compare_groups(
                frame["value"], frame["group"], label=value
            ),
            "stationarity": {
                "available": False,
                "reason": (
                    "ADF and KPSS arrive with the forecasting engine in Phase 5, "
                    "where differencing decisions are actually made."
                ),
            },
        }

    return cached(
        session, dataset, "statistics",
        {"filters": filters.cache_key(), "group": group, "value": value}, compute,
    )


def get_features(
    session: Session, dataset: Dataset, filters: Filters, *, target: str
) -> dict[str, Any]:
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        periods = repo.product_periods(
            session, dataset.id, filters, limit_products=DEFAULT_TOP_PRODUCTS
        )
        if periods.empty:
            return {"available": False, "reason": "No data in range."}
        table = feature_core.build_feature_table(periods, target_column="units")
        result = feature_core.score_features(table, target_column="units")
        result["top_products_analysed"] = DEFAULT_TOP_PRODUCTS
        result["target_requested"] = target
        return result

    return cached(
        session, dataset, "features",
        {"filters": filters.cache_key(), "target": target}, compute,
    )


def get_series_profile(
    session: Session, dataset: Dataset, filters: Filters, *, min_periods: int
) -> dict[str, Any]:
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        periods = repo.product_periods(
            session, dataset.id, filters, limit_products=DEFAULT_TOP_PRODUCTS
        )
        result = series_core.profile_many(periods, min_periods=min_periods)
        result["top_products_analysed"] = DEFAULT_TOP_PRODUCTS
        return result

    return cached(
        session, dataset, "series_profile",
        {"filters": filters.cache_key(), "min_periods": min_periods}, compute,
    )


def get_anomalies(
    session: Session, dataset: Dataset, filters: Filters, *, granularity: str
) -> dict[str, Any]:
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        frame = repo.trend(session, dataset.id, filters, granularity)
        period = {"day": 7, "week": 52, "month": 12, "year": 1}[granularity]
        return anomaly_core.detect_anomalies(frame, period=period)

    return cached(
        session, dataset, "anomalies",
        {"filters": filters.cache_key(), "granularity": granularity}, compute,
    )


def get_rfm(session: Session, dataset: Dataset, filters: Filters) -> dict[str, Any]:
    """Recency, Frequency, Monetary per customer (Chen, Sain & Guo 2012)."""
    ensure_ready(dataset)
    require_capability(dataset, "segmentation")

    def compute() -> dict[str, Any]:
        customers = repo.customer_rfm(session, dataset.id, filters)
        result = rfm_core.build_rfm(customers)
        if not result.get("available"):
            return result

        # How much of the business RFM cannot see. Reporting it next to the
        # segments stops a reader taking the customer view for the whole view.
        guests = repo.guest_summary(session, dataset.id, filters)
        identified_revenue = sum(segment["monetary"] for segment in result["segments"])
        total = identified_revenue + guests["guest_revenue"]
        result["coverage"] = {
            **guests,
            "identified_revenue": identified_revenue,
            "guest_revenue_share": (
                guests["guest_revenue"] / total if total else None
            ),
        }
        return result

    return cached(session, dataset, "rfm", {"filters": filters.cache_key()}, compute)


def get_baskets(session: Session, dataset: Dataset, filters: Filters) -> dict[str, Any]:
    """Basket size per invoice.

    Chen et al. (2012) read 18.3 distinct items per transaction as evidence
    that the retailer's customers are mostly organisations rather than
    individuals - a conclusion drawn from one simple aggregate.
    """
    ensure_ready(dataset)

    def compute() -> dict[str, Any]:
        baskets = repo.basket_sizes(session, dataset.id, filters)
        if baskets.empty:
            return {"available": False, "reason": "No invoices in range."}

        items = distribution_core.describe_distribution(
            baskets["distinct_items"], field="distinct_items_per_invoice"
        )
        values = distribution_core.describe_distribution(
            baskets["revenue"], field="order_value"
        )
        mean_items = items["summary"]["mean"]
        return {
            "available": True,
            "invoices": int(len(baskets)),
            "distinct_items_per_invoice": items,
            "order_value": values,
            "interpretation": (
                f"{mean_items:.1f} distinct items per transaction on average. "
                "Chen, Sain and Guo (2012) read a figure of this size on the same "
                "retailer as evidence that the customers are largely organisations "
                "rather than individual consumers."
                if mean_items >= 10 else
                f"{mean_items:.1f} distinct items per transaction on average, which "
                "is consistent with individual consumers rather than wholesale buyers."
            ),
        }

    return cached(session, dataset, "baskets", {"filters": filters.cache_key()}, compute)


def get_filter_options(session: Session, dataset: Dataset) -> dict[str, Any]:
    ensure_ready(dataset)
    return repo.filter_options(session, dataset.id)


def invalidate(session: Session, dataset_id: uuid.UUID) -> int:
    """Drop every cached analysis for a dataset. Called when it is reprocessed."""
    rows = session.query(AnalysisResult).filter(
        AnalysisResult.dataset_id == dataset_id
    ).delete(synchronize_session=False)
    return int(rows or 0)
