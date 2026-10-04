"""Generate a SYNTHETIC retail dataset for development and tests.

Everything it produces is invented: products, customers, prices, dates. It is
labelled SYNTHETIC in the filename and in a header comment, and datasets
uploaded from it should be marked synthetic so no screen ever presents its
numbers as real findings (brief §33).

It deliberately contains the problems the pipeline must handle:
duplicates, cancellations, missing customer IDs, zero prices, fee lines,
unreadable dates and a few very large orders.

    python scripts/generate_synthetic_data.py --rows 40000 --out ../data/sample

The data has a trend, weekly seasonality and a Q4 lift, so it is also usable
for the forecasting work in Phase 5.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PRODUCTS = [
    ("SYN-001", "SYNTHETIC CERAMIC MUG", 3.50),
    ("SYN-002", "SYNTHETIC LINEN TEA TOWEL", 4.25),
    ("SYN-003", "SYNTHETIC SCENTED CANDLE", 9.99),
    ("SYN-004", "SYNTHETIC GLASS JAR, LARGE", 5.75),
    ("SYN-005", "SYNTHETIC WOODEN COASTER SET", 6.50),
    ("SYN-006", "SYNTHETIC GIFT WRAP ROLL", 1.95),
    ("SYN-007", "SYNTHETIC PAPER LANTERN", 2.80),
    ("SYN-008", "SYNTHETIC ENAMEL TIN", 7.25),
    ("SYN-009", "SYNTHETIC COTTON TOTE BAG", 3.10),
    ("SYN-010", "SYNTHETIC PHOTO FRAME", 8.40),
    ("SYN-011", "SYNTHETIC STRING LIGHTS", 11.50),
    ('SYN-012', 'SYNTHETIC NOTEBOOK "A5"', 2.20),
]
COUNTRIES = ["United Kingdom"] * 82 + ["France"] * 6 + ["Germany"] * 5 + \
            ["Netherlands"] * 4 + ["Ireland"] * 3


def generate(rows: int, seed: int, start: str, months: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    begin = pd.Timestamp(start)
    end = begin + pd.DateOffset(months=months)
    span_days = (end - begin).days

    # A slow upward trend, a weekend dip and a pre-Christmas lift give the
    # series something for later phases to forecast.
    day_offsets = rng.integers(0, span_days, size=rows)
    dates = begin + pd.to_timedelta(day_offsets, unit="D")
    weights = (
        1.0
        + 0.35 * (dates.month.isin([11, 12]))          # Q4 lift
        - 0.25 * (dates.dayofweek >= 5)                # quieter weekends
        + 0.30 * (day_offsets / max(span_days, 1))     # growth over time
    )
    keep = rng.random(rows) < (weights / weights.max())
    dates = dates[keep]
    n = len(dates)

    product_index = rng.integers(0, len(PRODUCTS), size=n)
    codes = [PRODUCTS[i][0] for i in product_index]
    names = [PRODUCTS[i][1] for i in product_index]
    prices = np.array([PRODUCTS[i][2] for i in product_index])

    # Most orders are small; a few are wholesale-sized.
    quantity = np.maximum(1, (rng.gamma(2.0, 2.5, size=n)).astype(int))
    invoice = 700000 + (rng.integers(0, max(n // 3, 1), size=n))
    customer = rng.integers(40000, 40400, size=n).astype(object)
    hours = rng.integers(7, 18, size=n)
    minutes = rng.integers(0, 60, size=n)

    frame = pd.DataFrame(
        {
            "Invoice": [str(i) for i in invoice],
            "StockCode": codes,
            "Description": names,
            "Quantity": quantity,
            "InvoiceDate": (
                dates + pd.to_timedelta(hours, unit="h") + pd.to_timedelta(minutes, unit="m")
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "Price": prices,
            "Customer ID": [f"{c}.0" for c in customer],
            "Country": rng.choice(COUNTRIES, size=n),
        }
    )

    # --- deliberate data-quality problems -----------------------------------
    guests = rng.random(n) < 0.20                    # missing customer IDs
    frame.loc[guests, "Customer ID"] = ""

    cancels = rng.random(n) < 0.02                   # cancellations
    frame.loc[cancels, "Invoice"] = "C" + frame.loc[cancels, "Invoice"]
    frame.loc[cancels, "Quantity"] = -frame.loc[cancels, "Quantity"]

    free = rng.random(n) < 0.005                     # zero-price lines
    frame.loc[free, "Price"] = 0.0

    broken = rng.random(n) < 0.003                   # unreadable dates
    frame.loc[broken, "InvoiceDate"] = "2024-13-45 10:00:00"

    huge = rng.random(n) < 0.002                     # very large orders
    frame.loc[huge, "Quantity"] = frame.loc[huge, "Quantity"] * 500

    fees = frame.sample(frac=0.01, random_state=seed).copy()  # postage lines
    fees["StockCode"] = "POST"
    fees["Description"] = "POSTAGE"
    fees["Quantity"] = 1
    fees["Price"] = 18.00

    duplicates = frame.sample(frac=0.02, random_state=seed + 1)  # exact duplicates

    combined = pd.concat([frame, fees, duplicates], ignore_index=True)
    return combined.sort_values("InvoiceDate").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic retail CSV.")
    parser.add_argument("--rows", type=int, default=40000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "data" / "sample"))
    args = parser.parse_args()

    frame = generate(args.rows, args.seed, args.start, args.months)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "SYNTHETIC_retail_sales.csv"
    frame.to_csv(path, index=False)

    (out_dir / "README.md").write_text(
        "# Sample data\n\n"
        "`SYNTHETIC_retail_sales.csv` is **invented data** produced by\n"
        "`backend/scripts/generate_synthetic_data.py`. It exists so the pipeline can be\n"
        "developed and tested without a real dataset.\n\n"
        "It is not a sample of Online Retail II and must never be presented as a\n"
        "real-world result. Mark it as synthetic when uploading.\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(frame):,} rows to {path}")


if __name__ == "__main__":
    main()
