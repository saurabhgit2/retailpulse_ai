"""Reading uploaded CSV files.

Two habits that matter for real exports:

* **Encoding fallback.** Retail exports are often Windows-encoded, so a plain
  UTF-8 read raises UnicodeDecodeError on a single pound sign. We try UTF-8,
  then UTF-8 with a byte-order mark, then Latin-1 (which never fails) and
  report which one worked.
* **Everything is text first.** Columns are read as strings and converted
  later by the cleaning pipeline, so pandas cannot silently decide that a
  product code is a number and drop its leading zeros.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")


class CsvReadError(Exception):
    """The file could not be parsed as CSV at all."""


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


def read_header(path: Path) -> list[str]:
    frame, _ = read_csv(path, nrows=0)
    return [str(column) for column in frame.columns]
