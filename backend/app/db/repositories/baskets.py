"""The one query basket analysis needs: invoice lines, as products, in order.

A new module rather than three more functions in `analytics.py`, for a reason
that is about commits as much as about code: every file in this phase is new,
so nothing already committed changes, and a half-applied phase cannot leave the
repository in a state where an old file and a new one disagree. That has cost
this project a debugging session before.

**On importing `_conditions`.** It is private to `analytics.py` and imported
here anyway, deliberately. It builds the dataset, date, region, category and
outlier conditions that every analytics query shares. Writing a second copy of
that logic in this file would be the exact mistake `reconcile_invoices.py` made
with the non-product code list: a private helper reused is a smaller problem
than a public rule restated, because a copy drifts silently and produces
confident wrong numbers. If the sharing becomes awkward, the fix is to promote
`_conditions` to a public name, not to duplicate it.

**Division of labour, unchanged.** PostgreSQL filters and joins; pandas does
the analysis. This query returns one row per sale line rather than an
aggregate, because a basket *is* the set of its lines - there is nothing to
sum. That makes it the heaviest query in the project, so it selects four
columns and nothing else.
"""

from __future__ import annotations

import uuid

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.sales import Category, Product, SalesRecord
from app.db.repositories.analytics import Filters, _conditions, _frame


def basket_lines(
    session: Session,
    dataset_id: uuid.UUID,
    filters: Filters,
    *,
    include_returns: bool = False,
) -> pd.DataFrame:
    """Invoice lines with their product code, for basket construction.

    Returns `invoice_id`, `product_code`, `product_name`, `category`,
    `occurred_at` and `is_return`. Lines with no invoice or no product are
    dropped in SQL: a sale that belongs to no basket cannot contribute to a
    co-occurrence, and carrying the nulls into pandas only to drop them there
    would move megabytes for nothing.

    `category` is included because Jirapatsil & Phumchusri (2022) §3 mine at
    two levels - "Grouping the product by Category and SKU" - and a category
    run is the one that produces rules dense enough to act on when the SKU
    catalogue is long-tailed. The join is an outer one: a product with no
    category still belongs in its basket.

    Returns are excluded by default. `build_baskets` can also exclude them, and
    doing it here as well is intentional - this keeps the rows out of the
    transfer, and the pure function keeps the decision recorded in the results
    file.
    """
    conditions = _conditions(dataset_id, filters)
    if not include_returns:
        conditions.append(SalesRecord.is_return.is_(False))

    statement = (
        select(
            SalesRecord.invoice_id.label("invoice_id"),
            Product.product_code.label("product_code"),
            Product.name.label("product_name"),
            Category.name.label("category"),
            SalesRecord.occurred_at.label("occurred_at"),
            SalesRecord.is_return.label("is_return"),
        )
        .join(Product, SalesRecord.product_id == Product.id)
        .outerjoin(Category, Product.category_id == Category.id)
        .where(
            and_(*conditions),
            SalesRecord.invoice_id.is_not(None),
            SalesRecord.product_id.is_not(None),
        )
    )
    return _frame(session, statement)


def basket_line_count(
    session: Session, dataset_id: uuid.UUID, filters: Filters
) -> int:
    """How many rows `basket_lines` would return.

    Worth calling first. One line per sale is the largest result set in the
    project, and a runner that prints the number before fetching gives the
    operator the chance to narrow the date range rather than discover the size
    by waiting.
    """
    from sqlalchemy import func

    conditions = _conditions(dataset_id, filters)
    return int(
        session.execute(
            select(func.count())
            .select_from(SalesRecord)
            .where(
                and_(*conditions),
                SalesRecord.invoice_id.is_not(None),
                SalesRecord.product_id.is_not(None),
            )
        ).scalar_one()
    )
