"""Phase 5 (gap closure): prediction intervals and feature importance.

Two additive nullable columns on `forecast_runs`. Additive because 0004 may
already be applied: a run recorded before this migration keeps its results and
simply has no interval or importance block, which is the truth about it.

* `intervals` - the selected model's prediction interval around the hold-out
  forecast, sized from its cross-validation errors, with observed coverage.
* `feature_importance` - permutation importance from the global tree model and
  its agreement with the Phase 4 mutual-information ranking (§12.7).

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("intervals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "forecast_runs",
        sa.Column(
            "feature_importance", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("forecast_runs", "feature_importance")
    op.drop_column("forecast_runs", "intervals")
