"""The cleaned data: products, customers, categories and the sales fact table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Category(Base):
    """Optional. Online Retail II has no category column, so most datasets
    have none; `source` records whether it came from the file or was derived."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("dataset_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="mapped")


class Product(Base):
    """One row per product code per dataset, so a million repeated description
    strings are stored once (third normal form)."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("dataset_id", "product_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="SET NULL")
    )
    # How many different descriptions this code had in the file: a data-quality
    # signal that is reported rather than hidden.
    description_variants: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Customer(Base):
    """Pseudonymous customer. Rows without an ID are kept as guest sales with
    customer_id NULL, so revenue is complete even though segmentation is not."""

    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("dataset_id", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)


class SalesRecord(Base):
    """One line of one order: the fact table. About 1M rows for Online Retail II.

    Indexes are chosen from how the app actually queries (architecture §8.3):
    every analytics query filters by dataset first, then a date range, then
    optionally a product, customer, invoice or region.
    """

    __tablename__ = "sales_records"
    __table_args__ = (
        Index("ix_sales_records_dataset_id_occurred_at", "dataset_id", "occurred_at"),
        Index("ix_sales_records_dataset_id_product_id_occurred_at",
              "dataset_id", "product_id", "occurred_at"),
        Index("ix_sales_records_dataset_id_invoice_id", "dataset_id", "invoice_id"),
        Index("ix_sales_records_dataset_id_region", "dataset_id", "region"),
        # Partial index: guest rows have no customer, so they are left out of it.
        Index(
            "ix_sales_records_dataset_id_customer_id",
            "dataset_id",
            "customer_id",
            postgresql_where="customer_id IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )

    invoice_id: Mapped[str | None] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE")
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="SET NULL")
    )
    region: Mapped[str | None] = mapped_column(String(100))

    # Numeric, not float: money and counts must not drift through binary
    # floating-point rounding.
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # Flags, not deletions: each analysis decides what to exclude.
    is_return: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
