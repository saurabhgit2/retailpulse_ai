"""Use cases for datasets: upload, start processing, delete.

Services orchestrate. They call the pure preprocessing code, use repositories to
reach the database, and raise application errors. They know nothing about HTTP:
the route layer turns their results into responses and their errors into status
codes.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFound, PayloadTooLarge, ValidationFailed
from app.db.models.dataset import Dataset
from app.db.models.user import User
from app.db.repositories import datasets as dataset_repo
from app.preprocessing import validation
from app.preprocessing.cleaning import PIPELINE_VERSION
from app.preprocessing.csv_io import EXCEL_SOURCE, CsvReadError, read_table
from app.preprocessing.field_guide import DEFAULT_CLEANING_OPTIONS
from app.preprocessing.schema_detection import build_upload_profile

logger = logging.getLogger(__name__)

CHUNK_BYTES = 1024 * 1024  # stream the upload 1 MB at a time


def _store_upload(source: BinaryIO, destination: Path, max_mb: int) -> tuple[int, str]:
    """Write the upload to disk in chunks, hashing as we go.

    Never `source.read()` the whole file: a 100 MB upload would then sit in
    memory in full, and several at once would exhaust the server. Chunking also
    lets us stop the moment the size limit is passed.
    """
    digest = hashlib.sha256()
    size = 0
    limit = max_mb * 1024 * 1024

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as target:
        while chunk := source.read(CHUNK_BYTES):
            size += len(chunk)
            if size > limit:
                target.close()
                destination.unlink(missing_ok=True)
                raise PayloadTooLarge(f"Files must be {max_mb} MB or smaller.")
            digest.update(chunk)
            target.write(chunk)

    return size, digest.hexdigest()


def create_dataset_from_upload(
    session: Session,
    *,
    user: User,
    filename: str | None,
    stream: BinaryIO,
    is_synthetic: bool,
    settings: Settings,
) -> Dataset:
    """Step 1 of the upload: store the file and profile its columns."""
    safe_name = validation.validate_upload_filename(filename)

    dataset_id = uuid.uuid4()
    # The user's filename is shown in the UI but never used as a path, so a name
    # like "..\\..\\evil.csv" cannot escape the upload directory.
    suffix = validation.upload_suffix(safe_name)
    storage_path = Path(settings.upload_dir) / f"{dataset_id}{suffix}"

    size, sha256 = _store_upload(stream, storage_path, settings.max_upload_mb)
    validation.validate_upload_size(size, settings.max_upload_mb)

    try:
        preview, encoding = read_table(storage_path, nrows=settings.preview_rows)
    except CsvReadError as error:
        storage_path.unlink(missing_ok=True)
        raise ValidationFailed(
            f"The file could not be read: {error}", code="MALFORMED_CSV"
        ) from error

    try:
        validation.validate_preview_frame(preview, settings.max_columns)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise

    profile = build_upload_profile(
        preview,
        rows_examined=len(preview),
        file_truncated=len(preview) >= settings.preview_rows,
    )
    if encoding not in ("utf-8", EXCEL_SOURCE):
        profile["warnings"].append(
            {
                "code": "ENCODING_FALLBACK",
                "message": f"The file is not UTF-8; it was read as {encoding}. Check that "
                           f"accented characters look right in the samples above.",
            }
        )

    dataset = Dataset(
        id=dataset_id,
        owner_id=user.id,
        name=Path(safe_name).stem[:200],
        is_synthetic=is_synthetic,
        status="awaiting_mapping",
        original_filename=safe_name[:255],
        storage_path=str(storage_path),
        file_sha256=sha256,
        file_size_bytes=size,
        profile=profile,
        pipeline_version=PIPELINE_VERSION,
    )
    session.add(dataset)
    session.flush()
    logger.info("Stored upload %s (%s bytes) as dataset %s", safe_name, size, dataset.id)
    return dataset


def prepare_processing(
    session: Session, dataset: Dataset, mapping: dict[str, Any], options: dict[str, Any]
) -> dict[str, Any]:
    """Step 2: validate the confirmed mapping and mark the dataset processing.

    All validation happens here, before the background task starts, so the user
    gets mistakes back immediately instead of as a failed job.
    """
    validation.require_status(
        dataset.status,
        ("awaiting_mapping", "failed"),
        f"This dataset is {dataset.status.replace('_', ' ')} and cannot be processed now.",
        "INVALID_STATUS",
    )

    profile = dataset.profile or {}
    available = [column["name"] for column in profile.get("detected_columns", [])]
    confirmed = validation.validate_mapping(mapping, available)

    # Re-read a preview to test the date format against real values.
    preview, _ = read_table(
        Path(dataset.storage_path), columns=[confirmed["occurred_at"]], nrows=5000
    )
    date_format = validation.resolve_date_format(
        preview[confirmed["occurred_at"]], options.get("date_format"), confirmed["occurred_at"]
    )

    effective = {**DEFAULT_CLEANING_OPTIONS, **options, "date_format": date_format}

    dataset.column_mapping = confirmed
    dataset.cleaning_options = effective
    dataset.status = "processing"
    dataset.status_message = None
    dataset.pipeline_version = PIPELINE_VERSION
    session.flush()
    return effective


def delete_dataset(session: Session, dataset: Dataset) -> None:
    """Delete the dataset, everything derived from it (cascade) and the file."""
    path = Path(dataset.storage_path)
    session.delete(dataset)
    session.flush()
    path.unlink(missing_ok=True)


def get_owned_or_404(session: Session, dataset_id: uuid.UUID, owner_id: uuid.UUID) -> Dataset:
    dataset = dataset_repo.get_owned_dataset(session, dataset_id, owner_id)
    if dataset is None:
        raise NotFound("That dataset does not exist.", details={"dataset_id": str(dataset_id)})
    return dataset


def quality_report_or_conflict(dataset: Dataset) -> dict[str, Any]:
    validation.require_status(
        dataset.status,
        ("ready",),
        "This dataset isn't ready yet. Its report appears once processing finishes.",
        "DATASET_NOT_READY",
    )
    return dataset.quality_report or {}


def purge_upload_directory(settings: Settings) -> None:
    """Used by tests and scripts; never exposed through the API."""
    shutil.rmtree(settings.upload_dir, ignore_errors=True)
