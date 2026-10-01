"""Phase 3: the cleaned data - categories, products, customers and sales records.

Indexes are chosen from the queries the application actually runs
(architecture §8.3), not added speculatively: every one costs write time and
disk on a table with a million rows.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="mapped"),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"],
                                name="fk_categories_dataset_id_datasets", ondelete="CASCADE"),
        sa.UniqueConstraint("dataset_id", "name", name="uq_categories_dataset_id_name"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("description_variants", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"],
                                name="fk_products_dataset_id_datasets", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"],
                                name="fk_products_category_id_categories", ondelete="SET NULL"),
        sa.UniqueConstraint("dataset_id", "product_code",
                            name="uq_products_dataset_id_product_code"),
    )

    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"],
                                name="fk_customers_dataset_id_datasets", ondelete="CASCADE"),
        sa.UniqueConstraint("dataset_id", "external_id",
                            name="uq_customers_dataset_id_external_id"),
    )

    op.create_table(
        "sales_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", sa.String(length=32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        # Numeric, not float: money must not drift through binary rounding.
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("revenue", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("is_return", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_outlier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name="pk_sales_records"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"],
                                name="fk_sales_records_dataset_id_datasets", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                name="fk_sales_records_product_id_products", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"],
                                name="fk_sales_records_customer_id_customers", ondelete="SET NULL"),
    )

    # Every analytics query filters by dataset first, then by date range.
    op.create_index("ix_sales_records_dataset_id_occurred_at", "sales_records",
                    ["dataset_id", "occurred_at"])
    op.create_index("ix_sales_records_dataset_id_product_id_occurred_at", "sales_records",
                    ["dataset_id", "product_id", "occurred_at"])
    op.create_index("ix_sales_records_dataset_id_invoice_id", "sales_records",
                    ["dataset_id", "invoice_id"])
    op.create_index("ix_sales_records_dataset_id_region", "sales_records",
                    ["dataset_id", "region"])
    # Partial index: guest rows have no customer, so they are left out of it.
    op.create_index(
        "ix_sales_records_dataset_id_customer_id",
        "sales_records",
        ["dataset_id", "customer_id"],
        postgresql_where=sa.text("customer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("sales_records")
    op.drop_table("customers")
    op.drop_table("products")
    op.drop_table("categories")
