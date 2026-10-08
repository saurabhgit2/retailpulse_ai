"""Phase 4: the analysis cache.

One table. Expensive analyses (statistics, features, series profiles,
seasonality) are stored against a hash of everything that can change the
answer, so a repeat request is a lookup rather than a recomputation.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_type", sa.String(length=50), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("pipeline_version", sa.String(length=20), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_results"),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"],
            name="fk_analysis_results_dataset_id_datasets", ondelete="CASCADE",
        ),
        # The unique constraint is also the lookup index: a cache read matches
        # all four columns, which is exactly its leading prefix.
        sa.UniqueConstraint(
            "dataset_id", "analysis_type", "params_hash", "pipeline_version",
            name="uq_analysis_results_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("analysis_results")
