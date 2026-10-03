"""Validation rules: what the API refuses, and the message it gives."""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.errors import Conflict, PayloadTooLarge, UnsupportedFile, ValidationFailed
from app.preprocessing.validation import (
    require_status,
    resolve_date_format,
    validate_clean_result,
    validate_mapping,
    validate_upload_filename,
    validate_upload_size,
)

COLUMNS = ["Invoice", "InvoiceDate", "Quantity", "Price", "StockCode"]


def test_non_csv_files_are_refused():
    with pytest.raises(UnsupportedFile):
        validate_upload_filename("report.xlsx")


def test_empty_and_oversized_files_are_refused():
    with pytest.raises(ValidationFailed):
        validate_upload_size(0, 200)
    with pytest.raises(PayloadTooLarge):
        validate_upload_size(300 * 1024 * 1024, 200)


def test_mapping_rejects_columns_that_are_not_in_the_file():
    with pytest.raises(ValidationFailed) as error:
        validate_mapping({"occurred_at": "Nope", "quantity": "Quantity", "unit_price": "Price"},
                         COLUMNS)
    assert error.value.code == "UNKNOWN_COLUMN"


def test_mapping_rejects_one_column_used_twice():
    with pytest.raises(ValidationFailed) as error:
        validate_mapping(
            {"occurred_at": "InvoiceDate", "quantity": "Quantity", "unit_price": "Quantity"},
            COLUMNS,
        )
    assert error.value.code == "DUPLICATE_MAPPING"


def test_mapping_requires_a_revenue_path():
    with pytest.raises(ValidationFailed) as error:
        validate_mapping({"occurred_at": "InvoiceDate", "quantity": "Quantity"}, COLUMNS)
    assert error.value.code == "MISSING_REQUIRED_FIELD"


def test_valid_mapping_is_returned_with_every_field_present():
    result = validate_mapping(
        {"occurred_at": "InvoiceDate", "quantity": "Quantity", "unit_price": "Price"}, COLUMNS
    )
    assert result["occurred_at"] == "InvoiceDate"
    assert result["category"] is None  # unmapped fields are explicit


def test_ambiguous_dates_require_the_user_to_choose():
    values = pd.Series(["01/02/2010", "03/04/2010"])
    with pytest.raises(ValidationFailed) as error:
        resolve_date_format(values, None, "Date")
    assert error.value.code == "DATE_FORMAT_REQUIRED"
    assert set(error.value.details["candidates"]) == {"dmy", "mdy"}


def test_a_chosen_format_that_does_not_fit_is_rejected():
    values = pd.Series(["2010-01-01", "2010-01-02"])
    with pytest.raises(ValidationFailed) as error:
        resolve_date_format(values, "dmy", "Date")
    assert error.value.code == "DATE_PARSE_FAILURE"


def test_unambiguous_dates_need_no_choice():
    assert resolve_date_format(pd.Series(["2010-01-01"]), None, "Date") == "iso"


def test_too_little_data_is_refused():
    with pytest.raises(ValidationFailed) as error:
        validate_clean_result(rows_clean=10, distinct_weeks=20, min_rows=100)
    assert error.value.code == "INSUFFICIENT_DATA"

    with pytest.raises(ValidationFailed):
        validate_clean_result(rows_clean=500, distinct_weeks=3, min_rows=100)


def test_status_guard():
    require_status("ready", ("ready",), "nope", "X")  # does not raise
    with pytest.raises(Conflict) as error:
        require_status("processing", ("ready",), "Not ready yet.", "DATASET_NOT_READY")
    assert error.value.code == "DATASET_NOT_READY"
