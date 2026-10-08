"""Reading CSV and Excel.

Excel matters because Online Retail II is distributed as a workbook with one
sheet per year, and a capstone should not require the user to convert their own
dataset before the tool will look at it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.preprocessing.csv_io import (
    EXCEL_SOURCE,
    CsvReadError,
    read_header,
    read_table,
    sheet_names,
)
from app.preprocessing.validation import upload_suffix, validate_upload_filename

COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate",
           "Price", "Customer ID", "Country"]


@pytest.fixture
def workbook(tmp_path):
    """Two year-sheets with matching columns, plus an unrelated notes sheet."""
    first = pd.DataFrame(
        [["1001", "85123A", "WHITE MUG", 2, "2009-12-01 09:00:00", 3.0, "501", "United Kingdom"]] * 3,
        columns=COLUMNS,
    )
    second = pd.DataFrame(
        [["2001", "22423", "CAKE STAND", 1, "2010-12-01 09:00:00", 2.5, "502", "France"]] * 4,
        columns=COLUMNS,
    )
    notes = pd.DataFrame([["x", "y"]], columns=["Other", "Shape"])

    path = tmp_path / "online_retail_II.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        first.to_excel(writer, sheet_name="Year 2009-2010", index=False)
        second.to_excel(writer, sheet_name="Year 2010-2011", index=False)
        notes.to_excel(writer, sheet_name="Notes", index=False)
    return path


def test_sheets_with_matching_columns_are_stacked(workbook):
    frame, source = read_table(workbook)
    assert source == EXCEL_SOURCE
    assert len(frame) == 7                  # 3 + 4
    assert list(frame.columns) == COLUMNS


def test_a_sheet_with_different_columns_is_skipped_not_merged(workbook):
    frame, _ = read_table(workbook)
    assert "Other" not in frame.columns


def test_workbook_values_are_read_as_text_like_csv(workbook):
    """Text-first keeps leading zeros on product codes and stops pandas
    guessing types before the cleaning pipeline has had its say."""
    frame, _ = read_table(workbook)
    assert all(str(dtype) == "string" for dtype in frame.dtypes)


def test_the_header_can_be_read_without_any_rows(workbook):
    assert read_header(workbook) == COLUMNS


def test_sheet_names_are_reported(workbook):
    assert sheet_names(workbook) == ["Year 2009-2010", "Year 2010-2011", "Notes"]


def test_selecting_columns_works_across_sheets(workbook):
    """usecols cannot be passed to pandas here: it is applied to *every* sheet,
    so the unrelated notes sheet would make the whole read fail."""
    frame, _ = read_table(workbook, columns=["Invoice", "Quantity"])
    assert list(frame.columns) == ["Invoice", "Quantity"]
    assert len(frame) == 7


def test_asking_for_a_column_no_sheet_has_is_an_error(workbook):
    with pytest.raises(CsvReadError):
        read_table(workbook, columns=["Nope"])


def test_row_limits_apply_to_the_combined_result(workbook):
    frame, _ = read_table(workbook, nrows=2)
    assert len(frame) == 2


def test_csv_reading_is_unchanged(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    frame, encoding = read_table(path)
    assert encoding == "utf-8"
    assert frame.shape == (1, 2)


def test_a_windows_encoded_csv_falls_back_rather_than_failing(tmp_path):
    path = tmp_path / "latin.csv"
    path.write_bytes("name,price\ncaf\xe9,1.50\n".encode("latin-1"))
    frame, encoding = read_table(path)
    assert encoding == "latin-1"
    assert frame.iloc[0, 0] == "café"


def test_excel_filenames_are_accepted_on_upload():
    assert validate_upload_filename("online_retail_II.xlsx")
    assert validate_upload_filename("sales.csv")
    assert upload_suffix("ONLINE_RETAIL_II.XLSX") == ".xlsx"


def test_unsupported_filenames_are_refused():
    with pytest.raises(Exception):
        validate_upload_filename("report.pdf")
