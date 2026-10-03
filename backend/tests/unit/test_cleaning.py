"""The cleaning pipeline.

The most important test here is the conservation check: rows in the file must
always equal rows kept plus rows excluded. If a step ever drops a row without
recording it, that test fails and the data-quality report becomes a lie.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.preprocessing.cleaning import build_quality_report, clean_dataset


@pytest.fixture
def result(raw_frame, mapping):
    return clean_dataset(raw_frame, mapping, {"date_format": "iso"})


def test_conservation_holds(result):
    assert result.conservation_ok
    assert result.rows_clean + result.rows_excluded == result.rows_raw


def test_each_problem_is_excluded_once_with_a_reason(result):
    assert result.excluded_by_reason == {
        "invalid_value": 1,       # 'not a date'
        "exact_duplicate": 1,
        "non_product_code": 1,    # POST
        "non_positive_price": 1,  # 0.00
    }


def test_returns_and_guests_are_kept_not_deleted(result):
    assert result.rows_clean == 4
    assert result.rows_returns == 1
    assert result.rows_guest == 1
    assert bool(result.frame["is_return"].any())


def test_revenue_is_derived_when_the_file_has_none(result):
    row = result.frame.loc[result.frame["invoice_id"] == "1001"].iloc[0]
    assert float(row["revenue"]) == pytest.approx(6.0)  # 2 x 3.00


def test_product_codes_get_one_canonical_name(result):
    names = set(result.frame.loc[result.frame["product_code"] == "22423", "product_name"])
    assert names == {"CAKE STAND"}  # 'cake stand' was folded in
    assert result.product_variants["22423"] == 2


def test_float_looking_identifiers_are_repaired(result):
    assert "504" in set(result.frame["customer_id"].dropna())


def test_duplicates_can_be_kept_when_the_option_is_off(raw_frame, mapping):
    result = clean_dataset(
        raw_frame, mapping, {"date_format": "iso", "drop_exact_duplicates": False}
    )
    assert "exact_duplicate" not in result.excluded_by_reason


def test_same_input_gives_the_same_fingerprint(raw_frame, mapping):
    first = clean_dataset(raw_frame, mapping, {"date_format": "iso"})
    second = clean_dataset(raw_frame, mapping, {"date_format": "iso"})
    assert first.fingerprint == second.fingerprint  # reproducibility (NFR-03)


def test_a_date_format_must_be_given(raw_frame, mapping):
    with pytest.raises(ValueError):
        clean_dataset(raw_frame, mapping, {})


def test_outliers_are_flagged_per_product_and_never_removed():
    rows = [
        [str(i), "SYN-1", "MUG", "3", f"2024-02-{(i % 28) + 1:02d} 09:00:00", "3.00", "501", "UK"]
        for i in range(40)
    ]
    rows.append(["999", "SYN-1", "MUG", "9000", "2024-02-20 09:00:00", "3.00", "501", "UK"])
    frame = pd.DataFrame(
        rows,
        columns=["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price",
                 "Customer ID", "Country"],
    ).astype("string")
    mapping = {
        "invoice_id": "Invoice", "product_code": "StockCode", "product_name": "Description",
        "quantity": "Quantity", "occurred_at": "InvoiceDate", "unit_price": "Price",
        "customer_id": "Customer ID", "region": "Country", "revenue": None, "category": None,
        "discount": None,
    }
    result = clean_dataset(frame, mapping, {"date_format": "iso"})
    assert result.rows_clean == 41            # nothing removed
    assert int(result.frame["is_outlier"].sum()) == 1


def test_partial_final_week_is_reported():
    rows = [
        [str(i), "SYN-1", "MUG", "2", f"{day} 09:00:00", "3.00", "501", "UK"]
        for i, day in enumerate(pd.date_range("2011-11-01", "2011-12-09").strftime("%Y-%m-%d"))
    ]
    frame = pd.DataFrame(
        rows,
        columns=["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price",
                 "Customer ID", "Country"],
    ).astype("string")
    mapping = {
        "invoice_id": "Invoice", "product_code": "StockCode", "product_name": "Description",
        "quantity": "Quantity", "occurred_at": "InvoiceDate", "unit_price": "Price",
        "customer_id": "Customer ID", "region": "Country", "revenue": None, "category": None,
        "discount": None,
    }
    result = clean_dataset(frame, mapping, {"date_format": "iso"})
    assert "PARTIAL_FINAL_WEEK" in {warning["code"] for warning in result.warnings}
    assert result.last_complete_week == pd.Timestamp("2011-11-28")


def test_report_has_everything_the_screen_shows(result, mapping):
    report = build_quality_report(result, mapping)
    assert report["conservation"]["ok"] is True
    assert report["scope"]["mode"] == "full"
    assert {a["step"] for a in report["actions"]} >= {
        "normalise_text", "invalid_value", "exact_duplicate", "non_product_code",
        "non_positive_price", "returns_flagged", "missing_customer_id",
        "canonical_product_names", "revenue_derived", "partial_periods", "closure_calendar",
    }
    assert all("rationale" in action for action in report["actions"])
    assert report["clean_data_sha256"] == result.fingerprint
