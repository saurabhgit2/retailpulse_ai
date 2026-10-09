"""Reading uploaded data files.

Two habits that matter for real exports:

* **Encoding fallback.** Retail exports are often Windows-encoded, so a plain
  UTF-8 read raises UnicodeDecodeError on a single pound sign. We try UTF-8,
  then UTF-8 with a byte-order mark, then Latin-1 (which never fails) and
  report which one worked.
* **Everything is text first.** Columns are read as strings and converted
  later by the cleaning pipeline, so pandas cannot silently decide that a
  product code is a number and drop its leading zeros.

Excel is supported because that is how Online Retail II is distributed: one
workbook with a sheet per year ("Year 2009-2010", "Year 2010-2011"). Sheets
whose header matches the first sheet are concatenated, so the two years arrive
as one dataset; a sheet with a different shape is skipped and reported rather
than silently mangled.

Call `read_table`, which dispatches on the file extension. `read_csv` remains
for callers that know they have a CSV.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
# .txt is deliberately not accepted: nothing in this project needs it, and
# widening the upload surface for no reason is how a validator stops being
# a validator.
CSV_SUFFIXES = (".csv",)
SUPPORTED_SUFFIXES = CSV_SUFFIXES + EXCEL_SUFFIXES

# Reported in place of an encoding when the source was a workbook: Excel files
# carry their own encoding internally, so "which encoding worked" is not a
# question that applies to them.
EXCEL_SOURCE = "excel"


class CsvReadError(Exception):
    """The file could not be parsed as a table at all."""


def read_table(
    path: Path, *, columns: list[str] | None = None, nrows: int | None = None
) -> tuple[pd.DataFrame, str]:
    """Read a CSV or Excel file as text columns.

    Returns (frame, source) where source is the encoding that worked for a CSV,
    or "excel" for a workbook.
    """
    if Path(path).suffix.lower() in EXCEL_SUFFIXES:
        return read_excel(path, columns=columns, nrows=nrows)
    return read_csv(path, columns=columns, nrows=nrows)


def read_csv(
    path: Path, *, columns: list[str] | None = None, nrows: int | None = None
) -> tuple[pd.DataFrame, str]:
    """Return (frame of text columns, encoding used)."""
    last_error: Exception | None = None

    for encoding in ENCODINGS:
        try:
            frame = pd.read_csv(
                path,
                dtype="string",       # keep every value as text
                keep_default_na=True,
                encoding=encoding,
                usecols=columns,      # read only the mapped columns: less memory, faster
                nrows=nrows,
                skipinitialspace=True,
                on_bad_lines="warn",  # a malformed line is reported, not fatal
            )
            return frame, encoding
        except UnicodeDecodeError as error:
            last_error = error
            continue
        except ValueError as error:
            # usecols names that are not in the file, or an unparseable structure
            raise CsvReadError(str(error)) from error
        except pd.errors.ParserError as error:
            raise CsvReadError(str(error)) from error

    raise CsvReadError(f"The file could not be decoded as text ({last_error}).")


def read_excel(
    path: Path, *, columns: list[str] | None = None, nrows: int | None = None
) -> tuple[pd.DataFrame, str]:
    """Read every sheet of a workbook and stack the ones that share a header.

    Online Retail II splits its two years across two sheets with identical
    columns, so the natural reading of "the dataset" is both sheets together.
    """
    try:
        # usecols is deliberately NOT passed here: pandas applies it to every
        # sheet, so one unrelated sheet (a "Notes" tab) makes the whole read
        # fail. Columns are selected after the matching sheets are stacked.
        sheets = pd.read_excel(
            path,
            sheet_name=None,          # every sheet, as {name: DataFrame}
            dtype="string",           # text first, exactly as for CSV
            nrows=nrows,
            engine="openpyxl",
        )
    except ImportError as error:  # openpyxl missing
        raise CsvReadError(
            "Reading .xlsx files needs the openpyxl package: pip install openpyxl"
        ) from error
    except ValueError as error:
        # usecols naming a column no sheet has, or a corrupt workbook
        raise CsvReadError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - openpyxl raises its own types
        raise CsvReadError(f"The workbook could not be read ({error}).") from error

    # A sheet with no columns at all is empty in every sense. A sheet with
    # columns but no rows is kept when nrows=0, because that call is asking for
    # the header only (read_header).
    usable = [
        (name, frame)
        for name, frame in sheets.items()
        if len(frame.columns) > 0 and (nrows == 0 or not frame.empty)
    ]
    if not usable:
        raise CsvReadError("The workbook has no readable sheets.")

    # The first non-empty sheet defines the expected header; later sheets must
    # match it to be stacked. Anything else would silently invent columns.
    reference_name, reference = usable[0]
    reference_columns = list(reference.columns)
    frames = [reference]
    skipped: list[str] = []

    for name, frame in usable[1:]:
        if list(frame.columns) == reference_columns:
            frames.append(frame)
        else:
            skipped.append(name)

    if skipped:
        logger.warning(
            "Workbook sheets skipped because their columns differ from %r: %s",
            reference_name, ", ".join(skipped),
        )

    combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    if columns is not None:
        missing = [column for column in columns if column not in combined.columns]
        if missing:
            # Same failure the CSV path gives for an unknown usecols name.
            raise CsvReadError(
                "Columns expected but not found: " + ", ".join(repr(m) for m in missing)
            )
        combined = combined[columns]

    if nrows is not None and len(combined) > nrows:
        # nrows applies per sheet in pandas; trim so the caller gets what it asked for.
        combined = combined.head(nrows)
    return combined, EXCEL_SOURCE


def read_header(path: Path) -> list[str]:
    frame, _ = read_table(path, nrows=0)
    return [str(column) for column in frame.columns]


def sheet_names(path: Path) -> list[str]:
    """Sheet names in a workbook, for reporting. Empty list for a CSV."""
    if Path(path).suffix.lower() not in EXCEL_SUFFIXES:
        return []
    try:
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            return list(workbook.sheet_names)
    except Exception as error:  # noqa: BLE001
        raise CsvReadError(f"The workbook could not be opened ({error}).") from error
