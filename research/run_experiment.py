"""Run a declared experiment and export its results.

    python research/run_experiment.py research/configs/rq1_forecasting.toml

This is the research workstream's entry point, and it is deliberately separate
from the API (architecture §4.5). The application exists to let a manager
explore their data; this exists to run a pre-declared experiment and export
numbers that go into a report. They share the pure core - the same `splits`,
`metrics` and models - so the two cannot disagree, but the experiment is not
something you start by clicking a button, and its protocol lives in a file
under version control rather than in a form.

What it guarantees:

* **The protocol is declared before the run.** It comes from the TOML file,
  and the file's SHA-256 is written into every output. A result and the exact
  protocol that produced it are never separated.
* **The hold-out is scored once, after selection.** Same discipline as the
  service: cross-validation picks a model, the choice is recorded, and only
  then is the locked window scored.
* **The environment is recorded.** Library versions and the seed travel with
  the numbers, because "reproducible" means nothing without them.

Outputs land in `research/results/<timestamp>-<name>/`:

    config.toml          a copy of the config that ran, byte for byte
    run.json             everything: protocol, summary, significance, holdout
    per_fold.csv         models x folds, the input to the significance test
    summary.csv          one row per model
    holdout.csv          the locked window, scored once
    README.md            what was run, when, against what versions

`--dry-run` prints the protocol and the model list without fitting anything,
which is the cheap way to catch a config mistake before a long run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.forecasting  # noqa: E402,F401  - registers the models
from app.forecasting.base import available_models, get_model  # noqa: E402
from app.forecasting.evaluate import (  # noqa: E402
    build_intervals,
    run_experiment,
    run_holdout,
)
from app.forecasting.features import (  # noqa: E402
    FeatureSpec,
    build_features,
    feature_names,
)
from app.forecasting.importance import (  # noqa: E402
    permutation_importance,
    rank_agreement,
    to_score_map,
)
from app.forecasting.splits import SplitError, build_protocol  # noqa: E402
from app.forecasting.trees import GlobalTreeModel  # noqa: E402

# The whole-business total is one series in the panel alongside the products,
# so the pooled model forecasts exactly the series the local models are scored
# on.
TARGET_SERIES_ID = "__TOTAL__"

PANEL_SPEC = FeatureSpec(
    lags=(1, 2, 3, 4, 8, 12, 52), rolling_windows=(4, 12), calendar=True
)

# Models that take a season length. Keeping this in one place means adding a
# seasonal model does not require remembering to edit the CLI as well.
SEASONAL_MODELS = {"seasonal_naive", "seasonal_naive_drift", "fourier"}

NON_PRODUCT_CODES = {
    "POST", "DOT", "M", "D", "C2", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "B", "S", "PADS", "ADJUST",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """The config is wrong. Raised before anything expensive happens."""


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    """Parse the TOML and hash the raw bytes.

    The hash is of the **file**, not of the parsed dictionary: a comment
    explaining why a parameter was chosen is part of the declared protocol, and
    changing it should be visible.
    """
    raw = path.read_bytes()
    try:
        config = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error

    digest = hashlib.sha256(raw).hexdigest()
    validate_config(config)
    return config, digest


def validate_config(config: dict[str, Any]) -> None:
    """Check the whole config up front and report every problem at once.

    One error at a time turns a five-minute fix into five rounds of editing and
    re-running.
    """
    problems: list[str] = []

    for section in ("meta", "data", "protocol", "models"):
        if section not in config:
            problems.append(f"Missing [{section}] section.")
    if problems:
        raise ConfigError("\n".join(problems))

    data = config["data"]
    source = data.get("source")
    if source not in ("database", "csv"):
        problems.append("data.source must be 'database' or 'csv'.")
    if source == "csv" and not data.get("csv_path"):
        problems.append("data.source is 'csv' but data.csv_path is empty.")

    protocol = config["protocol"]
    for key in ("horizon", "folds", "season_length"):
        value = protocol.get(key)
        if not isinstance(value, int) or value < 1:
            problems.append(f"protocol.{key} must be a positive integer.")
    if protocol.get("window_style") not in ("expanding", "sliding"):
        problems.append("protocol.window_style must be 'expanding' or 'sliding'.")

    requested = config["models"].get("include") or []
    if not requested:
        problems.append("models.include is empty - there is nothing to compare.")

    known = {row["model"]: row for row in available_models()}
    for name in requested:
        if name not in known:
            problems.append(
                f"Unknown model '{name}'. Available: {', '.join(sorted(known))}."
            )

    members = config.get("combination", {}).get("members") or []
    missing = [m for m in members if m not in requested]
    if missing:
        problems.append(
            f"combination.members names {missing}, which are not in models.include. "
            f"A combination cannot average a model that was never fitted."
        )

    if problems:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(problems))


def build_factories(config: dict[str, Any]) -> dict[str, Any]:
    """Model name -> zero-argument factory, with per-model params applied."""
    params = config["models"].get("params", {}) or {}
    season_length = config["protocol"]["season_length"]

    factories: dict[str, Any] = {}
    for name in config["models"]["include"]:
        kwargs = dict(params.get(name, {}) or {})
        if name in SEASONAL_MODELS:
            kwargs.setdefault("season_length", season_length)
        factories[name] = lambda n=name, k=kwargs: get_model(n, **k)
    return factories


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def series_from_database(config: dict[str, Any]) -> tuple[pd.Series, dict[str, Any]]:
    """The authoritative path: the cleaned, stored dataset via the same SQL the app uses."""
    from sqlalchemy import select

    from app.db.models.dataset import Dataset
    from app.db.repositories import forecasts as forecast_repo
    from app.db.repositories.analytics import Filters
    from app.db.session import SessionFactory

    data = config["data"]
    session = SessionFactory()
    try:
        dataset_id = (data.get("dataset_id") or "").strip()
        if dataset_id:
            dataset = session.get(Dataset, uuid.UUID(dataset_id))
            if dataset is None:
                raise ConfigError(f"No dataset with id {dataset_id}.")
        else:
            dataset = session.execute(
                select(Dataset)
                .where(Dataset.status == "ready")
                .order_by(Dataset.processed_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if dataset is None:
                raise ConfigError(
                    "No processed dataset found. Upload and process one, or set "
                    "data.dataset_id."
                )
            print(
                f"  WARNING: data.dataset_id is empty, so the most recently processed\n"
                f"           dataset was used ({dataset.id}). Set it explicitly before\n"
                f"           the run whose numbers you cite - 'the latest one' is not\n"
                f"           a reproducible reference."
            )

        series, meta = forecast_repo.weekly_series(
            session, dataset.id, Filters(),
            granularity=data.get("granularity", "week"),
            value_column=data.get("value_column", "net_revenue"),
            date_max=pd.Timestamp(dataset.date_max) if dataset.date_max else None,
        )
        meta["dataset_id"] = str(dataset.id)
        meta["dataset_name"] = dataset.name
        meta["pipeline_version"] = dataset.pipeline_version
        meta["clean_data_sha256"] = dataset.clean_data_sha256
        return series, meta
    finally:
        session.close()


def series_from_csv(config: dict[str, Any]) -> tuple[pd.Series, dict[str, Any]]:
    """Development path: a light aggregation of the raw file, no database.

    Not the full cleaning pipeline - non-product codes and non-positive prices
    are excluded and the partial final week is dropped, which is enough to
    rehearse the protocol. Numbers from here are for development.
    """
    path = Path(config["data"]["csv_path"])
    if not path.exists():
        raise ConfigError(f"data.csv_path does not exist: {path}")

    frame = pd.read_csv(
        path, usecols=["Invoice", "StockCode", "Quantity", "InvoiceDate", "Price"],
        dtype={"StockCode": "string"},
    )
    frame["StockCode"] = frame["StockCode"].astype("string").str.strip().str.upper()
    frame["Quantity"] = pd.to_numeric(frame["Quantity"], errors="coerce")
    frame["Price"] = pd.to_numeric(frame["Price"], errors="coerce")
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"], errors="coerce")

    kept = frame[
        ~frame["StockCode"].isin(NON_PRODUCT_CODES)
        & frame["Price"].notna() & (frame["Price"] > 0)
        & frame["Quantity"].notna() & frame["InvoiceDate"].notna()
    ].copy()
    kept["revenue"] = kept["Quantity"] * kept["Price"]

    # W-SUN labels each bin by its Sunday but starts it on Monday, matching
    # PostgreSQL's date_trunc('week'). W-MON would start weeks on a Tuesday.
    weekly = kept.set_index("InvoiceDate")["revenue"].resample("W-SUN").sum()
    last_date = kept["InvoiceDate"].max().normalize()
    dropped = int((weekly.index > last_date).sum())
    weekly = weekly[weekly.index <= last_date]
    weekly.index = weekly.index.to_period("W-SUN").start_time

    return weekly.astype("float64"), {
        "available": True,
        "source": "csv",
        "file": str(path),
        "rows_read": int(len(frame)),
        "rows_used": int(len(kept)),
        "incomplete_final_periods_dropped": dropped,
        "warning": (
            "Built by a light aggregation, not the twelve-step cleaning pipeline. "
            "Use source = 'database' for any number that reaches the report."
        ),
    }


# ---------------------------------------------------------------------------
# Running and exporting
# ---------------------------------------------------------------------------


def panel_from_database(config: dict[str, Any], series: pd.Series, dataset_id: str):
    """The target series plus the top products, for the pooled tree model."""
    import uuid as _uuid

    from app.db.repositories import forecasts as forecast_repo
    from app.db.repositories.analytics import Filters
    from app.db.session import SessionFactory

    limit = int(config["data"].get("panel_products", 100))
    session = SessionFactory()
    try:
        panel, meta = forecast_repo.product_panel(
            session, _uuid.UUID(dataset_id), Filters(),
            granularity=config["data"].get("granularity", "week"),
            limit_products=limit,
        )
    finally:
        session.close()

    if not meta.get("available") or panel.empty:
        return None, {**meta, "tree_family_excluded": True}
    return _with_target(panel, series), meta


def panel_from_csv(config: dict[str, Any], series: pd.Series):
    """Per-product weekly series from the raw file, same light aggregation."""
    path = Path(config["data"]["csv_path"])
    limit = int(config["data"].get("panel_products", 100))

    frame = pd.read_csv(
        path, usecols=["StockCode", "Quantity", "InvoiceDate", "Price"],
        dtype={"StockCode": "string"},
    )
    frame["StockCode"] = frame["StockCode"].astype("string").str.strip().str.upper()
    frame["Quantity"] = pd.to_numeric(frame["Quantity"], errors="coerce")
    frame["Price"] = pd.to_numeric(frame["Price"], errors="coerce")
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"], errors="coerce")

    kept = frame[
        ~frame["StockCode"].isin(NON_PRODUCT_CODES)
        & frame["Price"].notna() & (frame["Price"] > 0)
        & frame["Quantity"].notna() & frame["InvoiceDate"].notna()
    ].copy()
    kept["revenue"] = kept["Quantity"] * kept["Price"]
    if kept.empty:
        return None, {"available": False, "reason": "No usable product rows."}

    top = (
        kept.groupby("StockCode")["revenue"].sum()
        .sort_values(ascending=False).head(limit).index
    )
    weekly = (
        kept[kept["StockCode"].isin(top)]
        .set_index("InvoiceDate")
        .groupby("StockCode")["revenue"]
        .resample("W-SUN").sum()
        .reset_index()
    )
    weekly["period"] = weekly["InvoiceDate"].dt.to_period("W-SUN").dt.start_time
    panel = weekly.rename(columns={"StockCode": "series_id", "revenue": "value"})
    panel = panel[["series_id", "period", "value"]]

    # Each series onto the shared calendar: a SKU that sold in weeks 1 and 5
    # genuinely has zero in weeks 2-4, and omitting those rows would make every
    # lag feature wrong.
    calendar = series.index
    filled = []
    for series_id, group in panel.groupby("series_id", observed=True):
        reindexed = (
            group.set_index("period")["value"].reindex(calendar).fillna(0.0)
            .rename_axis("period").reset_index(name="value")
        )
        reindexed["series_id"] = str(series_id)
        filled.append(reindexed)
    panel = pd.concat(filled, ignore_index=True)[["series_id", "period", "value"]]

    return _with_target(panel, series), {
        "available": True,
        "source": "csv",
        "series": int(panel["series_id"].nunique()),
        "product_limit": limit,
    }


def _with_target(panel: pd.DataFrame, series: pd.Series) -> pd.DataFrame:
    """Add the target series to the panel and restrict products to its calendar."""
    panel = panel[panel["period"].isin(series.index)]
    total = pd.DataFrame({
        "series_id": TARGET_SERIES_ID,
        "period": series.index,
        "value": series.to_numpy(dtype="float64"),
    })
    return pd.concat([total, panel], ignore_index=True)


def feature_importance(panel: pd.DataFrame, protocol, seed: int) -> dict[str, Any]:
    """Permutation importance on held-out rows, against the Phase 4 MI ranking.

    This is §12.7. Phase 4's `score_features` returns `model_importance: null`
    as a placeholder; this is the model-based half, and the agreement block is
    what turns an unsupported proposal into a tested one.
    """
    from app.analytics import features as analytics_features

    spec = FeatureSpec(
        lags=PANEL_SPEC.lags, rolling_windows=PANEL_SPEC.rolling_windows,
        calendar=True, horizon=1,
    )
    built = build_features(panel, spec)
    if built.empty:
        return {"available": False, "reason": "No rows survived feature building."}

    columns = feature_names(spec)
    cutoff = protocol.holdout.train_index[-1]
    train = built[built["period"] <= cutoff]
    validation = built[built["period"] > cutoff]
    if len(train) < 50 or validation.empty:
        return {
            "available": False,
            "reason": (
                f"Too few rows: {len(train)} training and {len(validation)} "
                f"validation after feature building."
            ),
        }

    estimator = GlobalTreeModel(spec=spec, horizon=1)._make_estimator()
    estimator.fit(train[columns].to_numpy(), train["y"].to_numpy())

    scores = permutation_importance(
        estimator, validation[columns], validation["y"], random_state=seed
    )
    if not scores.get("available"):
        return scores

    try:
        mi = analytics_features.score_features(
            validation[[*columns, "y"]], target_column="y"
        )
        if mi.get("available"):
            mutual = {
                str(row["feature"]): float(row["mi_knn"])
                for row in mi["features"] if row.get("mi_knn") is not None
            }
            agreement = rank_agreement(to_score_map(scores["rows"]), mutual)
        else:
            agreement = {"available": False, "reason": mi.get("reason")}
    except Exception as error:   # noqa: BLE001 - the importances still stand
        agreement = {"available": False, "reason": f"MI comparison failed: {error}"}

    return {
        "available": True,
        "training_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "permutation_importance": scores,
        "agreement_with_mutual_information": agreement,
    }


def environment() -> dict[str, str]:
    import platform

    import numpy
    import scipy
    import sklearn

    versions = {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
    }
    try:
        import xgboost

        versions["xgboost"] = xgboost.__version__
    except ImportError:
        versions["xgboost"] = "not installed"
    return versions


def export(
    outcome: dict[str, Any],
    holdout: dict[str, Any],
    config: dict[str, Any],
    config_path: Path,
    config_hash: str,
    series_meta: dict[str, Any],
    destination: Path,
    *,
    intervals: dict[str, Any] | None = None,
    importance: dict[str, Any] | None = None,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    output = config.get("output", {})

    shutil.copy2(config_path, destination / "config.toml")

    if output.get("write_csv", True):
        outcome["per_fold_table"].to_csv(destination / "per_fold.csv")
        outcome["summary"].to_csv(destination / "summary.csv", index=False)
        holdout["summary"].to_csv(destination / "holdout.csv", index=False)
        if importance and importance.get("available"):
            pd.DataFrame(
                importance["permutation_importance"]["rows"]
            ).to_csv(destination / "feature_importance.csv", index=False)
        if intervals and intervals.get("available"):
            pd.DataFrame({
                "step": range(1, len(intervals["point"]) + 1),
                "lower": intervals["lower"],
                "point": intervals["point"],
                "upper": intervals["upper"],
                "actual": intervals["actual"],
            }).to_csv(destination / "intervals.csv", index=False)

    record = {
        "meta": config.get("meta", {}),
        "config_hash": config_hash,
        "run_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        "series": series_meta,
        "protocol": outcome["protocol"],
        "primary_metric": outcome["metric"],
        "summary": json.loads(outcome["summary"].to_json(orient="records")),
        "significance": outcome["significance"],
        "combination": outcome["combination"],
        "selection": {
            "selected_model": holdout["selected_before_scoring"],
            "holdout_scored_at": holdout["scored_at"],
            "warning": holdout["warning"],
        },
        "holdout": json.loads(holdout["summary"].to_json(orient="records")),
        "global_models": outcome["global_models"],
        "intervals": intervals,
        "feature_importance": importance,
        "fold_results": outcome["fold_results"],
    }
    if output.get("write_json", True):
        (destination / "run.json").write_text(json.dumps(record, indent=2, default=str))

    (destination / "README.md").write_text(_readme(record, config_path, config_hash))


def _readme(record: dict[str, Any], config_path: Path, config_hash: str) -> str:
    versions = "\n".join(f"| {k} | {v} |" for k, v in record["environment"].items())
    summary = record["significance"].get("summary", "(not computed)")
    selected = record["selection"]["selected_model"]
    return f"""# {record['meta'].get('name', 'experiment')}

Run at **{record['run_at']}**.

Config: `{config_path.name}`
Config SHA-256: `{config_hash}`

A result and the protocol that produced it belong together. If the config hash
here differs from another run's, the two ran different experiments.

## Selection

Selected on cross-validation: **{selected}**
Hold-out scored at: {record['selection']['holdout_scored_at']}

{record['selection']['warning'] or 'Selection was recorded before the hold-out was scored.'}

## Significance

{summary}

## Environment

| component | version |
|---|---|
{versions}

## Files

| file | what it is |
|---|---|
| `config.toml` | the config that ran, copied byte for byte |
| `run.json` | protocol, summary, significance, hold-out, per-fold detail |
| `per_fold.csv` | models x folds - the input to the significance test |
| `summary.csv` | one row per model |
| `holdout.csv` | the locked window, scored once |
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("config", type=Path, help="Path to the experiment TOML")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and print the protocol without fitting anything")
    parser.add_argument("--out", type=Path, default=None,
                        help="Override output.directory from the config")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"No such config: {args.config}")
        return 2

    try:
        config, digest = load_config(args.config)
    except ConfigError as error:
        print(error)
        return 2

    meta = config.get("meta", {})
    print(f"\n{meta.get('name', args.config.stem)}  ({meta.get('research_question', '?')})")
    print(f"config sha256: {digest}")

    print("\nenvironment:")
    for key, value in environment().items():
        print(f"  {key:<14} {value}")

    print("\nmodels:")
    known = {row["model"]: row for row in available_models()}
    for name in config["models"]["include"]:
        row = known[name]
        mark = "ok" if row["available"] else "--"
        print(f"  [{mark}] {name}")
        if not row["available"]:
            print(f"       {row['unavailable_reason']}")

    try:
        if config["data"]["source"] == "database":
            series, series_meta = series_from_database(config)
        else:
            series, series_meta = series_from_csv(config)
    except ConfigError as error:
        print(f"\n{error}")
        return 2

    panel, panel_meta = None, {"available": False, "reason": "not requested"}
    if config["models"].get("include_global", True):
        try:
            if config["data"]["source"] == "database":
                panel, panel_meta = panel_from_database(
                    config, series, series_meta.get("dataset_id", "")
                )
            else:
                panel, panel_meta = panel_from_csv(config, series)
        except Exception as error:   # noqa: BLE001 - a missing panel is not fatal
            panel, panel_meta = None, {
                "available": False, "reason": f"The panel could not be built: {error}"
            }
    series_meta["panel"] = panel_meta

    if not series_meta.get("available", True) or series.empty:
        print(f"\nNo series to forecast: {series_meta.get('reason', 'empty')}")
        return 1

    print(f"\nseries: {len(series)} periods, "
          f"{series.index[0].date()} to {series.index[-1].date()}")
    if panel is not None:
        print(f"panel : {panel['series_id'].nunique()} series "
              f"(the target plus {panel['series_id'].nunique() - 1} products)")
    else:
        print(f"panel : not built - the tree family is NOT in this comparison "
              f"({panel_meta.get('reason', 'unknown')})")
    for key in ("gap_note", "incomplete_note", "warning"):
        if series_meta.get(key):
            print(f"  note: {series_meta[key]}")

    protocol_config = config["protocol"]
    try:
        protocol = build_protocol(
            series,
            horizon=protocol_config["horizon"],
            folds=protocol_config["folds"],
            style=protocol_config["window_style"],
        )
    except SplitError as error:
        print(f"\nThe protocol does not fit this series:\n  {error}")
        return 1

    print("\nprotocol:")
    for fold in protocol.as_dict()["folds"]:
        print(f"  fold {fold['fold']}: train {fold['train_start']}..{fold['train_end']} "
              f"({fold['train_size']:>3}) -> test {fold['test_start']}..{fold['test_end']}")
    locked = protocol.as_dict()["holdout"]
    print(f"  LOCKED  : test {locked['test_start']}..{locked['test_end']}")

    if args.dry_run:
        print("\nDry run: nothing was fitted and nothing was written.")
        return 0

    factories = build_factories(config)
    combination = config.get("combination", {})
    global_factories = (
        {"gbt_global": lambda: GlobalTreeModel(
            spec=PANEL_SPEC, horizon=protocol_config["horizon"]
        )}
        if panel is not None else None
    )

    outcome = run_experiment(
        series, factories,
        horizon=protocol_config["horizon"],
        folds=protocol_config["folds"],
        season_length=protocol_config["season_length"],
        combination_rule=combination.get("rule", "median"),
        combination_members=combination.get("members") or None,
        metric=protocol_config.get("primary_metric", "WAPE"),
        protocol=protocol,
        panel=panel,
        global_factories=global_factories,
        target_series_id=TARGET_SERIES_ID if panel is not None else None,
    )
    for note in outcome["global_models"]["notes"]:
        print(f"  note: {note}")

    print(f"\ncross-validation ({outcome['metric']}, lower is better):")
    print(outcome["summary"].round(3).to_string(index=False))
    print(f"\nsignificance:\n  {outcome['significance']['summary']}")

    # Selection, then the hold-out. In that order, and recorded.
    column = f"mean_{outcome['metric'].lower()}"
    usable = outcome["summary"][outcome["summary"][column].notna()]
    selected = str(usable.iloc[0]["model"]) if not usable.empty else None
    print(f"\nselected on cross-validation: {selected}")

    holdout = run_holdout(
        series, factories,
        horizon=protocol_config["horizon"],
        season_length=protocol_config["season_length"],
        protocol=protocol,
        selected=selected,
        panel=panel,
        global_factories=global_factories,
        target_series_id=TARGET_SERIES_ID if panel is not None else None,
        combination_rule=combination.get("rule", "median"),
        combination_members=combination.get("members") or None,
    )
    if holdout.get("combination_note"):
        print(f"  note: {holdout['combination_note']}")
    print("\nhold-out (scored once, after selection):")
    print(holdout["summary"].round(3).to_string(index=False))

    intervals = (
        build_intervals(
            outcome["_fold_objects"], holdout["_result_objects"], selected,
            level=float(config.get("intervals", {}).get("level", 0.80)),
        )
        if selected else {"available": False, "reason": "No model was selected."}
    )
    if intervals.get("available"):
        cover = intervals["coverage"]
        print(f"\nprediction interval ({intervals['level']:.0%} nominal): "
              f"observed coverage {cover['observed']:.0%} - {cover['verdict']}")

    importance = (
        feature_importance(panel, protocol, config.get("reproducibility", {})
                           .get("random_seed", 20260101))
        if panel is not None else {"available": False, "reason": "No panel."}
    )
    if importance.get("available"):
        agreement = importance["agreement_with_mutual_information"]
        if agreement.get("available"):
            print(f"\n12.7 feature importance vs mutual information: "
                  f"rho = {agreement['spearman_rho']:.3f} over "
                  f"{agreement['features_compared']} features, "
                  f"top-{agreement['top_k']} overlap "
                  f"{agreement['top_k_overlap_count']}")
            print(f"  {agreement['verdict']}")

    root = args.out or Path(config.get("output", {}).get("directory", "research/results"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = root / f"{stamp}-{meta.get('name', args.config.stem)}"
    export(outcome, holdout, config, args.config, digest, series_meta, destination,
           intervals=intervals, importance=importance)

    print(f"\nwritten to {destination}")
    failures = int(outcome["summary"]["folds_failed"].sum())
    if failures:
        print(f"WARNING: {failures} model/fold combination(s) failed; see summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
