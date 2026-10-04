"""The background job that turns an uploaded file into stored, cleaned data.

The API answers 202 Accepted immediately and this runs afterwards, because
cleaning a million rows takes far longer than a browser will wait. The frontend
polls GET /datasets/{id} until the status is `ready` or `failed`
(architecture ADR-03).

Everything here runs *outside* a request: it opens its own database session and
must never assume a user or a request context exists.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.core.errors import RetailPulseError
from app.db.repositories import datasets as dataset_repo
from app.db.repositories.sales import store_clean_dataset
from app.db.session import SessionFactory
from app.preprocessing import validation
from app.preprocessing.cleaning import build_quality_report, clean_dataset
from app.preprocessing.csv_io import CsvReadError, read_csv
from app.preprocessing.field_guide import compute_capabilities

logger = logging.getLogger(__name__)


def _open_session():
    """Open the session this job will use.

    A background task runs after the response, so the request's session is gone
    and it must open its own. This is a named function rather than a direct
    SessionFactory() call so the tests can substitute their transaction-scoped
    session: otherwise the job connects to the *development* database and cannot
    see the rows the test just created inside an uncommitted transaction.
    """
    return SessionFactory()


def process_dataset(dataset_id: uuid.UUID) -> None:
    """Clean and store one dataset. Never raises: failures are recorded on the row."""
    settings = get_settings()
    started = time.perf_counter()
    session = _open_session()

    try:
        dataset = dataset_repo.get_dataset(session, dataset_id)
        if dataset is None or dataset.status != "processing":
            logger.warning("Dataset %s is not awaiting processing; skipping", dataset_id)
            return

        mapping = dataset.column_mapping or {}
        options = dataset.cleaning_options or {}
        source_columns = [column for column in mapping.values() if column]

        logger.info("Processing dataset %s (%s)", dataset_id, dataset.original_filename)
        raw, _ = read_csv(Path(dataset.storage_path), columns=source_columns)
        read_seconds = time.perf_counter() - started

        result = clean_dataset(raw, mapping, options)
        if not result.conservation_ok:
            # Belt and braces: the tests assert this too. If it ever fires, a
            # cleaning step has dropped rows without recording them.
            raise RuntimeError(
                f"Conservation check failed: {result.rows_raw} raw rows != "
                f"{result.rows_clean} kept + {result.rows_excluded} excluded"
            )

        distinct_weeks = int(
            result.frame["occurred_at"].dt.to_period("W").nunique() if result.rows_clean else 0
        )
        validation.validate_clean_result(result.rows_clean, distinct_weeks, settings.min_clean_rows)

        rows_written = store_clean_dataset(
            session, dataset.id, result.frame, result.product_variants
        )

        report = build_quality_report(result, mapping)
        report["timings_seconds"] = {
            "read": round(read_seconds, 2),
            "total": round(time.perf_counter() - started, 2),
        }

        dataset.quality_report = report
        dataset.capabilities = compute_capabilities(mapping)
        dataset.row_count_raw = result.rows_raw
        dataset.row_count_clean = result.rows_clean
        dataset.clean_data_sha256 = result.fingerprint
        dataset.date_min = _to_naive(result.date_min)
        dataset.date_max = _to_naive(result.date_max)
        dataset.currency = options.get("currency")
        dataset.status = "ready"
        dataset.status_message = None
        dataset.processed_at = datetime.now(UTC)
        session.commit()

        logger.info(
            "Dataset %s ready: %s rows stored in %.1fs",
            dataset_id, rows_written, time.perf_counter() - started,
        )

    except (RetailPulseError, CsvReadError, ValueError, KeyError) as error:
        # Expected failure: tell the user what went wrong, in their words.
        _fail(session, dataset_id, str(getattr(error, "message", error)))
    except Exception:
        # Unexpected failure: log the detail, show the user something safe.
        logger.exception("Processing failed for dataset %s", dataset_id)
        _fail(
            session,
            dataset_id,
            "Processing failed unexpectedly. The server log has the details.",
        )
    finally:
        session.close()


def _to_naive(value: pd.Timestamp | None) -> datetime | None:
    """Transaction times are wall-clock times from the retailer's system, so they
    are stored without a time zone rather than shifted into one."""
    if value is None or pd.isna(value):
        return None
    return value.to_pydatetime().replace(tzinfo=None)


def _fail(session, dataset_id: uuid.UUID, message: str) -> None:
    session.rollback()
    dataset = dataset_repo.get_dataset(session, dataset_id)
    if dataset is not None:
        dataset.status = "failed"
        dataset.status_message = message[:500]
        session.commit()
        logger.warning("Dataset %s failed: %s", dataset_id, message)


def recover_stuck_datasets() -> int:
    """Called at start-up.

    Background tasks live inside this process, so a restart loses any that were
    running. Rather than leaving those datasets "processing" for ever, mark them
    failed with an explanation and let the user retry.
    """
    session = _open_session()
    try:
        stuck = dataset_repo.stuck_processing(session)
        for dataset in stuck:
            dataset.status = "failed"
            dataset.status_message = (
                "Processing was interrupted when the server restarted. Open the dataset and "
                "confirm the mapping again to retry."
            )
        if stuck:
            session.commit()
            logger.warning("Marked %s interrupted dataset(s) as failed", len(stuck))
        return len(stuck)
    finally:
        session.close()