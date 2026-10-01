"""Phase 2: users and datasets.

Every schema change is a migration, and migrations are committed. That is
version control for the database: a colleague (or you, on another machine) runs
`alembic upgrade head` and gets exactly this schema.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="awaiting_mapping"),
        sa.Column("status_message", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        # JSONB: written once, read whole, never filtered on an inner key.
        sa.Column("profile", postgresql.JSONB(), nullable=True),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=True),
        sa.Column("cleaning_options", postgresql.JSONB(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=True),
        sa.Column("quality_report", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_version", sa.String(length=20), nullable=True),
        sa.Column("clean_data_sha256", sa.String(length=64), nullable=True),
        sa.Column("row_count_raw", sa.Integer(), nullable=True),
        sa.Column("row_count_clean", sa.Integer(), nullable=True),
        sa.Column("date_min", sa.DateTime(timezone=False), nullable=True),
        sa.Column("date_max", sa.DateTime(timezone=False), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_datasets_owner_id_users",
                                ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('awaiting_mapping', 'processing', 'ready', 'failed')",
            name="ck_datasets_dataset_status",
        ),
    )
    op.create_index("ix_datasets_owner_id", "datasets", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_datasets_owner_id", table_name="datasets")
    op.drop_table("datasets")
    op.drop_table("users")
