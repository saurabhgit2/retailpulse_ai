"""Profile a retail dataset and write an EDA report.

This is the research-side companion to the web app, and it is the point of the
"pure core" rule: it imports `app.preprocessing` and `app.analytics` directly,
runs **no** web framework and touches **no** database, and therefore produces
exactly the same numbers the dashboard shows. If the report and the screen ever
disagreed, one of them would be wrong - here they cannot.

    python scripts/profile_dataset.py ../data/raw/online_retail_II.xlsx
    python scripts/profile_dataset.py ../data/sample/SYNTHETIC_retail_sales.csv --synthetic

Writes a `PROFILE.md` plus supporting CSVs into the output directory. Figures
you can quote in the methodology chapter; the CSVs are there so a table can be
regenerated without re-running the whole thing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics import breakdowns, distributions, entropy, kpis, rfm, series_profile, trends  # noqa: E402
from app.analytics import seasonality as seasonality_core  # noqa: E402
from app.preprocessing.cleaning import build_quality_report, clean_dataset  # noqa: E402
from app.preprocessing.csv_io import CsvReadError, read_table, sheet_names  # noqa: E402
from app.preprocessing.schema_detection import build_upload_profile  # noqa: E402


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:,.2f}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _table(rows: list[list[str]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def profile(path: Path, out_dir: Path, *, synthetic: bool, date_format: str | None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)

    print(f"Reading {path.name} ...")
    try:
        raw, source = read_table(path)
    except CsvReadError as error:
        raise SystemExit(f"Could not read the file: {error}") from error
    print(f"  {len(raw):,} rows x {raw.shape[1]} columns (read as {source})")

    print("Detecting columns ...")
    upload_profile = build_upload_profile(raw, rows_examined=len(raw), file_truncated=False)
    mapping = upload_profile["suggested_mapping"]
    mapped = {k: v for k, v in mapping.items() if v}
    print("  " + ", ".join(f"{k} <- {v}" for k, v in mapped.items()))

    options: dict[str, object] = {}
    if date_format:
        options["date_format"] = date_format
    else:
        detected = upload_profile.get("date_format") or "iso"
        options["date_format"] = detected
        print(f"  date format: {detected}")

    print("Cleaning ...")
    result = clean_dataset(raw, mapping, options)
    report = build_quality_report(result, mapping)
    frame = result.frame
    print(f"  {result.rows_clean:,} kept, {result.rows_excluded:,} excluded "
          f"(conservation {'holds' if result.conservation_ok else 'FAILS'})")

    # --- aggregates, using the same code the API uses ------------------------
    gross = float(frame.loc[~frame["is_return"], "revenue"].sum())
    returns = float(abs(frame.loc[frame["is_return"], "revenue"].sum()))
    totals = kpis.PeriodTotals(
        gross_revenue=gross,
        returns_value=returns,
        units=float(frame.loc[~frame["is_return"], "quantity"].sum()),
        orders=int(frame.loc[~frame["is_return"], "invoice_id"].nunique()),
        active_customers=int(frame["customer_id"].nunique(dropna=True)),
        guest_revenue=float(
            frame.loc[~frame["is_return"] & frame["customer_id"].isna(), "revenue"].sum()
        ),
        lines=int(len(frame)),
    )
    kpi_block = kpis.build_kpis(totals)

    weekly = (
        frame.assign(period=trends.week_start(frame["occurred_at"]))
        .groupby("period", as_index=False)
        .agg(gross_revenue=("revenue", "sum"), units=("quantity", "sum"),
             orders=("invoice_id", "nunique"))
    )
    trend = trends.build_trend(weekly, "week", data_max=frame["occurred_at"].max())
    seasonality = {
        "calendar": seasonality_core.calendar_indices(
            frame.assign(period=frame["occurred_at"].dt.floor("D"),
                         hour=frame["occurred_at"].dt.hour)
            .groupby(["period", "hour"], as_index=False)
            .agg(gross_revenue=("revenue", "sum"))
        ),
        "decomposition": seasonality_core.weekly_seasonality(weekly),
    }

    by_product = (
        frame[~frame["is_return"]]
        .groupby("product_code", as_index=False)
        .agg(gross_revenue=("revenue", "sum"), units=("quantity", "sum"),
             orders=("invoice_id", "nunique"), label=("product_name", "first"))
    )
    products = breakdowns.rank_breakdown(
        by_product, key="product_code", limit=20, label_column="label"
    )

    regions = None
    if "region" in frame.columns and frame["region"].notna().any():
        by_region = (
            frame[~frame["is_return"]]
            .groupby("region", as_index=False)
            .agg(gross_revenue=("revenue", "sum"), units=("quantity", "sum"),
                 orders=("invoice_id", "nunique"))
        )
        regions = breakdowns.rank_breakdown(by_region, key="region", limit=15)

    order_values = frame[~frame["is_return"]].groupby("invoice_id")["revenue"].sum()
    distribution_blocks = {
        "line_revenue": distributions.describe_distribution(
            frame.loc[~frame["is_return"], "revenue"], field="line_revenue"),
        "quantity": distributions.describe_distribution(
            frame.loc[~frame["is_return"], "quantity"], field="quantity"),
        "unit_price": distributions.describe_distribution(
            frame.loc[~frame["is_return"], "unit_price"], field="unit_price"),
        "order_value": distributions.describe_distribution(order_values, field="order_value"),
    }

    # Entropy of the categorical context features (§12.7)
    context = frame.assign(
        day_of_week=frame["occurred_at"].dt.day_name(),
        month=frame["occurred_at"].dt.month_name(),
        hour=frame["occurred_at"].dt.hour.astype("string"),
        customer_kind=frame["customer_id"].isna().map({True: "guest", False: "registered"}),
    )
    entropy_rows = []
    for column in ("region", "product_code", "day_of_week", "month", "hour", "customer_kind"):
        if column in context.columns and context[column].notna().any():
            entropy_rows.append(
                entropy.profile_categorical(context, column, context["revenue"]).as_dict()
            )

    weekly_sku = (
        frame[~frame["is_return"]]
        .assign(period=trends.week_start(frame["occurred_at"]))
        .groupby(["product_code", "period"], as_index=False)
        .agg(units=("quantity", "sum"))
    )
    top_codes = by_product.nlargest(300, "gross_revenue")["product_code"]
    series = series_profile.profile_many(
        weekly_sku[weekly_sku["product_code"].isin(top_codes)], min_periods=26
    )

    # Basket size: Chen, Sain & Guo (2012) read 18.3 distinct items per
    # transaction on this retailer as evidence of organisational customers.
    sold = frame[~frame["is_return"]]
    baskets = sold.groupby("invoice_id").agg(
        distinct_items=("product_code", "nunique"),
        units=("quantity", "sum"),
        revenue=("revenue", "sum"),
    )
    basket_items = distributions.describe_distribution(
        baskets["distinct_items"], field="distinct_items_per_invoice"
    )

    # RFM per customer, following the same paper's aggregation.
    identified = frame[frame["customer_id"].notna()]
    rfm_block = {"available": False, "reason": "No identified customers."}
    if not identified.empty:
        customers = identified.groupby("customer_id").agg(
            first_purchase=("occurred_at", "min"),
            last_purchase=("occurred_at", "max"),
            frequency=("invoice_id", "nunique"),
            lines=("revenue", "size"),
        )
        customers["monetary_gross"] = (
            identified[~identified["is_return"]].groupby("customer_id")["revenue"].sum()
        )
        customers["returns_value"] = (
            identified[identified["is_return"]].groupby("customer_id")["revenue"].sum().abs()
        )
        customers = customers.fillna({"monetary_gross": 0.0, "returns_value": 0.0}).reset_index()
        rfm_block = rfm.build_rfm(customers)

    # --- write the outputs ---------------------------------------------------
    pd.DataFrame(products["items"]).to_csv(out_dir / "top_products.csv", index=False)
    weekly.to_csv(out_dir / "weekly_totals.csv", index=False)
    pd.DataFrame(entropy_rows).to_csv(out_dir / "entropy.csv", index=False)
    if rfm_block.get("available"):
        pd.DataFrame(rfm_block["table"]).to_csv(out_dir / "rfm.csv", index=False)
    if series.get("series"):
        pd.DataFrame(series["series"]).to_csv(out_dir / "series_profiles.csv", index=False)
    (out_dir / "quality_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    label = " **(SYNTHETIC DATA - not a real-world finding)**" if synthetic else ""
    values = kpi_block["values"]
    elapsed = (datetime.now(UTC) - started).total_seconds()

    lines = [
        f"# Data profile: {path.name}{label}",
        "",
        f"Generated {started.date().isoformat()} by `scripts/profile_dataset.py` "
        f"in {elapsed:.0f}s. Pipeline version `{report['pipeline_version']}`, "
        f"clean-data fingerprint `{result.fingerprint[:16]}...`.",
        "",
    ]
    if synthetic:
        lines += [
            "> **This dataset is synthetic.** Every figure below is invented and must "
            "not be presented as a real-world result.",
            "",
        ]
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        lines += [f"Workbook sheets: {', '.join(sheet_names(path))}.", ""]

    lines += [
        "## 1. Shape and cleaning",
        "",
        _table([
            ["Rows in file", f"{result.rows_raw:,}"],
            ["Rows kept", f"{result.rows_clean:,}"],
            ["Rows excluded", f"{result.rows_excluded:,}"],
            ["Conservation holds", "yes" if result.conservation_ok else "**NO**"],
            ["Columns in file", str(raw.shape[1])],
            ["Date range", f"{frame['occurred_at'].min()} to {frame['occurred_at'].max()}"],
            ["Distinct products", f"{frame['product_code'].nunique():,}"],
            ["Distinct customers", f"{frame['customer_id'].nunique(dropna=True):,}"],
            ["Guest lines", f"{int(frame['customer_id'].isna().sum()):,}"],
            ["Return lines", f"{int(frame['is_return'].sum()):,}"],
            ["Outlier lines flagged", f"{int(frame['is_outlier'].sum()):,}"],
        ], ["Measure", "Value"]),
        "",
        "### Why rows were excluded",
        "",
        _table(
            [[reason, f"{count:,}"] for reason, count in report["excluded_by_reason"].items()]
            or [["(none)", "0"]],
            ["Reason", "Rows"],
        ),
        "",
        "## 2. Headline figures",
        "",
        _table([
            ["Gross revenue", _money(values["gross_revenue"])],
            ["Returns value", _money(values["returns_value"])],
            ["Net revenue", _money(values["net_revenue"])],
            ["Units", _money(values["units"])],
            ["Orders", f"{values['orders']:,}"],
            ["Average order value", _money(values["average_order_value"])],
            ["Active customers", f"{values['active_customers']:,}"],
            ["Return rate", _pct(values["return_rate"])],
            ["Guest revenue share", _pct(values["guest_revenue_share"])],
        ], ["KPI", "Value"]),
        "",
        "## 3. Distributions",
        "",
        "Mean and median are shown together: a mean far above the median is the "
        "signature of the long right tail that retail money always has.",
        "",
        _table([
            [
                name,
                f"{block['summary']['mean']:,.2f}",
                f"{block['summary']['median']:,.2f}",
                f"{block['summary']['skewness']:.2f}",
                f"{block['percentiles']['99']:,.2f}",
                f"{block['outliers']['tukey_count']:,}",
            ]
            for name, block in distribution_blocks.items() if block["summary"]
        ], ["Variable", "Mean", "Median", "Skewness", "99th pct", "Tukey outliers"]),
        "",
        "## 4. Time and seasonality",
        "",
        _table([
            ["Weekly points", str(len(trend["points"]))],
            ["Complete weeks", str(trend["complete_points"])],
            ["Partial weeks", str(trend["partial_points"])],
            ["Decomposition available",
             "yes" if seasonality["decomposition"].get("available") else "no"],
            ["Seasonal period", str(seasonality["decomposition"].get("period", "-"))],
            ["Cycles of history",
             f"{seasonality['decomposition'].get('cycles', 0):.1f}"],
            ["Seasonal strength",
             f"{seasonality['decomposition'].get('seasonal_strength') or 0:.3f}"],
        ], ["Measure", "Value"]),
        "",
    ]
    if seasonality["decomposition"].get("seasonal_estimate_note"):
        lines += [f"> {seasonality['decomposition']['seasonal_estimate_note']}", ""]

    lines += [
        "### Day-of-week index (1.0 = an average day)",
        "",
        _table([
            [row["label"], f"{row['index']:.2f}" if row["index"] else "-",
             f"{row['observations']:,}"]
            for row in seasonality["calendar"]["day_of_week"]
        ], ["Day", "Index", "Observations"]),
        "",
        "## 5. Concentration",
        "",
        _table([
            ["Products", f"{products['concentration']['entities']:,}",
             _pct(products["concentration"]["top_share"]),
             f"{products['concentration']['gini']:.3f}"],
        ] + ([
            ["Regions", f"{regions['concentration']['entities']:,}",
             _pct(regions["concentration"]["top_share"]),
             f"{regions['concentration']['gini']:.3f}"],
        ] if regions else []),
            ["Dimension", "Entities", "Top 20% share", "Gini"]),
        "",
        "### Top 10 products by revenue",
        "",
        _table([
            [str(item["rank"]), str(item["key"]), str(item.get("label") or "-"),
             _money(item["gross_revenue"]), _pct(item["share"]),
             _pct(item["cumulative_share"])]
            for item in products["items"][:10]
        ], ["#", "Code", "Description", "Revenue", "Share", "Cumulative"]),
        "",
        "## 6. Entropy of categorical features",
        "",
        "Normalised entropy is H / log2(k), so features with different numbers of "
        "categories are comparable. Low means one value dominates.",
        "",
        _table([
            [row["feature"], f"{row['distinct_values']:,}",
             f"{row['entropy_bits']:.3f}", f"{row['normalised_entropy']:.3f}",
             f"{row['mutual_information_bits']:.3f}" if row["mutual_information_bits"] is not None else "-"]
            for row in entropy_rows
        ], ["Feature", "Categories", "H (bits)", "Normalised H", "I(revenue; X)"]),
        "",
        "## 7. Series forecastability (top 300 products by revenue)",
        "",
    ]
    if series.get("summary"):
        lines += [
            _table([
                ["Series profiled", f"{series['series_count']:,}"],
                ["Median weeks of history", f"{series['summary']['median_periods']:.0f}"],
                ["Median zero-week share", _pct(series["summary"]["median_zero_share"])],
                ["Median ADI", f"{series['summary']['median_adi']:.2f}"],
                ["Median CV squared", f"{series['summary']['median_cv_squared']:.2f}"],
                ["Median spectral entropy",
                 f"{series['summary']['median_spectral_entropy']:.3f}"
                 if series["summary"]["median_spectral_entropy"] else "-"],
            ], ["Measure", "Value"]),
            "",
            "Intermittency classes (Syntetos-Boylan):",
            "",
            _table([[name, f"{count:,}"] for name, count in series["classes"].items()],
                   ["Class", "Series"]),
            "",
        ]
    else:
        lines += [f"Not available: {series.get('reason', 'no series met the minimum length')}.", ""]

    lines += [
        "## 8. Basket size",
        "",
        _table([
            ["Invoices", f"{len(baskets):,}"],
            ["Mean distinct items per invoice", f"{basket_items['summary']['mean']:.1f}"],
            ["Median distinct items per invoice", f"{basket_items['summary']['median']:.0f}"],
            ["90th percentile", f"{basket_items['percentiles']['90']:.0f}"],
            ["Mean units per invoice", f"{baskets['units'].mean():.1f}"],
        ], ["Measure", "Value"]),
        "",
        "Chen, Sain and Guo (2012) report 18.3 distinct items per transaction for this "
        "retailer and read it as evidence that the customers are largely organisations "
        "rather than individual consumers.",
        "",
        "## 9. RFM (Recency, Frequency, Monetary)",
        "",
    ]
    if rfm_block.get("available"):
        dist = rfm_block["distributions"]
        lines += [
            f"**{rfm_block['customers']:,} identified customers**, aggregated as of "
            f"{rfm_block['as_of']}. Frequency is {rfm_block['frequency_definition']}; "
            f"monetary is the {rfm_block['monetary_definition']}.",
            "",
            _table([
                ["Recency (days)", f"{dist['recency_days']['min']:.0f}",
                 f"{dist['recency_days']['median']:.0f}", f"{dist['recency_days']['max']:.0f}",
                 f"{dist['recency_days']['skewness']:.2f}"],
                ["Frequency (invoices)", f"{dist['frequency']['min']:.0f}",
                 f"{dist['frequency']['median']:.0f}", f"{dist['frequency']['max']:.0f}",
                 f"{dist['frequency']['skewness']:.2f}"],
                ["Monetary", f"{dist['monetary']['min']:,.2f}",
                 f"{dist['monetary']['median']:,.2f}", f"{dist['monetary']['max']:,.2f}",
                 f"{dist['monetary']['skewness']:.2f}"],
            ], ["Variable", "Min", "Median", "Max", "Skewness"]),
            "",
            "### Score-band groups (descriptive shorthand, not a clustering result)",
            "",
            _table([
                [row["segment"], f"{row['customers']:,}", _pct(row["customer_share"]),
                 _money(row["monetary"]), _pct(row["monetary_share"]),
                 f"{row['median_recency_days']:.0f}", f"{row['median_frequency']:.0f}"]
                for row in rfm_block["segments"]
            ], ["Group", "Customers", "Share", "Monetary", "Revenue share",
                "Median recency", "Median frequency"]),
            "",
            "### Before clustering (RQ2)",
            "",
        ] + [f"- {note}" for note in rfm_block["clustering_notes"]] + [
            "",
            f"Monetary Gini across customers: **{rfm_block['monetary_gini']:.3f}**; "
            f"the top 20% of customers account for "
            f"{_pct(rfm_block['concentration']['top_share'])} of monetary value.",
            "",
        ]
    else:
        lines += [f"Not available: {rfm_block.get('reason')}.", ""]

    lines += [
        "## 10. Files written",
        "",
        "- `top_products.csv`",
        "- `weekly_totals.csv`",
        "- `entropy.csv`",
        "- `rfm.csv` - Recency, Frequency, Monetary and scores per customer",
        "- `series_profiles.csv`",
        "- `quality_report.json` - every cleaning action, with counts and examples",
        "",
        "---",
        "",
        "Produced by the same `app.analytics` and `app.preprocessing` modules the "
        "application uses, so these figures and the dashboard cannot disagree.",
    ]

    destination = out_dir / "PROFILE.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile a retail dataset (EDA report).")
    parser.add_argument("path", type=Path, help="CSV or Excel file")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument("--synthetic", action="store_true",
                        help="label every figure as synthetic")
    parser.add_argument("--date-format", default=None,
                        choices=["iso", "dmy", "mdy"],
                        help="override the detected date format")
    args = parser.parse_args()

    if not args.path.exists():
        raise SystemExit(f"File not found: {args.path}")
    out_dir = args.out or args.path.parent / f"{args.path.stem}_profile"
    profile(args.path, out_dir, synthetic=args.synthetic, date_format=args.date_format)


if __name__ == "__main__":
    main()
