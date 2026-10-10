"""Reconcile invoice counts between the raw file, the database and the profile.

Three numbers get quoted in the EDA chapter and they do not agree, which is
correct but needs explaining:

* **raw file** - every distinct `Invoice` value in the source file, including
  invoices that cleaning removes entirely;
* **after cleaning** - distinct invoices on the rows that survive. Compare this
  against `SELECT count(DISTINCT invoice_id)` in PostgreSQL; they should match;
* **orders** - distinct invoices with at least one *sale* line. This is what
  PROFILE.md calls Orders. The difference is invoices made up entirely of
  return lines.

Usage:

    python scripts/reconcile_invoices.py ../data/raw/online_retail_II.csv

The exclusion rules are **imported from the pipeline**, not restated here. An
earlier version of this script kept its own copy of the non-product code list,
which was four codes short, and the counts disagreed with the database by 85
invoices for no reason other than that. A reconciliation script that quietly
defines its own version of the thing it is reconciling against is worse than no
script at all, because it looks authoritative while being wrong.

What this script still does *not* model, and why the remaining gap (if any) is
expected rather than alarming:

* **step 2**, rows whose date or numbers cannot be read. Removing those can only
  remove a whole invoice if every line of it is unreadable.
* **step 3**, exact duplicate rows. These cannot remove an invoice entirely:
  `invoice_id` is one of the compared columns, so a duplicate always has a
  surviving first copy under the same invoice number.

Both are stated in the write-up rather than coded around. `app/preprocessing/
cleaning.py` remains the single source of truth for what cleaning does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.preprocessing.field_guide import NON_PRODUCT_CODES  # noqa: E402

COLUMNS = ["Invoice", "StockCode", "Quantity", "Price", "Customer ID"]
EXCLUDED_CODES = {code.upper() for code in NON_PRODUCT_CODES}


def _load(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        sheets = pd.read_excel(path, sheet_name=None)
        frame = pd.concat(sheets.values(), ignore_index=True)
    else:
        frame = pd.read_csv(
            path, usecols=COLUMNS, dtype={"Invoice": "string", "StockCode": "string"}
        )
    frame["Invoice"] = frame["Invoice"].astype("string").str.strip()
    frame["StockCode"] = frame["StockCode"].astype("string").str.strip().str.upper()
    frame["Quantity"] = pd.to_numeric(frame["Quantity"], errors="coerce")
    frame["Price"] = pd.to_numeric(frame["Price"], errors="coerce")
    return frame


def reconcile(path: Path) -> dict[str, object]:
    frame = _load(path)

    raw_invoices = set(frame["Invoice"].dropna())

    product = frame[~frame["StockCode"].isin(EXCLUDED_CODES)]
    priced = product[product["Price"].notna() & (product["Price"] > 0)]
    kept_invoices = set(priced["Invoice"].dropna())

    sale_invoices = set(priced[priced["Quantity"] > 0]["Invoice"].dropna())

    # Which rule removed each lost invoice, so the gap is explainable rather
    # than a single unattributed number.
    lost_to_codes = raw_invoices - set(product["Invoice"].dropna())
    lost_to_price = raw_invoices - kept_invoices - lost_to_codes

    return {
        "rows": len(frame),
        "raw_invoices": len(raw_invoices),
        "invoices_after_cleaning": len(kept_invoices),
        "invoices_with_a_sale_line": len(sale_invoices),
        "lost_to_non_product_codes": len(lost_to_codes),
        "lost_to_non_positive_price": len(lost_to_price),
        "return_only_invoices": len(kept_invoices - sale_invoices),
        "codes_applied": sorted(EXCLUDED_CODES),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: python {Path(sys.argv[0]).name} <path to raw file>")
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    counts = reconcile(path)

    print(f"\n{path.name}  -  {counts['rows']:,} rows")
    print(f"Non-product codes applied: {', '.join(counts['codes_applied'])}\n")
    print(f"  Distinct invoices in the raw file          {counts['raw_invoices']:>8,}")
    print(f"    less fee / adjustment-only invoices      {-counts['lost_to_non_product_codes']:>8,}")
    print(f"    less zero-price-only invoices            {-counts['lost_to_non_positive_price']:>8,}")
    print(f"  Distinct invoices after cleaning           {counts['invoices_after_cleaning']:>8,}"
          "   <- compare with PostgreSQL")
    print(f"    less return-only invoices                {-counts['return_only_invoices']:>8,}")
    print(f"  Invoices with at least one sale line       {counts['invoices_with_a_sale_line']:>8,}"
          "   <- PROFILE.md Orders\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
