from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    """Row in the datasets list. The column profile is left out deliberately:
    it is large and only the upload wizard needs it."""

    id: uuid.UUID
    name: str
    is_synthetic: bool
    status: str
    status_message: str | None = None
    original_filename: str
    file_size_bytes: int | None = None
    file_sha256: str | None = None
    row_count_raw: int | None = None
    row_count_clean: int | None = None
    # Fingerprint of the cleaned data (architecture NFR-03). Same file + same
    # mapping + same pipeline version = same hash, so a result can be shown to
    # be reproducible rather than merely claimed to be.
    clean_data_sha256: str | None = None
    date_min: datetime | None = None
    date_max: datetime | None = None
    currency: str | None = None
    capabilities: list[dict[str, Any]] | None = None
    pipeline_version: str | None = None
    created_at: datetime
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}


class DatasetDetail(DatasetSummary):
    """Single dataset, including what the wizard needs to map columns."""

    profile: dict[str, Any] | None = None
    column_mapping: dict[str, Any] | None = None
    cleaning_options: dict[str, Any] | None = None


class DatasetList(BaseModel):
    items: list[DatasetSummary]
    total: int


class ProcessOptions(BaseModel):
    """Cleaning options. Anything omitted falls back to the documented default."""

    date_format: str | None = Field(default=None, description="'iso', 'dmy' or 'mdy'")
    drop_exact_duplicates: bool | None = None
    exclude_non_product_codes: bool | None = None
    non_product_codes: list[str] | None = None
    outlier_threshold: float | None = Field(default=None, ge=1, le=20)
    currency: str | None = Field(default=None, max_length=3)


class ProcessRequest(BaseModel):
    mapping: dict[str, str | None]
    options: ProcessOptions = Field(default_factory=ProcessOptions)


class ProcessAccepted(BaseModel):
    id: uuid.UUID
    status: str
    poll: str = Field(description="Poll this URL until status is 'ready' or 'failed'.")