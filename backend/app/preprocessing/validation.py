"""Validation rules (architecture §12.2).

Every check answers the same question: can the next step trust this input? Each
failure raises an application error carrying a code the frontend can act on and
a message the user can act on.

The checks run on the server even though the browser checks some of them too.
Anything enforced only in the browser is not enforced at all.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import Conflict, PayloadTooLarge, UnsupportedFile, ValidationFailed
from app.preprocessing.csv_io import SUPPORTED_SUFFIXES
from app.preprocessing.dates import DATE_STYLES, parse_rate
from app.preprocessing.field_guide import (
    FIELD_KEYS,
    blocking_capability_gaps,
    missing_required_fields,
)

DATE_PARSE_THRESHOLD = 0.95


def validate_upload_filename(filename: str | None) -> str:
    """Accept CSV and Excel.

    Excel matters because Online Retail II is distributed as a workbook with one
    sheet per year; requiring a manual export would be an avoidable obstacle
    between the user and their own data.
    """
    if not filename:
        raise ValidationFailed("No file was provided.", code="FILE_REQUIRED")
    if not filename.lower().endswith(SUPPORTED_SUFFIXES):
        allowed = ", ".join(SUPPORTED_SUFFIXES)
        raise UnsupportedFile(
            f'"{filename}" is not a supported file type. Upload one of: {allowed}.'
        )
    return filename


def upload_suffix(filename: str) -> str:
    """The extension to store the file under, so later reads dispatch correctly."""
    lowered = filename.lower()
    for suffix in SUPPORTED_SUFFIXES:
        if lowered.endswith(suffix):
            return suffix
    return ".csv"


def validate_upload_size(size_bytes: int, max_mb: int) -> None:
    if size_bytes == 0:
        raise ValidationFailed("The file is empty.", code="EMPTY_FILE")
    if size_bytes > max_mb * 1024 * 1024:
        raise PayloadTooLarge(f"Files must be {max_mb} MB or smaller.")


def validate_preview_frame(frame: pd.DataFrame, max_columns: int) -> None:
    if frame.shape[1] == 0 or frame.empty:
        raise ValidationFailed(
            "The file needs a header row and at least one data row.", code="EMPTY_FILE"
        )
    if frame.shape[1] > max_columns:
        raise ValidationFailed(
            f"The file has {frame.shape[1]} columns, more than the {max_columns} allowed. "
            f"Check that the file is comma-separated.",
            code="MALFORMED_CSV",
        )


def validate_mapping(mapping: dict[str, Any], available_columns: list[str]) -> dict[str, str | None]:
    """Check the confirmed mapping before anything is cleaned."""
    unknown_fields = [key for key in mapping if key not in FIELD_KEYS]
    if unknown_fields:
        raise ValidationFailed(
            f"Unknown field(s): {', '.join(sorted(unknown_fields))}.", code="UNKNOWN_FIELD"
        )

    cleaned: dict[str, str | None] = {key: mapping.get(key) or None for key in FIELD_KEYS}

    missing_columns = [c for c in cleaned.values() if c and c not in available_columns]
    if missing_columns:
        raise ValidationFailed(
            f"These columns are not in the file: {', '.join(missing_columns)}.",
            code="UNKNOWN_COLUMN",
        )

    used: dict[str, str] = {}
    duplicates: list[str] = []
    for fieldname, column in cleaned.items():
        if not column:
            continue
        if column in used:
            duplicates.append(column)
        else:
            used[column] = fieldname
    if duplicates:
        raise ValidationFailed(
            f"Each source column can be mapped to one field only. Used more than once: "
            f"{', '.join(sorted(set(duplicates)))}.",
            code="DUPLICATE_MAPPING",
            details={"columns": sorted(set(duplicates))},
        )

    blocking = sorted(set(missing_required_fields(cleaned) + blocking_capability_gaps(cleaned)))
    if blocking:
        raise ValidationFailed(
            f"Map these before processing: {'; '.join(blocking)}.",
            code="MISSING_REQUIRED_FIELD",
            details={"missing": blocking},
        )

    return cleaned


def resolve_date_format(
    values: pd.Series, requested: str | None, column_name: str
) -> str:
    """Decide how to read the date column, or refuse to guess."""
    if requested:
        if requested not in DATE_STYLES:
            raise ValidationFailed(
                f"Unknown date format {requested!r}. Expected one of {', '.join(DATE_STYLES)}.",
                code="DATE_FORMAT_INVALID",
            )
        if parse_rate(values, requested) < DATE_PARSE_THRESHOLD:
            raise ValidationFailed(
                f'Fewer than 95% of the values in "{column_name}" can be read with the chosen '
                f"date format.",
                code="DATE_PARSE_FAILURE",
            )
        return requested

    candidates = [style for style in DATE_STYLES if parse_rate(values, style) >= DATE_PARSE_THRESHOLD]
    if not candidates:
        raise ValidationFailed(
            f'"{column_name}" does not contain readable dates.', code="DATE_PARSE_FAILURE"
        )
    if len(candidates) > 1:
        # Never guess: 03/04 is two different days depending on the answer.
        raise ValidationFailed(
            "The dates could be read in more than one way. Choose the date format before "
            "processing.",
            code="DATE_FORMAT_REQUIRED",
            details={"candidates": candidates},
        )
    return candidates[0]


def validate_clean_result(rows_clean: int, distinct_weeks: int, min_rows: int) -> None:
    """Refuse to store a dataset too small or too short to analyse."""
    if rows_clean < min_rows:
        raise ValidationFailed(
            f"Only {rows_clean} usable rows remain after cleaning (at least {min_rows} are "
            f"needed). Check the column mapping and the date format.",
            code="INSUFFICIENT_DATA",
        )
    if distinct_weeks < 8:
        raise ValidationFailed(
            f"The data covers {distinct_weeks} distinct weeks; at least 8 are needed for "
            f"trends and forecasting.",
            code="INSUFFICIENT_DATA",
        )


def require_status(current: str, allowed: tuple[str, ...], message: str, code: str) -> None:
    if current not in allowed:
        raise Conflict(message, code=code, details={"status": current})
