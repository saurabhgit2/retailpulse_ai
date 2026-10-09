"""Aggregation SQL for the analytics endpoints (architecture §11.2).

The division of labour: **PostgreSQL aggregates, pandas analyses.** A million
sales rows become a few hundred weekly totals in the database, and only those
cross into Python. Pulling a million rows into pandas to sum them would be slow,
memory-hungry, and would waste the composite index that was built for exactly
this access pattern.

Every query here starts with `dataset_id` and then a date range, which is the
leading edge of `ix_sales_records_dataset_id_occurred_at`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime

import pandas as pd
from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.analytics.kpis import PeriodTotals
from app.db.models.sales import Category, Customer, Product, SalesRecord

GRANULARITY_SQL = {"day": "day", "week": "week", "month": "month", "year": "year"}

# Which numeric column each distribution refers to.
DISTRIBUTION_FIELDS = ("revenue", "quantity", "unit_price", "order_value")


@dataclass
class Filters:
    """The filter set every analytics endpoint shares."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    regions: list[str] = field(default_factory=list)
    product_codes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    customer_type: str = "all"          # all | registered | guest
    include_returns: bool = True

    def cache_key(self) -> dict[str, object]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "regions": sorted(self.regions),
            "product_codes": sorted(self.product_codes),
            "categories": sorted(self.categories),
            "customer_type": self.customer_type,
            "include_returns": self.include_returns,
        }


def _conditions(dataset_id: uuid.UUID, filters: Filters) -> list:
    """WHERE clauses, dataset first so the composite index is usable."""
    clauses = [SalesRecord.dataset_id == dataset_id]

    if filters.date_from is not None:
        clauses.append(SalesRecord.occurred_at >= filters.date_from)
    if filters.date_to is not None:
        clauses.append(SalesRecord.occurred_at <= filters.date_to)
    if filters.regions:
        clauses.append(SalesRecord.region.in_(filters.regions))
    if filters.customer_type == "registered":
        clauses.append(SalesRecord.customer_id.is_not(None))
    elif filters.customer_type == "guest":
        clauses.append(SalesRecord.customer_id.is_(None))
    if not filters.include_returns:
        clauses.append(SalesRecord.is_return.is_(False))

    if filters.product_codes:
        product_ids = (
            select(Product.id)
            .where(Product.dataset_id == dataset_id, Product.product_code.in_(filters.product_codes))
            .scalar_subquery()
        )
        clauses.append(SalesRecord.product_id.in_(product_ids))

    if filters.categories:
        category_product_ids = (
            select(Product.id)
            .join(Category, Product.category_id == Category.id)
            .where(Product.dataset_id == dataset_id, Category.name.in_(filters.categories))
            .scalar_subquery()
        )
        clauses.append(SalesRecord.product_id.in_(category_product_ids))

    return clauses


# Revenue split into the two halves the KPI dictionary needs. `is_return` is a
# flag rather than a filter because net revenue needs both halves (§12.4).
_GROSS = func.coalesce(
    func.sum(case((SalesRecord.is_return.is_(False), SalesRecord.revenue), else_=0)), 0
)
_RETURNS = func.abs(
    func.coalesce(
        func.sum(case((SalesRecord.is_return.is_(True), SalesRecord.revenue), else_=0)), 0
    )
)
_UNITS = func.coalesce(
    func.sum(case((SalesRecord.is_return.is_(False), SalesRecord.quantity), else_=0)), 0
)
_ORDERS = func.count(func.distinct(
    case((SalesRecord.is_return.is_(False), SalesRecord.invoice_id))
))
_GUEST_REVENUE = func.coalesce(
    func.sum(
        case(
            (and_(SalesRecord.is_return.is_(False), SalesRecord.customer_id.is_(None)),
             SalesRecord.revenue),
            else_=0,
        )
    ),
    0,
)


def _frame(session: Session, statement: Select) -> pd.DataFrame:
    """Run a query and return a DataFrame with plain Python numbers.

    PostgreSQL NUMERIC arrives as `decimal.Decimal`, which is correct for money
    but is not JSON serialisable and is not reliably converted by
    `pd.to_numeric` across pandas versions. Converting here means the pure
    analytics core and every response handle ordinary floats, and no module
    downstream has to know the database uses NUMERIC.
    """
    frame = pd.DataFrame(session.execute(statement).mappings().all())
    for column in frame.columns:
        if frame[column].dtype == "object" and frame[column].map(
            lambda value: isinstance(value, Decimal)
        ).any():
            frame[column] = frame[column].map(
                lambda value: float(value) if isinstance(value, Decimal) else value
            ).astype("float64")
    return frame


def totals(session: Session, dataset_id: uuid.UUID, filters: Filters) -> PeriodTotals:
    """One row of sums: everything the KPI block needs."""
    statement = select(
        _GROSS.label("gross_revenue"),
        _RETURNS.label("returns_value"),
        _UNITS.label("units"),
        _ORDERS.label("orders"),
        func.count(func.distinct(SalesRecord.customer_id)).label("active_customers"),
        _GUEST_REVENUE.label("guest_revenue"),
        func.count().label("lines"),
    ).where(and_(*_conditions(dataset_id, filters)))

    row = session.execute(statement).mappings().one()
    return PeriodTotals(
        gross_revenue=float(row["gross_revenue"] or 0),
        returns_value=float(row["returns_value"] or 0),
        units=float(row["units"] or 0),
        orders=int(row["orders"] or 0),
        active_customers=int(row["active_customers"] or 0),
        guest_revenue=float(row["guest_revenue"] or 0),
        lines=int(row["lines"] or 0),
    )


def trend(
    session: Session, dataset_id: uuid.UUID, filters: Filters, granularity: str
) -> pd.DataFrame:
    """Totals per period. `date_trunc` buckets weeks from Monday, which is what
    the pandas side assumes too (`W-MON`)."""
    unit = GRANULARITY_SQL[granularity]
    bucket = func.date_trunc(unit, SalesRecord.occurred_at).label("period")

    statement = (
        select(
            bucket,
            _GROSS.label("gross_revenue"),
            _RETURNS.label("returns_value"),
            _UNITS.label("units"),
            _ORDERS.label("orders"),
            func.count(func.distinct(SalesRecord.customer_id)).label("active_customers"),
        )
        .where(and_(*_conditions(dataset_id, filters)))
        .group_by(bucket)
        .order_by(bucket)
    )
    frame = _frame(session, statement)
    if not frame.empty:
        frame["net_revenue"] = frame["gross_revenue"] - frame["returns_value"]
    return frame


def breakdown(
    session: Session, dataset_id: uuid.UUID, filters: Filters, dimension: str
) -> pd.DataFrame:
    """Totals per product, region or category."""
    conditions = _conditions(dataset_id, filters)
    base = select(
        _GROSS.label("gross_revenue"),
        _RETURNS.label("returns_value"),
        _UNITS.label("units"),
        _ORDERS.label("orders"),
    )

    if dimension == "product":
        statement = (
            base.add_columns(
                Product.product_code.label("product_code"), Product.name.label("label")
            )
            .join(Product, SalesRecord.product_id == Product.id)
            .where(and_(*conditions))
            .group_by(Product.product_code, Product.name)
        )
    elif dimension == "region":
        statement = (
            base.add_columns(SalesRecord.region.label("region"))
            .where(and_(*conditions), SalesRecord.region.is_not(None))
            .group_by(SalesRecord.region)
        )
    elif dimension == "category":
        statement = (
            base.add_columns(Category.name.label("category"))
            .join(Product, SalesRecord.product_id == Product.id)
            .join(Category, Product.category_id == Category.id)
            .where(and_(*conditions))
            .group_by(Category.name)
        )
    elif dimension == "customer":
        statement = (
            base.add_columns(Customer.external_id.label("customer"))
            .join(Customer, SalesRecord.customer_id == Customer.id)
            .where(and_(*conditions))
            .group_by(Customer.external_id)
        )
    else:
        raise ValueError(f"Unknown breakdown dimension: {dimension}")

    frame = _frame(session, statement)
    if not frame.empty:
        frame["net_revenue"] = frame["gross_revenue"] - frame["returns_value"]
    return frame


def distribution_values(
    session: Session, dataset_id: uuid.UUID, filters: Filters, field_name: str
) -> pd.Series:
    """The raw column a histogram is built from.

    This is the one place that moves a column of row-level values into Python
    (about 8 MB per million rows). Quantiles, skewness and a histogram all need
    the values themselves; the result is cached so the cost is paid once per
    filter combination.
    """
    conditions = _conditions(dataset_id, filters)

    if field_name == "order_value":
        # An order's value is the sum of its lines, so this aggregates first.
        statement = (
            select(func.sum(SalesRecord.revenue).label("value"))
            .where(and_(*conditions), SalesRecord.is_return.is_(False))
            .group_by(SalesRecord.invoice_id)
        )
    else:
        column = {
            "revenue": SalesRecord.revenue,
            "quantity": SalesRecord.quantity,
            "unit_price": SalesRecord.unit_price,
        }[field_name]
        statement = (
            select(column.label("value"))
            .where(and_(*conditions), SalesRecord.is_return.is_(False), column.is_not(None))
        )

    rows = session.execute(statement).scalars().all()
    return pd.Series(rows, dtype="float64")


def daily_with_hour(
    session: Session, dataset_id: uuid.UUID, filters: Filters
) -> pd.DataFrame:
    """Daily totals plus an hour column, for the calendar indices."""
    day = func.date_trunc("day", SalesRecord.occurred_at).label("period")
    hour = func.extract("hour", SalesRecord.occurred_at).label("hour")
    statement = (
        select(day, hour, _GROSS.label("gross_revenue"), _UNITS.label("units"))
        .where(and_(*_conditions(dataset_id, filters)))
        .group_by(day, hour)
        .order_by(day)
    )
    frame = _frame(session, statement)
    if not frame.empty:
        frame["hour"] = pd.to_numeric(frame["hour"], errors="coerce")
    return frame


def product_periods(
    session: Session,
    dataset_id: uuid.UUID,
    filters: Filters,
    *,
    granularity: str = "week",
    limit_products: int | None = None,
) -> pd.DataFrame:
    """One row per product per period: the input for series profiles, feature
    analysis and the price/quantity relationship."""
    unit = GRANULARITY_SQL[granularity]
    bucket = func.date_trunc(unit, SalesRecord.occurred_at).label("period")
    conditions = list(_conditions(dataset_id, filters))

    if limit_products:
        # Analysing every SKU is expensive and the long tail is mostly noise,
        # so the biggest sellers by revenue come first. The cut-off is reported.
        top = (
            select(SalesRecord.product_id)
            .where(and_(*conditions), SalesRecord.is_return.is_(False))
            .group_by(SalesRecord.product_id)
            .order_by(func.sum(SalesRecord.revenue).desc())
            .limit(limit_products)
            .scalar_subquery()
        )
        conditions.append(SalesRecord.product_id.in_(top))

    statement = (
        select(
            Product.product_code.label("product_code"),
            bucket,
            _UNITS.label("units"),
            _GROSS.label("gross_revenue"),
            func.avg(SalesRecord.unit_price).label("avg_unit_price"),
            func.count(func.distinct(SalesRecord.customer_id)).label("distinct_customers"),
            func.count(func.distinct(SalesRecord.region)).label("distinct_regions"),
        )
        .join(Product, SalesRecord.product_id == Product.id)
        .where(and_(*conditions))
        .group_by(Product.product_code, bucket)
        .order_by(Product.product_code, bucket)
    )
    return _frame(session, statement)


def group_values(
    session: Session,
    dataset_id: uuid.UUID,
    filters: Filters,
    *,
    group: str,
    value: str = "order_value",
) -> pd.DataFrame:
    """Values with a group label, for the non-parametric comparisons.

    `group` is "region" or "quarter"; "quarter" supports the Q4-versus-the-rest
    comparison the architecture names.
    """
    conditions = _conditions(dataset_id, filters)

    if group == "region":
        label = SalesRecord.region.label("group")
    elif group == "quarter":
        label = func.concat("Q", func.extract("quarter", SalesRecord.occurred_at)).label("group")
    elif group == "customer_type":
        label = case(
            (SalesRecord.customer_id.is_(None), "guest"), else_="registered"
        ).label("group")
    else:
        raise ValueError(f"Unknown grouping: {group}")

    if value == "order_value":
        statement = (
            select(label, func.sum(SalesRecord.revenue).label("value"))
            .where(and_(*conditions), SalesRecord.is_return.is_(False))
            .group_by(label, SalesRecord.invoice_id)
        )
    else:
        column = {"revenue": SalesRecord.revenue, "quantity": SalesRecord.quantity,
                  "unit_price": SalesRecord.unit_price}[value]
        statement = (
            select(label, column.label("value"))
            .where(and_(*conditions), SalesRecord.is_return.is_(False), column.is_not(None))
        )

    return _frame(session, statement)


def filter_options(session: Session, dataset_id: uuid.UUID) -> dict[str, object]:
    """Date bounds, regions, categories and top products for the filter UI."""
    bounds = session.execute(
        select(
            func.min(SalesRecord.occurred_at).label("date_min"),
            func.max(SalesRecord.occurred_at).label("date_max"),
            func.count().label("rows"),
        ).where(SalesRecord.dataset_id == dataset_id)
    ).mappings().one()

    regions = session.execute(
        select(SalesRecord.region, func.sum(SalesRecord.revenue).label("revenue"))
        .where(SalesRecord.dataset_id == dataset_id, SalesRecord.region.is_not(None))
        .group_by(SalesRecord.region)
        .order_by(func.sum(SalesRecord.revenue).desc())
    ).mappings().all()

    products = session.execute(
        select(
            Product.product_code,
            Product.name,
            func.sum(SalesRecord.revenue).label("revenue"),
        )
        .join(SalesRecord, SalesRecord.product_id == Product.id)
        .where(SalesRecord.dataset_id == dataset_id)
        .group_by(Product.product_code, Product.name)
        .order_by(func.sum(SalesRecord.revenue).desc())
        .limit(100)
    ).mappings().all()

    categories = session.execute(
        select(Category.name)
        .where(Category.dataset_id == dataset_id)
        .order_by(Category.name)
    ).scalars().all()

    return {
        "date_min": bounds["date_min"].isoformat() if bounds["date_min"] else None,
        "date_max": bounds["date_max"].isoformat() if bounds["date_max"] else None,
        "rows": int(bounds["rows"] or 0),
        "regions": [
            {"value": row["region"], "revenue": float(row["revenue"] or 0)} for row in regions
        ],
        "top_products": [
            {
                "value": row["product_code"],
                "label": row["name"],
                "revenue": float(row["revenue"] or 0),
            }
            for row in products
        ],
        "categories": list(categories),
        "customer_types": ["all", "registered", "guest"],
    }


def delete_cached_analyses(session: Session, dataset_id: uuid.UUID) -> int:
    """Drop every cached analysis for a dataset.

    Called when a dataset is reprocessed. The cache key covers the filters and
    the pipeline version but not the data itself, so re-running the same
    pipeline over a corrected file would otherwise serve the old numbers.
    """
    from app.db.models.analysis import AnalysisResult

    result = session.execute(
        AnalysisResult.__table__.delete().where(AnalysisResult.dataset_id == dataset_id)
    )
    return int(result.rowcount or 0)


def customer_rfm(session: Session, dataset_id: uuid.UUID, filters: Filters) -> pd.DataFrame:
    """One row per identified customer: the input for RFM (Chen et al. 2012).

    Guests have no `customer_id` and are excluded here by construction. The
    revenue they represent is reported separately by `guest_summary`, because a
    segmentation that silently drops a quarter of revenue would mislead.
    """
    conditions = _conditions(dataset_id, filters)

    statement = (
        select(
            Customer.external_id.label("customer"),
            func.min(SalesRecord.occurred_at).label("first_purchase"),
            func.max(SalesRecord.occurred_at).label("last_purchase"),
            _ORDERS.label("frequency"),
            _GROSS.label("monetary_gross"),
            _RETURNS.label("returns_value"),
            _UNITS.label("units"),
            func.count().label("lines"),
        )
        .join(Customer, SalesRecord.customer_id == Customer.id)
        .where(and_(*conditions))
        .group_by(Customer.external_id)
    )
    return _frame(session, statement)


def guest_summary(session: Session, dataset_id: uuid.UUID, filters: Filters) -> dict[str, float]:
    """How much of the business RFM cannot see."""
    conditions = _conditions(dataset_id, filters)
    row = session.execute(
        select(
            _GROSS.label("gross_revenue"),
            func.count().label("lines"),
        ).where(and_(*conditions), SalesRecord.customer_id.is_(None))
    ).mappings().one()
    return {
        "guest_revenue": float(row["gross_revenue"] or 0),
        "guest_lines": int(row["lines"] or 0),
    }


def basket_sizes(session: Session, dataset_id: uuid.UUID, filters: Filters) -> pd.DataFrame:
    """Distinct items per invoice.

    Chen et al. (2012) use this one number - 18.3 items per transaction - to
    argue that the customers are mostly organisations rather than individuals.
    It is a cheap figure with a real interpretation behind it.
    """
    conditions = _conditions(dataset_id, filters)
    statement = (
        select(
            SalesRecord.invoice_id.label("invoice_id"),
            func.count(func.distinct(SalesRecord.product_id)).label("distinct_items"),
            func.sum(SalesRecord.quantity).label("units"),
            func.sum(SalesRecord.revenue).label("revenue"),
        )
        .where(and_(*conditions), SalesRecord.is_return.is_(False))
        .group_by(SalesRecord.invoice_id)
    )
    return _frame(session, statement)
