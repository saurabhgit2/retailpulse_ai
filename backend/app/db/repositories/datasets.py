"""Dataset queries.

Every lookup is scoped to the owner. A dataset belonging to somebody else is
reported as "not found" rather than "forbidden", so the API never reveals that
an ID exists (architecture §9.1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.dataset import Dataset


def get_owned_dataset(session: Session, dataset_id: uuid.UUID, owner_id: uuid.UUID) -> Dataset | None:
    return session.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == owner_id)
    )


def list_datasets(session: Session, owner_id: uuid.UUID) -> list[Dataset]:
    return list(
        session.scalars(
            select(Dataset).where(Dataset.owner_id == owner_id).order_by(Dataset.created_at.desc())
        )
    )


def get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset | None:
    """Used by the background job, which runs without a request user."""
    return session.get(Dataset, dataset_id)


def stuck_processing(session: Session) -> list[Dataset]:
    """Datasets left mid-processing by a restart (architecture ADR-03)."""
    return list(session.scalars(select(Dataset).where(Dataset.status == "processing")))
