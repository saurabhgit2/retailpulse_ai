"""Convert a workbook to CSV.

The app reads .xlsx directly, but openpyxl is slow on a file the size of Online
Retail II (about a million rows across two sheets): expect minutes, and a lot of
memory. Converting once to CSV makes every later upload and re-processing run
several times faster.

    python scripts/excel_to_csv.py ../data/raw/online_retail_II.xlsx

Writes `online_retail_II.csv` beside the workbook, with every matching sheet
stacked into one file and a `source_sheet` column so the two years stay
distinguishable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def convert(source: Path, destination: Path | None, keep_sheet_column: bool) -> Path:
    if not source.exists():
        raise SystemExit(f"File not found: {source}")

    print(f"Reading {source.name} ... (this can take a few minutes)")
    sheets = pd.read_excel(source, sheet_name=None, dtype="string", engine="openpyxl")

    usable = [(name, frame) for name, frame in sheets.items() if not frame.empty]
    if not usable:
        raise SystemExit("The workbook has no rows.")

    reference_name, reference = usable[0]
    reference_columns = list(reference.columns)
    frames, skipped = [], []

    for name, frame in usable:
        if list(frame.columns) == reference_columns:
            if keep_sheet_column:
                frame = frame.assign(source_sheet=name)
            frames.append(frame)
            print(f"  {name}: {len(frame):,} rows")
        else:
            skipped.append(name)

    if skipped:
        print(f"  skipped (different columns): {', '.join(skipped)}")

    combined = pd.concat(frames, ignore_index=True)
    out = destination or source.with_suffix(".csv")
    combined.to_csv(out, index=False, encoding="utf-8")
    print(f"\nWrote {len(combined):,} rows to {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert an Excel workbook to one CSV.")
    parser.add_argument("source", type=Path, help="path to the .xlsx file")
    parser.add_argument("--out", type=Path, default=None, help="output .csv path")
    parser.add_argument(
        "--no-sheet-column",
        action="store_true",
        help="do not add a source_sheet column naming the sheet each row came from",
    )
    args = parser.parse_args()
    convert(args.source, args.out, keep_sheet_column=not args.no_sheet_column)


if __name__ == "__main__":
    sys.exit(main())
