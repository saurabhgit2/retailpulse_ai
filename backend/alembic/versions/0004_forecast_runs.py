"""Phase 5: forecast run persistence.

Two tables. `forecast_runs` holds one experiment - its declared config, the
protocol it actually ran, the summary, the significance result and the library
versions. `forecast_results` holds one row per model per fold, with fold 0
reserved for the locked hold-out.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("series_scope", sa.String(length=20), nullable=False),
        sa.Column("series_key", sa.String(length=100), nullable=True),
        sa.Column("granularity", sa.String(length=10), nullable=False),
        sa.Column("value_column", sa.String(length=30), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("folds", sa.Integer(), nullable=False),
        sa.Column("season_length", sa.Integer(), nullable=False),
        sa.Column("window_style", sa.String(length=20), nullable=False),
        sa.Column("primary_metric", sa.String(length=20), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("protocol", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("significance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("combination", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("series_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("selected_model", sa.String(length=50), nullable=True),
        sa.Column("holdout_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("holdout_warning", sa.Text(), nullable=True),
        sa.Column("library_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("pipeline_version", sa.String(length=20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("computed_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_forecast_runs"),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"],
            name="fk_forecast_runs_dataset_id_datasets", ondelete="CASCADE",
        ),
    )
    # "The latest ready run for this dataset and this series" is the dashboard's
    # only question, and this is it.
    op.create_index(
        "ix_forecast_runs_dataset_id_series_key_created_at",
        "forecast_runs", ["dataset_id", "series_key", "created_at"],
    )
    op.create_index(
        "ix_forecast_runs_dataset_id_status", "forecast_runs", ["dataset_id", "status"],
    )

    op.create_table(
        "forecast_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("fold", sa.Integer(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("uses_exogenous", sa.Boolean(), nullable=False),
        sa.Column("wape", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("mase", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("mae", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("rmse", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("mape", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("smape", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("bias", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("forecast", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_forecast_results"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["forecast_runs.id"],
            name="fk_forecast_results_run_id_forecast_runs", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_forecast_results_run_id_model", "forecast_results", ["run_id", "model"])


def downgrade() -> None:
    op.drop_index("ix_forecast_results_run_id_model", table_name="forecast_results")
    op.drop_table("forecast_results")
    op.drop_index("ix_forecast_runs_dataset_id_status", table_name="forecast_runs")
    op.drop_index(
        "ix_forecast_runs_dataset_id_series_key_created_at", table_name="forecast_runs"
    )
    op.drop_table("forecast_runs")
