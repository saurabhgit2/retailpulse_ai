"""The cleaning pipeline (architecture §12.3).

Twelve ordered steps. Each one is a small function that takes the frame and
returns the frame plus a record of exactly what it did: how many rows it
touched, why, and a few example rows.

Two rules hold the whole thing together:

1. **Nothing is changed silently.** Every step produces an ActionRecord, and
   those records become the data-quality report the user reads.
2. **Conservation.** rows in the file = rows kept + rows excluded, always.
   It is checked here and asserted in the tests; if it ever fails, a step has
   dropped rows without saying so.

Pure module: pandas only. No FastAPI, no SQLAlchemy, no file paths.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.preprocessing.dates import last_complete_period, parse_dates
from app.preprocessing.field_guide import DEFAULT_CLEANING_OPTIONS, compute_capabilities

PIPELINE_VERSION = "1.0.0"

# Columns the pipeline produces, in order.
CLEAN_COLUMNS = [
    "invoice_id", "occurred_at", "product_code", "product_name", "category",
    "customer_id", "region", "quantity", "unit_price", "revenue", "is_return", "is_outlier",
]

EXAMPLE_ROWS = 3


@dataclass
class ActionRecord:
    """What one step did. This is what the user sees in the report."""

    step: str
    title: str
    kind: str  # 'excluded' | 'flagged' | 'transformed' | 'info'
    rows_before: int
    rows_after: int
    rows_affected: int
    rationale: str
    examples: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "title": self.title,
            "kind": self.kind,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_affected": self.rows_affected,
            "rationale": self.rationale,
            "examples": self.examples,
        }


@dataclass
class CleaningResult:
    frame: pd.DataFrame
    actions: list[ActionRecord]
    excluded_by_reason: dict[str, int]
    warnings: list[dict[str, str]]
    rows_raw: int
    rows_returns: int
    rows_guest: int
    date_min: pd.Timestamp | None
    date_max: pd.Timestamp | None
    last_complete_week: pd.Timestamp | None
    last_complete_month: pd.Timestamp | None
    product_variants: dict[str, int]
    fingerprint: str

    @property
    def rows_clean(self) -> int:
        return len(self.frame)

    @property
    def rows_excluded(self) -> int:
        return sum(self.excluded_by_reason.values())

    @property
    def conservation_ok(self) -> bool:
        return self.rows_raw == self.rows_clean + self.rows_excluded


class _Pipeline:
    """Holds the frame between steps and collects the records."""

    def __init__(self, frame: pd.DataFrame, options: dict[str, Any]):
        self.frame = frame
        self.options = options
        self.actions: list[ActionRecord] = []
        self.excluded: dict[str, int] = {}
        self.warnings: list[dict[str, str]] = []

    def has(self, column: str) -> bool:
        return column in self.frame.columns

    def _examples(self, rows: pd.DataFrame) -> list[dict[str, Any]]:
        sample = rows.head(EXAMPLE_ROWS)
        return [
            {k: ("" if pd.isna(v) else str(v)) for k, v in record.items()}
            for record in sample.to_dict(orient="records")
        ]

    def exclude(self, step: str, title: str, rationale: str, mask: pd.Series) -> None:
        """Drop the rows where `mask` is True, and record why."""
        mask = mask.fillna(False)
        removed = self.frame[mask]
        before = len(self.frame)
        self.frame = self.frame[~mask]
        self.excluded[step] = self.excluded.get(step, 0) + int(len(removed))
        self.actions.append(
            ActionRecord(
                step=step,
                title=title,
                kind="excluded",
                rows_before=before,
                rows_after=len(self.frame),
                rows_affected=int(len(removed)),
                rationale=rationale,
                examples=self._examples(removed),
            )
        )

    def note(
        self, step: str, title: str, rationale: str, affected: int, kind: str = "flagged",
        examples: pd.DataFrame | None = None,
    ) -> None:
        """Record a step that changed or flagged rows but removed none."""
        self.actions.append(
            ActionRecord(
                step=step,
                title=title,
                kind=kind,
                rows_before=len(self.frame),
                rows_after=len(self.frame),
                rows_affected=int(affected),
                rationale=rationale,
                examples=self._examples(examples) if examples is not None else [],
            )
        )


def _rename_to_canonical(raw: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Keep only the mapped columns and give them their canonical names."""
    columns = {source: canonical for canonical, source in mapping.items() if source}
    missing = [source for source in columns if source not in raw.columns]
    if missing:
        raise KeyError(f"Mapped columns are not in the file: {', '.join(missing)}")
    return raw[list(columns)].rename(columns=columns)


def _fingerprint(frame: pd.DataFrame) -> str:
    """A hash of the cleaned data that does not depend on row order.

    Same file + same mapping + same pipeline version must give the same value.
    That is what makes the reproducibility test in the architecture (NFR-03)
    a check rather than a promise.
    """
    row_hashes = pd.util.hash_pandas_object(frame.reset_index(drop=True), index=False)
    total = np.uint64(row_hashes.to_numpy(dtype="uint64").sum())  # order-independent
    payload = f"{PIPELINE_VERSION}|{len(frame)}|{total}".encode()
    return hashlib.sha256(payload).hexdigest()


def clean_dataset(
    raw: pd.DataFrame, mapping: dict[str, str | None], options: dict[str, Any] | None = None
) -> CleaningResult:
    """Run the twelve steps. `raw` holds text columns with the file's own names."""
    opts = {**DEFAULT_CLEANING_OPTIONS, **(options or {})}
    if not opts.get("date_format"):
        raise ValueError("options['date_format'] is required ('iso', 'dmy' or 'mdy').")

    frame = _rename_to_canonical(raw, mapping)
    rows_raw = len(frame)
    pipe = _Pipeline(frame, opts)

    _step_1_normalise_text(pipe)
    _step_2_parse_types(pipe)
    _step_3_exact_duplicates(pipe)
    _step_4_non_merchandise(pipe)
    _step_5_invalid_prices(pipe)
    rows_returns = _step_6_flag_returns(pipe)
    rows_guest = _step_7_missing_identifiers(pipe)
    product_variants = _step_8_canonical_product_names(pipe)
    _step_9_revenue(pipe)
    _step_10_outliers(pipe)
    date_min, date_max, last_week, last_month = _step_11_partial_periods(pipe)
    _step_12_closure_calendar(pipe)

    result_frame = _finalise_columns(pipe.frame)

    return CleaningResult(
        frame=result_frame,
        actions=pipe.actions,
        excluded_by_reason=pipe.excluded,
        warnings=pipe.warnings,
        rows_raw=rows_raw,
        rows_returns=rows_returns,
        rows_guest=rows_guest,
        date_min=date_min,
        date_max=date_max,
        last_complete_week=last_week,
        last_complete_month=last_month,
        product_variants=product_variants,
        fingerprint=_fingerprint(result_frame),
    )


# --- The twelve steps --------------------------------------------------------

IDENTIFIER_COLUMNS = ("invoice_id", "product_code", "customer_id")


def _step_1_normalise_text(pipe: _Pipeline) -> None:
    """Trim whitespace, upper-case product codes, and repair float-looking IDs."""
    frame = pipe.frame
    changed = 0

    for column in frame.columns:
        if frame[column].dtype == object or str(frame[column].dtype) == "string":
            original = frame[column]
            values = original.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
            if column in IDENTIFIER_COLUMNS:
                # Spreadsheets turn 13085 into "13085.0"; the trailing .0 is an
                # artefact of reading an integer ID as a float, not part of the ID.
                values = values.str.replace(r"^(\d+)\.0$", r"\1", regex=True)
            if column == "product_code":
                values = values.str.upper()
            values = values.replace({"": pd.NA})
            changed += int((values.fillna("") != original.astype("string").fillna("")).sum())
            frame[column] = values

    pipe.frame = frame
    pipe.note(
        "normalise_text",
        "Tidied text values",
        "Trimmed spaces, upper-cased product codes and removed the trailing '.0' that "
        "spreadsheets add to numeric IDs, so the same value is never treated as two.",
        changed,
        kind="transformed",
    )


NUMERIC_COLUMNS = ("quantity", "unit_price", "revenue", "discount")


def _step_2_parse_types(pipe: _Pipeline) -> None:
    """Turn text into dates and numbers; exclude rows that cannot be read."""
    frame = pipe.frame
    style = pipe.options["date_format"]

    frame["occurred_at"] = parse_dates(frame["occurred_at"], style)
    bad = frame["occurred_at"].isna()

    numeric_present = [c for c in NUMERIC_COLUMNS if c in frame.columns]
    for column in numeric_present:
        text = frame[column].astype("string").str.replace(",", "", regex=False)
        converted = pd.to_numeric(text, errors="coerce")
        # A value that was present but unreadable is a problem; an empty cell is not.
        bad = bad | (text.notna() & (text != "") & converted.isna())
        frame[column] = converted

    pipe.frame = frame
    pipe.exclude(
        "invalid_value",
        "Excluded rows with an unreadable date or number",
        f"Dates are read as '{style}'. A row whose date or "
        f"{'/'.join(numeric_present) or 'numbers'} cannot be read cannot be placed in time "
        f"or valued, so it is removed and counted here.",
        bad,
    )


def _step_3_exact_duplicates(pipe: _Pipeline) -> None:
    if not pipe.options.get("drop_exact_duplicates", True):
        return
    duplicated = pipe.frame.duplicated(keep="first")
    pipe.exclude(
        "exact_duplicate",
        "Removed exact duplicate rows",
        "Rows identical in every mapped column are treated as double entries. Caveat: some "
        "may be genuine repeat scans of the same item; this assumption is recorded as a "
        "limitation.",
        duplicated,
    )


def _step_4_non_merchandise(pipe: _Pipeline) -> None:
    if not pipe.has("product_code") or not pipe.options.get("exclude_non_product_codes", True):
        return
    codes = {str(code).upper() for code in pipe.options.get("non_product_codes", [])}
    mask = pipe.frame["product_code"].astype("string").str.upper().isin(codes)
    pipe.exclude(
        "non_product_code",
        "Excluded fee and adjustment lines",
        "Postage, bank charges, fees and manual adjustments are not product sales. Leaving "
        "them in would inflate revenue and invent products that do not exist.",
        mask,
    )


def _step_5_invalid_prices(pipe: _Pipeline) -> None:
    if not pipe.has("unit_price"):
        return
    price = pipe.frame["unit_price"]
    pipe.exclude(
        "non_positive_price",
        "Excluded lines with a zero or negative price",
        "Zero-price lines are free items or stock adjustments; negative prices are bad-debt "
        "write-offs. Neither is a sale.",
        price.notna() & (price <= 0),
    )


def _step_6_flag_returns(pipe: _Pipeline) -> int:
    """Returns are kept and flagged: they are real events that reduce net revenue."""
    frame = pipe.frame
    mask = pd.Series(False, index=frame.index)
    if pipe.has("invoice_id"):
        mask |= frame["invoice_id"].astype("string").str.upper().str.startswith("C").fillna(False)
    if pipe.has("quantity"):
        mask |= frame["quantity"].fillna(0) < 0

    frame["is_return"] = mask
    pipe.frame = frame
    pipe.note(
        "returns_flagged",
        "Flagged returns and cancellations (kept)",
        "Cancellation invoices and negative quantities are returns. They are kept because net "
        "revenue needs them; demand forecasting and basket analysis exclude them by filter.",
        int(mask.sum()),
        examples=frame[mask],
    )
    return int(mask.sum())


def _step_7_missing_identifiers(pipe: _Pipeline) -> int:
    """Missing customer IDs become guests rather than deletions."""
    if not pipe.has("customer_id"):
        return 0
    missing = pipe.frame["customer_id"].isna()
    pipe.note(
        "missing_customer_id",
        "Kept rows without a customer ID as guest sales",
        "These are valid sales for revenue and forecasting, but cannot be attributed to a "
        "customer, so segmentation leaves them out. Deleting them would understate revenue.",
        int(missing.sum()),
        examples=pipe.frame[missing],
    )
    return int(missing.sum())


def _step_8_canonical_product_names(pipe: _Pipeline) -> dict[str, int]:
    """One name per product code: the most frequent one in the file."""
    if not (pipe.has("product_code") and pipe.has("product_name")):
        return {}

    frame = pipe.frame
    named = frame.dropna(subset=["product_code", "product_name"])
    variants = named.groupby("product_code")["product_name"].nunique()

    if not named.empty:
        canonical = (
            named.groupby(["product_code", "product_name"]).size().reset_index(name="n")
            .sort_values(["product_code", "n"], ascending=[True, False])
            .drop_duplicates("product_code")
            .set_index("product_code")["product_name"]
        )
        replaced = frame["product_code"].map(canonical)
        changed = int((replaced.notna() & (replaced != frame["product_name"])).sum())
        frame["product_name"] = replaced.fillna(frame["product_name"]).fillna("UNKNOWN")
    else:
        changed = 0
        frame["product_name"] = frame["product_name"].fillna("UNKNOWN")

    multi = variants[variants > 1]
    pipe.frame = frame
    pipe.note(
        "canonical_product_names",
        "Gave each product code one name",
        f"{len(multi)} product codes appeared with more than one description. The most "
        f"frequent description is used everywhere so the same product is not counted twice "
        f"under different names.",
        changed,
        kind="transformed",
    )
    return {str(code): int(count) for code, count in variants.items()}


def _step_9_revenue(pipe: _Pipeline) -> None:
    """Derive revenue when the file has none; check it when the file has both."""
    frame = pipe.frame
    has_revenue = pipe.has("revenue")
    can_derive = pipe.has("quantity") and pipe.has("unit_price")

    if not has_revenue and can_derive:
        frame["revenue"] = (frame["quantity"] * frame["unit_price"]).round(2)
        pipe.frame = frame
        pipe.note(
            "revenue_derived",
            "Calculated revenue as quantity x unit price",
            "The file has no revenue column. The derivation is recorded so every revenue "
            "figure can be traced back to the columns it came from.",
            len(frame),
            kind="transformed",
        )
        return

    if has_revenue and can_derive:
        derived = (frame["quantity"] * frame["unit_price"]).round(2)
        difference = (frame["revenue"] - derived).abs()
        tolerance = derived.abs() * 0.01
        mismatch = (difference > tolerance) & derived.notna() & frame["revenue"].notna()
        if mismatch.any():
            pipe.warnings.append(
                {
                    "code": "REVENUE_MISMATCH",
                    "message": f"{int(mismatch.sum())} rows have a revenue value that differs "
                               f"from quantity x unit price by more than 1%. The file's own "
                               f"revenue value was kept.",
                }
            )
        pipe.note(
            "revenue_checked",
            "Checked revenue against quantity x unit price",
            "The file provides revenue and the parts to derive it, so they are compared. "
            "Where they disagree the file's value is kept and the disagreement is reported.",
            int(mismatch.sum()),
            kind="info",
        )


def _step_10_outliers(pipe: _Pipeline) -> None:
    """Flag unusual quantities per product - never remove them."""
    if not pipe.has("quantity") or len(pipe.frame) < 10:
        pipe.frame["is_outlier"] = False
        pipe.note(
            "outlier_flagged",
            "Skipped outlier detection",
            "Outlier detection needs a quantity column and at least 10 rows; with fewer, a "
            "median and MAD are meaningless. Nothing was flagged.",
            0,
            kind="info",
        )
        return

    frame = pipe.frame
    threshold = float(pipe.options.get("outlier_threshold", 5.0))
    quantity = frame["quantity"].abs()

    if pipe.has("product_code"):
        grouped = quantity.groupby(frame["product_code"])
        median = grouped.transform("median")
        deviation = (quantity - median).abs()
        mad = deviation.groupby(frame["product_code"]).transform("median")
        mean_deviation = deviation.groupby(frame["product_code"]).transform("mean")
    else:
        median = pd.Series(quantity.median(), index=frame.index)
        deviation = (quantity - median).abs()
        mad = pd.Series(deviation.median(), index=frame.index)
        mean_deviation = pd.Series(deviation.mean(), index=frame.index)

    # The robust z-score uses the median and MAD, so the outliers themselves do
    # not inflate the threshold the way a mean and standard deviation would.
    #
    # When more than half the values of a product are identical the MAD is 0 and
    # the score would be undefined, so we fall back to the mean absolute
    # deviation (scaled to be comparable). If that is 0 too, every value is the
    # same and no outlier exists.
    scale = mad.where(mad > 0, mean_deviation * 1.2533).replace(0, np.nan)
    robust_z = 0.6745 * deviation / scale
    mask = (robust_z > threshold).fillna(False)

    frame["is_outlier"] = mask
    pipe.frame = frame
    pipe.note(
        "outlier_flagged",
        f"Flagged unusually large quantities (robust z > {threshold:g})",
        "Flagged, not removed: a large wholesale order is real data. Each analysis decides "
        "whether to exclude them, and the flag makes that choice visible.",
        int(mask.sum()),
        examples=frame[mask],
    )


def _step_11_partial_periods(pipe: _Pipeline):
    """Record the date range and where complete weeks and months end."""
    dates = pipe.frame["occurred_at"]
    if dates.empty or dates.isna().all():
        return None, None, None, None

    date_min, date_max = dates.min(), dates.max()
    last_week = last_complete_period(date_max, "week")
    last_month = last_complete_period(date_max, "month")

    # Data beyond the end of the last complete week means the final week is partial.
    if date_max.normalize() > last_week + pd.Timedelta(days=6):
        pipe.warnings.append(
            {
                "code": "PARTIAL_FINAL_WEEK",
                "message": f"The data ends on {date_max.date()}, part-way through a week. "
                           f"Weeks after {last_week.date()} are incomplete and are excluded "
                           f"from growth rates and model training.",
            }
        )

    pipe.note(
        "partial_periods",
        "Identified the last complete week and month",
        f"Data runs {date_min.date()} to {date_max.date()}. The last complete week starts "
        f"{last_week.date()} and the last complete month starts {last_month.date()}. Counting "
        f"a partial period as a whole one makes the final point of every trend look like a "
        f"collapse.",
        0,
        kind="info",
    )
    return date_min, date_max, last_week, last_month


def _step_12_closure_calendar(pipe: _Pipeline) -> None:
    """Find weekdays that never trade and long gaps: closures, not zero demand."""
    dates = pipe.frame["occurred_at"].dropna()
    if dates.empty:
        return

    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    traded = set(dates.dt.weekday.unique())
    never_traded = [weekday_names[d] for d in range(7) if d not in traded]

    unique_days = pd.Series(sorted(dates.dt.normalize().unique()))
    gaps = unique_days.diff().dt.days.fillna(0)
    long_gaps = int((gaps >= 4).sum())

    if never_traded or long_gaps:
        detail = []
        if never_traded:
            detail.append(f"no trading on {', '.join(never_traded)}")
        if long_gaps:
            detail.append(f"{long_gaps} gaps of 4 days or more")
        pipe.warnings.append(
            {
                "code": "CLOSURE_DAYS",
                "message": f"Calendar check: {'; '.join(detail)}. These are closures, not zero "
                           f"demand, so daily models must treat them differently from a quiet "
                           f"trading day.",
            }
        )

    pipe.note(
        "closure_calendar",
        "Checked the trading calendar",
        f"Days with no trading at all: {', '.join(never_traded) if never_traded else 'none'}. "
        f"Gaps of four days or more: {long_gaps}.",
        0,
        kind="info",
    )


def _finalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Guarantee the same columns and types whatever the source file had."""
    result = frame.copy()
    for column in CLEAN_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    result["is_return"] = result["is_return"].fillna(False).astype(bool)
    result["is_outlier"] = result["is_outlier"].fillna(False).astype(bool)
    if "revenue" in result:
        result["revenue"] = pd.to_numeric(result["revenue"], errors="coerce").fillna(0).round(2)
    return result[CLEAN_COLUMNS].reset_index(drop=True)


def build_quality_report(result: CleaningResult, mapping: dict[str, str | None]) -> dict[str, Any]:
    """The document served by GET /datasets/{id}/quality-report."""
    return {
        "pipeline_version": PIPELINE_VERSION,
        "scope": {
            "mode": "full",
            "rows_examined": result.rows_raw,
            "file_truncated": False,
            "note": "Computed by the backend pipeline over every row in the uploaded file.",
        },
        "summary": {
            "rows_raw": result.rows_raw,
            "rows_clean": result.rows_clean,
            "rows_excluded": result.rows_excluded,
            "rows_returns_flagged": result.rows_returns,
            "rows_guest": result.rows_guest,
        },
        "conservation": {
            "ok": result.conservation_ok,
            "rows_raw": result.rows_raw,
            "rows_clean": result.rows_clean,
            "rows_excluded": result.rows_excluded,
        },
        "excluded_by_reason": result.excluded_by_reason,
        "actions": [action.as_dict() for action in result.actions],
        "warnings": result.warnings,
        "date_range": {
            "min": result.date_min.isoformat() if result.date_min is not None else None,
            "max": result.date_max.isoformat() if result.date_max is not None else None,
            "last_complete_week": (
                result.last_complete_week.date().isoformat()
                if result.last_complete_week is not None else None
            ),
            "last_complete_month": (
                result.last_complete_month.date().isoformat()
                if result.last_complete_month is not None else None
            ),
        },
        "capabilities": compute_capabilities(mapping),
        "clean_data_sha256": result.fingerprint,
    }
