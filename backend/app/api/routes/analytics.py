"""Analytics endpoints (architecture §9.2).

Every route is the same four lines: take the shared filters, call one service
function, return the result. Ownership and the "is this dataset ready" check
are dependencies, so a new endpoint cannot forget either.

All paths are nested under the dataset, because an analysis without a dataset
is meaningless and nesting makes the ownership check structural rather than
remembered.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app.api.deps import DbSession, OwnedDataset
from app.schemas.analytics import CommonFilters, FilterOptions, KpiResponse
from app.services import analytics_service

router = APIRouter(prefix="/datasets/{dataset_id}", tags=["analytics"])


@router.get("/filter-options", response_model=FilterOptions,
            summary="Date bounds, regions, categories and top products")
def filter_options(dataset: OwnedDataset, session: DbSession) -> dict[str, Any]:
    return analytics_service.get_filter_options(session, dataset)


@router.get("/analytics/kpis", response_model=KpiResponse,
            summary="Headline KPIs and the comparable previous period")
def kpis(dataset: OwnedDataset, session: DbSession, filters: CommonFilters) -> dict[str, Any]:
    return analytics_service.get_kpis(session, dataset, filters.to_filters())


@router.get("/analytics/trends", summary="Time series with moving average and growth")
def trends(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    granularity: Literal["day", "week", "month", "year"] = "week",
    ma_window: Annotated[int, Query(ge=1, le=52)] = 4,
) -> dict[str, Any]:
    return analytics_service.get_trends(
        session, dataset, filters.to_filters(), granularity, ma_window
    )


@router.get("/analytics/products", summary="Product performance, ranked")
def products(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    sort: Literal["gross_revenue", "net_revenue", "units", "orders"] = "gross_revenue",
    order: Literal["desc", "asc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    return analytics_service.get_breakdown(
        session, dataset, filters.to_filters(),
        dimension="product", sort=sort, descending=order == "desc", limit=limit,
    )


@router.get("/analytics/regions", summary="Region performance and concentration")
def regions(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    sort: Literal["gross_revenue", "net_revenue", "units", "orders"] = "gross_revenue",
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    return analytics_service.get_breakdown(
        session, dataset, filters.to_filters(),
        dimension="region", sort=sort, descending=True, limit=limit,
    )


@router.get("/analytics/categories", summary="Category performance (409 if unavailable)")
def categories(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    return analytics_service.get_breakdown(
        session, dataset, filters.to_filters(),
        dimension="category", sort="gross_revenue", descending=True, limit=limit,
    )


@router.get("/analytics/customers", summary="Customer revenue concentration")
def customers(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    return analytics_service.get_breakdown(
        session, dataset, filters.to_filters(),
        dimension="customer", sort="gross_revenue", descending=True, limit=limit,
    )


@router.get("/analytics/rfm", summary="Recency, Frequency, Monetary per customer")
def rfm(dataset: OwnedDataset, session: DbSession, filters: CommonFilters) -> dict[str, Any]:
    return analytics_service.get_rfm(session, dataset, filters.to_filters())


@router.get("/analytics/baskets", summary="Items per transaction, and what it implies")
def baskets(dataset: OwnedDataset, session: DbSession, filters: CommonFilters) -> dict[str, Any]:
    return analytics_service.get_baskets(session, dataset, filters.to_filters())


@router.get("/analytics/distributions", summary="Histogram, percentiles and outlier counts")
def distributions(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    field: Literal["revenue", "quantity", "unit_price", "order_value"] = "revenue",
    bins: Annotated[int, Query(ge=5, le=200)] = 40,
) -> dict[str, Any]:
    return analytics_service.get_distribution(
        session, dataset, filters.to_filters(), field, bins
    )


@router.get("/analytics/seasonality", summary="Calendar indices and weekly decomposition")
def seasonality(
    dataset: OwnedDataset, session: DbSession, filters: CommonFilters
) -> dict[str, Any]:
    return analytics_service.get_seasonality(session, dataset, filters.to_filters())


@router.get("/analytics/relationships", summary="Correlations and the price/quantity proxy")
def relationships(
    dataset: OwnedDataset, session: DbSession, filters: CommonFilters
) -> dict[str, Any]:
    return analytics_service.get_relationships(session, dataset, filters.to_filters())


@router.get("/analytics/statistics", summary="Descriptives and a non-parametric comparison")
def statistics(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    group: Literal["region", "quarter", "customer_type"] = "quarter",
    value: Literal["order_value", "revenue", "quantity", "unit_price"] = "order_value",
) -> dict[str, Any]:
    return analytics_service.get_statistics(
        session, dataset, filters.to_filters(), group=group, value=value
    )


@router.get("/analytics/features", summary="Entropy, mutual information and rank agreement")
def features(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    target: Literal["weekly_quantity"] = "weekly_quantity",
) -> dict[str, Any]:
    return analytics_service.get_features(
        session, dataset, filters.to_filters(), target=target
    )


@router.get("/analytics/series-profile", summary="ADI, CV squared and spectral entropy per SKU")
def series_profile(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    min_periods: Annotated[int, Query(ge=4, le=200)] = 26,
) -> dict[str, Any]:
    return analytics_service.get_series_profile(
        session, dataset, filters.to_filters(), min_periods=min_periods
    )


@router.get("/analytics/anomalies", summary="Unusual periods, with an explanation")
def anomalies(
    dataset: OwnedDataset,
    session: DbSession,
    filters: CommonFilters,
    granularity: Literal["day", "week", "month"] = "week",
) -> dict[str, Any]:
    return analytics_service.get_anomalies(
        session, dataset, filters.to_filters(), granularity=granularity
    )
