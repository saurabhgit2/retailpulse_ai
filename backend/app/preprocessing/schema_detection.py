"""Working out what the columns in an uploaded file are.

The rule (architecture §12.1): suggest, never assume. The server proposes a
mapping from the column names *and* their contents, and the user confirms it
before any cleaning happens.

Everything here is pure: DataFrame in, plain dictionaries out. That makes it
testable without a server, a database or a file.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from app.preprocessing.dates import detect_date_formats
from app.preprocessing.field_guide import (
    CANONICAL_FIELDS,
    compute_capabilities,
    missing_required_fields,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def normalise_header(name: str) -> str:
    """'Customer ID' -> 'customerid', 'Invoice_Date' -> 'invoicedate'."""
    return _NON_ALNUM.sub("", str(name).lower())


def _looks_numeric(series: pd.Series) -> float:
    converted = pd.to_numeric(series, errors="coerce")
    return float(converted.notna().mean()) if len(series) else 0.0


def profile_columns(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Describe every column: inferred type, emptiness, sample values, date styles."""
    profile: list[dict[str, Any]] = []

    for name in frame.columns:
        values = frame[name].astype("string").str.strip()
        non_empty = values[values.notna() & (values != "")]

        dates = detect_date_formats(non_empty.tolist()) if not non_empty.empty else {
            "candidates": [], "ambiguous": False
        }

        if dates["candidates"]:
            inferred = "datetime"
        elif not non_empty.empty and _looks_numeric(non_empty) >= 0.95:
            inferred = "numeric"
        else:
            inferred = "text"

        profile.append(
            {
                "name": str(name),
                "inferred_type": inferred,
                "null_count_sample": int(len(values) - len(non_empty)),
                "distinct_count_sample": int(non_empty.nunique()),
                "sample_values": [str(v) for v in non_empty.drop_duplicates().head(3)],
                "date_format_candidates": dates["candidates"],
                "date_ambiguous": bool(dates["ambiguous"]),
            }
        )

    return profile


def _type_matches(field: dict[str, Any], column: dict[str, Any]) -> bool:
    if field["expected_type"] == "any":
        return True
    return field["expected_type"] == column["inferred_type"]


def suggest_mapping(columns: list[dict[str, Any]]) -> tuple[dict[str, str | None], list[dict]]:
    """Match columns to canonical fields by name, then check their contents agree.

    A column called "Price" that contains words is left unmapped with a warning,
    rather than mapped and failing later during cleaning.
    """
    mapping: dict[str, str | None] = {field["key"]: None for field in CANONICAL_FIELDS}
    warnings: list[dict[str, str]] = []
    used: set[str] = set()

    for field in CANONICAL_FIELDS:
        match = next(
            (
                column
                for column in columns
                if column["name"] not in used
                and normalise_header(column["name"]) in field["synonyms"]
            ),
            None,
        )
        if match is None:
            continue
        if not _type_matches(field, match):
            warnings.append(
                {
                    "code": "TYPE_MISMATCH",
                    "message": (
                        f'"{match["name"]}" looks like {field["label"]}, but its values are '
                        f'{match["inferred_type"]}, not {field["expected_type"]}. It was left '
                        f"unmapped; map it yourself if it is correct."
                    ),
                }
            )
            continue
        mapping[field["key"]] = match["name"]
        used.add(match["name"])

    return mapping, warnings


def build_upload_profile(
    frame: pd.DataFrame, *, rows_examined: int, file_truncated: bool
) -> dict[str, Any]:
    """Everything POST /datasets returns about a newly uploaded file."""
    columns = profile_columns(frame)
    mapping, warnings = suggest_mapping(columns)

    if not mapping["revenue"] and mapping["quantity"] and mapping["unit_price"]:
        warnings.append(
            {
                "code": "REVENUE_WILL_BE_DERIVED",
                "message": "No revenue column found. Revenue will be calculated as "
                           "quantity x unit price.",
            }
        )
    if not mapping["customer_id"]:
        warnings.append(
            {
                "code": "NO_CUSTOMER_ID",
                "message": "No customer ID column found. Customer segmentation will be "
                           "unavailable.",
            }
        )
    if not mapping["category"]:
        warnings.append(
            {
                "code": "NO_CATEGORY",
                "message": "No category column found. Category analyses will be hidden.",
            }
        )

    date_column = next((c for c in columns if c["name"] == mapping["occurred_at"]), None)
    if date_column and date_column["date_ambiguous"]:
        warnings.append(
            {
                "code": "AMBIGUOUS_DATE_FORMAT",
                "message": f'Dates in "{date_column["name"]}" could be day/month or month/day. '
                           f"Choose the correct format before processing.",
            }
        )

    return {
        "detected_columns": columns,
        "suggested_mapping": mapping,
        "missing_required": missing_required_fields(mapping),
        "warnings": warnings,
        "capabilities_preview": compute_capabilities(mapping),
        "preview": {"rows_examined": int(rows_examined), "file_truncated": bool(file_truncated)},
    }
