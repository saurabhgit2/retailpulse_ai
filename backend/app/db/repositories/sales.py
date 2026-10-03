"""Storing a cleaned dataset.

The interesting part is how a million rows get in. Inserting them one at a time
through the ORM takes minutes to hours: each row is a round trip. PostgreSQL's
COPY streams them in one go and is typically orders of magnitude faster
(architecture §11.1).

So this module is deliberately split:

* products, customers and categories - a few thousand rows - go through normal
  bulk inserts, because we need their generated IDs back;
* sales_records - a million rows - go through COPY.
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.sales import Category, Customer, Product, SalesRecord

logger = logging.getLogger(__name__)

COPY_CHUNK_ROWS = 100_000

SALES_COPY_COLUMNS = [
    "dataset_id", "invoice_id", "occurred_at", "product_id", "customer_id",
    "region", "quantity", "unit_price", "revenue", "is_return", "is_outlier",
]


def delete_dataset_records(session: Session, dataset_id: uuid.UUID) -> None:
    """Remove everything derived from a dataset so it can be reprocessed.

    Order matters: sales rows reference products and customers.
    """
    session.execute(delete(SalesRecord).where(SalesRecord.dataset_id == dataset_id))
    session.execute(delete(Product).where(Product.dataset_id == dataset_id))
    session.execute(delete(Customer).where(Customer.dataset_id == dataset_id))
    session.execute(delete(Category).where(Category.dataset_id == dataset_id))
    session.flush()


def _insert_categories(session: Session, dataset_id: uuid.UUID, frame: pd.DataFrame) -> dict[str, int]:
    if "category" not in frame or frame["category"].isna().all():
        return {}
    names = sorted({str(value) for value in frame["category"].dropna().unique()})
    session.execute(
        Category.__table__.insert(),
        [{"dataset_id": dataset_id, "name": name, "source": "mapped"} for name in names],
    )
    session.flush()
    rows = session.execute(
        select(Category.name, Category.id).where(Category.dataset_id == dataset_id)
    ).all()
    return {name: identifier for name, identifier in rows}


def _insert_products(
    session: Session,
    dataset_id: uuid.UUID,
    frame: pd.DataFrame,
    variants: dict[str, int],
    category_ids: dict[str, int],
) -> dict[str, int]:
    if "product_code" not in frame or frame["product_code"].isna().all():
        return {}

    products = (
        frame.dropna(subset=["product_code"])
        .drop_duplicates(subset=["product_code"])[["product_code", "product_name", "category"]]
    )
    payload: list[dict[str, Any]] = []
    for row in products.itertuples(index=False):
        code = str(row.product_code)
        category = None if pd.isna(row.category) else category_ids.get(str(row.category))
        payload.append(
            {
                "dataset_id": dataset_id,
                "product_code": code,
                "name": None if pd.isna(row.product_name) else str(row.product_name)[:255],
                "category_id": category,
                "description_variants": int(variants.get(code, 1)),
            }
        )

    session.execute(Product.__table__.insert(), payload)
    session.flush()
    rows = session.execute(
        select(Product.product_code, Product.id).where(Product.dataset_id == dataset_id)
    ).all()
    return {code: identifier for code, identifier in rows}


def _insert_customers(session: Session, dataset_id: uuid.UUID, frame: pd.DataFrame) -> dict[str, int]:
    if "customer_id" not in frame or frame["customer_id"].isna().all():
        return {}
    externals = sorted({str(value) for value in frame["customer_id"].dropna().unique()})
    session.execute(
        Customer.__table__.insert(),
        [{"dataset_id": dataset_id, "external_id": external} for external in externals],
    )
    session.flush()
    rows = session.execute(
        select(Customer.external_id, Customer.id).where(Customer.dataset_id == dataset_id)
    ).all()
    return {external: identifier for external, identifier in rows}


def _copy_sales_records(session: Session, frame: pd.DataFrame) -> int:
    """Stream the sales rows into PostgreSQL with COPY, in chunks."""
    # Reach past SQLAlchemy to the psycopg connection, because COPY is a
    # PostgreSQL protocol feature rather than SQL the ORM can emit.
    dbapi_connection = session.connection().connection
    raw_connection = getattr(dbapi_connection, "driver_connection", dbapi_connection)

    columns = ", ".join(SALES_COPY_COLUMNS)
    statement = f"COPY sales_records ({columns}) FROM STDIN WITH (FORMAT csv, NULL '')"

    written = 0
    with raw_connection.cursor() as cursor:
        with cursor.copy(statement) as copy:
            for start in range(0, len(frame), COPY_CHUNK_ROWS):
                chunk = frame.iloc[start : start + COPY_CHUNK_ROWS]
                buffer = io.StringIO()
                chunk.to_csv(buffer, index=False, header=False, na_rep="")
                copy.write(buffer.getvalue())
                written += len(chunk)
                logger.info("COPY progress: %s/%s rows", written, len(frame))
    return written


def store_clean_dataset(
    session: Session,
    dataset_id: uuid.UUID,
    frame: pd.DataFrame,
    product_variants: dict[str, int],
) -> int:
    """Replace this dataset's stored records with the cleaned frame."""
    delete_dataset_records(session, dataset_id)

    category_ids = _insert_categories(session, dataset_id, frame)
    product_ids = _insert_products(session, dataset_id, frame, product_variants, category_ids)
    customer_ids = _insert_customers(session, dataset_id, frame)

    sales = pd.DataFrame(index=frame.index)
    sales["dataset_id"] = str(dataset_id)
    sales["invoice_id"] = frame["invoice_id"]
    sales["occurred_at"] = frame["occurred_at"]
    # .map() on a column containing NA returns float64 (pandas upcasts), which
    # writes "3436.0" - and PostgreSQL rejects that for a bigint column. The
    # nullable Int64 dtype keeps whole numbers whole and empty cells empty.
    sales["product_id"] = (
        frame["product_code"].map(product_ids).astype("Int64") if product_ids else pd.NA
    )
    sales["customer_id"] = (
        frame["customer_id"].map(customer_ids).astype("Int64") if customer_ids else pd.NA
    )
    sales["region"] = frame["region"]
    sales["quantity"] = frame["quantity"]
    sales["unit_price"] = frame["unit_price"]
    sales["revenue"] = frame["revenue"]
    # PostgreSQL's CSV input reads 't'/'f' as booleans.
    sales["is_return"] = frame["is_return"].map({True: "t", False: "f"})
    sales["is_outlier"] = frame["is_outlier"].map({True: "t", False: "f"})

    return _copy_sales_records(session, sales[SALES_COPY_COLUMNS])
