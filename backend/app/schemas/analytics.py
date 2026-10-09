"""Request and response models for the analytics endpoints.

The filter set is a single Pydantic model injected with `Depends`, so every
analytics route accepts exactly the same filters and gains any new one without
being edited.

Responses are deliberately loose (`dict[str, Any]`). The analysis payloads are
nested, vary by analysis, and are already assembled by the pure core with keys
chosen for the frontend; re-declaring each shape here would add a second place
to keep in step for no validation benefit. The endpoints that return a fixed
shape - the KPI block - do get a typed model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, Query
from pydantic import BaseModel, Field, field_validator

from app.db.repositories.analytics import Filters


class AnalyticsFilters(BaseModel):
    """Shared query parameters.

    Lists arrive as repeated query parameters (`?regions=France&regions=EIRE`)
    or as one comma-separated value, because both are common in links people
    paste to each other.
    """

    date_from: datetime | None = Field(default=None, description="Inclusive start")
    date_to: datetime | None = Field(default=None, description="Inclusive end")
    regions: list[str] = Field(default_factory=list)
    product_codes: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    customer_type: Literal["all", "registered", "guest"] = "all"
    include_returns: bool = True

    @field_validator("regions", "product_codes", "categories", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                out.extend(
                    part.strip() for part in str(item).split(",") if part.strip()
                )
            return out
        return value

    def to_filters(self) -> Filters:
        return Filters(
            date_from=self.date_from,
            date_to=self.date_to,
            regions=self.regions,
            product_codes=self.product_codes,
            categories=self.categories,
            customer_type=self.customer_type,
            include_returns=self.include_returns,
        )


def filter_params(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    regions: list[str] = Query(default_factory=list),
    product_codes: list[str] = Query(default_factory=list),
    categories: list[str] = Query(default_factory=list),
    customer_type: Literal["all", "registered", "guest"] = Query(default="all"),
    include_returns: bool = Query(default=True),
) -> AnalyticsFilters:
    """Dependency that assembles the filters from the query string."""
    return AnalyticsFilters(
        date_from=date_from,
        date_to=date_to,
        regions=regions,
        product_codes=product_codes,
        categories=categories,
        customer_type=customer_type,
        include_returns=include_returns,
    )


CommonFilters = Annotated[AnalyticsFilters, Depends(filter_params)]


class KpiValues(BaseModel):
    gross_revenue: float
    returns_value: float
    net_revenue: float
    units: float
    orders: int | None = None
    average_order_value: float | None = None
    active_customers: int | None = None
    return_rate: float | None = None
    guest_revenue_share: float | None = None
    lines: int


class KpiComparison(BaseModel):
    comparable: bool
    note: str | None = None


class KpiResponse(BaseModel):
    values: KpiValues
    previous: dict[str, Any] | None = None
    growth: dict[str, float | None] | None = None
    comparison: KpiComparison


class FilterOptions(BaseModel):
    date_min: str | None = None
    date_max: str | None = None
    rows: int
    regions: list[dict[str, Any]]
    top_products: list[dict[str, Any]]
    categories: list[str]
    customer_types: list[str]
