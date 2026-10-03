"""Column detection: the algorithm the upload wizard depends on."""

from __future__ import annotations

import pandas as pd

from app.preprocessing.schema_detection import build_upload_profile, normalise_header


def profile(frame: pd.DataFrame) -> dict:
    return build_upload_profile(frame, rows_examined=len(frame), file_truncated=False)


def test_headers_are_normalised_before_matching():
    assert normalise_header("Customer ID") == "customerid"
    assert normalise_header("Invoice_Date") == "invoicedate"


VALID_FRAME = pd.DataFrame(
    [
        ["489434", "85048", "GLASS BALL LIGHTS", "12", "2009-12-01 07:45:00", "6.95", "13085.0",
         "United Kingdom"],
        ["489434", "79323P", "PINK CHERRY LIGHTS", "12", "2009-12-01 07:45:00", "6.75", "13085.0",
         "United Kingdom"],
        ["C489449", "22087", "PAPER BUNTING", "-12", "2009-12-01 10:33:00", "2.95", "",
         "Australia"],
    ],
    columns=["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price",
             "Customer ID", "Country"],
).astype("string")


def test_online_retail_ii_columns_all_map(mapping):
    assert profile(VALID_FRAME)["suggested_mapping"] == mapping


def test_missing_revenue_and_category_are_reported():
    codes = {warning["code"] for warning in profile(VALID_FRAME)["warnings"]}
    assert "REVENUE_WILL_BE_DERIVED" in codes
    assert "NO_CATEGORY" in codes


def test_a_column_of_mostly_unreadable_dates_is_not_treated_as_a_date():
    """The threshold is 95%: a column that cannot be read reliably is not a date
    column, and the user is told a required field is unmapped rather than given
    a silently mangled one."""
    frame = pd.DataFrame(
        {"When": ["2024-01-01", "nope", "also no", "still not"], "Sales": ["1", "2", "3", "4"]}
    ).astype("string")
    result = profile(frame)
    assert result["suggested_mapping"]["occurred_at"] is None
    assert result["missing_required"] == ["occurred_at"]


def test_a_column_whose_contents_contradict_its_name_is_not_mapped():
    frame = pd.DataFrame(
        {"Date": ["2020-01-01", "2020-01-02"], "Price": ["n/a", "call us"]}
    ).astype("string")
    result = profile(frame)
    assert result["suggested_mapping"]["unit_price"] is None
    assert "TYPE_MISMATCH" in {w["code"] for w in result["warnings"]}


def test_ambiguous_dates_are_flagged():
    frame = pd.DataFrame(
        {"Date": ["01/02/2010", "03/04/2010"], "Sales": ["5", "7"]}
    ).astype("string")
    assert "AMBIGUOUS_DATE_FORMAT" in {w["code"] for w in profile(frame)["warnings"]}


def test_required_fields_are_listed_when_missing():
    frame = pd.DataFrame({"Sales": ["5", "7"]}).astype("string")
    assert profile(frame)["missing_required"] == ["occurred_at"]
