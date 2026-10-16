"""Forecasting use cases: declare a run, execute it, store it, read it back.

The shape follows `processing_service`: the request returns 202 with a run id,
the work happens in a background task that opens its own session, and the
client polls. A ladder of seven models over four folds on a 100-week series is
seconds rather than minutes, but a per-SKU run over 100 products is not, and an
HTTP request that holds a connection open for two minutes is a request that
times out behind a proxy.

**The protocol discipline is enforced here, not documented here.**

* `run_experiment` scores the CV folds only. The hold-out is untouched.
* The model with the best mean score on CV is written to `selected_model`
  *before* `run_holdout` is called.
* `run_holdout` then scores the locked window once, and the timestamp goes in
  `holdout_scored_at`.

That order is the difference between "selected on cross-validation and
confirmed on a held-out window" and "ran everything on the hold-out and
reported the best number", which are different experiments supporting different
claims. Doing it in code rather than by hand is what makes the claim checkable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.models.dataset import Dataset
from app.db.models.forecast import HOLDOUT_FOLD, ForecastRun
from app.db.repositories import forecasts as repo
from app.db.repositories.analytics import Filters
from app.db.session import SessionFactory
from app.forecasting.base import available_models, get_model
from app.forecasting.evaluate import (
    PRIMARY_METRIC,
    build_intervals,
    run_experiment,
    run_holdout,
)
from app.forecasting.features import FeatureSpec, build_features, feature_names
from app.forecasting.importance import (
    permutation_importance,
    rank_agreement,
    to_score_map,
)
from app.forecasting.splits import SplitError, build_protocol
from app.forecasting.trees import GlobalTreeModel

logger = logging.getLogger(__name__)

# The ladder as the API offers it. A research config can name a different set;
# this is the default the dashboard button uses.
DEFAULT_MODELS: tuple[str, ...] = (
    "naive", "seasonal_naive", "seasonal_naive_drift",
    "moving_average", "fourier", "ets",
)

# Members of the combination. Naive and drift are excluded: Aras et al. combine
# genuine candidate models, and including a sanity baseline drags the median
# towards a forecast nobody would ship.
DEFAULT_COMBINATION_MEMBERS: tuple[str, ...] = (
    "seasonal_naive", "seasonal_naive_drift", "moving_average", "fourier", "ets",
)

# Enough history to estimate a yearly cycle at all, with a hold-out left over.
MIN_PERIODS = 30

# The global tree model's name in the results table. Not in DEFAULT_MODELS
# because it is not a `Forecaster` - it is fitted across a panel of series and
# runs through its own fold runner.
GLOBAL_TREE_MODEL = "gbt_global"

# The series the panel is built around. The whole-business total is one series
# in the panel alongside the products, so the global model forecasts exactly
# the series the local models are scored on.
TOTAL_SERIES_ID = "__TOTAL__"

# How many products join the panel. One SKU has ~105 weekly points; pooling a
# hundred gives the tree thousands of training rows. Larger is slower without
# obviously being better, and the cut-off is reported with the results.
PANEL_PRODUCT_LIMIT = 100

# Features for the global model. The 52-week lag is what lets a tree see last
# year at all; it also costs 52 rows per series, which on two years of data is
# half the history - a trade-off worth naming in the report.
PANEL_FEATURE_SPEC = FeatureSpec(
    lags=(1, 2, 3, 4, 8, 12, 52),
    rolling_windows=(4, 12),
    calendar=True,
)

# Nominal coverage for the prediction interval.
INTERVAL_LEVEL = 0.80

MAX_HORIZON = 52
MAX_FOLDS = 10


def _open_session():
    """Seam for tests, matching `processing_service`.

    A background task cannot use the request's session - that one is closed
    when the response is sent - so it opens its own. Tests monkeypatch this to
    inject their transaction-scoped session instead, which is the only way the
    job's writes are visible to the assertions.
    """
    return SessionFactory()


def ensure_ready(dataset: Dataset) -> None:
    if dataset.status != "ready":
        raise Conflict(
            "This dataset has not finished processing yet.",
            code="DATASET_NOT_READY",
            details={"status": dataset.status},
        )


def config_hash(config: dict[str, Any]) -> str:
    """Stable digest of the declared experiment.

    Two runs with the same hash ran the same experiment. A different hash means
    something changed - which is the first question anyone auditing a results
    table should ask, and the reason the hash is stored next to the results.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def library_versions() -> dict[str, str]:
    """What the run was executed against (NFR-03).

    Reproducibility is a claim about inputs *and* environment. The pandas 2.3 /
    3.0 difference in this project's own history is the reason this is
    recorded rather than assumed.
    """
    import platform

    import scipy
    import sklearn

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
    }
    try:  # optional, and its absence is itself worth recording
        import xgboost

        versions["xgboost"] = xgboost.__version__
    except ImportError:
        versions["xgboost"] = "not installed"
    return versions


def validate_request(
    *,
    horizon: int,
    folds: int,
    season_length: int,
    models: list[str],
    window_style: str,
) -> None:
    """Refuse an impossible experiment before anything is queued."""
    if not 1 <= horizon <= MAX_HORIZON:
        raise ValidationFailed(f"Horizon must be between 1 and {MAX_HORIZON}.")
    if not 1 <= folds <= MAX_FOLDS:
        raise ValidationFailed(f"Folds must be between 1 and {MAX_FOLDS}.")
    if season_length < 1:
        raise ValidationFailed("Season length must be at least 1.")
    if window_style not in ("expanding", "sliding"):
        raise ValidationFailed("Window style must be 'expanding' or 'sliding'.")
    if not models:
        raise ValidationFailed("Choose at least one model.")

    known = {row["model"] for row in available_models()}
    unknown = sorted(set(models) - known)
    if unknown:
        raise ValidationFailed(
            f"Unknown model(s): {', '.join(unknown)}. Available: {', '.join(sorted(known))}."
        )

    unavailable = {
        row["model"]: row["unavailable_reason"]
        for row in available_models()
        if row["model"] in models and not row["available"]
    }
    if unavailable:
        raise ValidationFailed(
            "Some requested models cannot run on this server.",
            details={"models": unavailable},
        )


def start_run(
    session,
    dataset: Dataset,
    *,
    horizon: int = 12,
    folds: int = 4,
    season_length: int = 52,
    granularity: str = "week",
    value_column: str = "net_revenue",
    window_style: str = "expanding",
    models: list[str] | None = None,
    combination_rule: str = "median",
    combination_members: list[str] | None = None,
    primary_metric: str = PRIMARY_METRIC,
    series_scope: str = "total",
    series_key: str | None = None,
    filters: Filters | None = None,
    random_seed: int = 20260101,
) -> ForecastRun:
    """Record the experiment and queue it. Returns immediately with a run id."""
    ensure_ready(dataset)
    chosen = list(models or DEFAULT_MODELS)
    validate_request(
        horizon=horizon, folds=folds, season_length=season_length,
        models=chosen, window_style=window_style,
    )

    config = {
        "models": sorted(chosen),
        "combination": {
            "rule": combination_rule,
            "members": sorted(combination_members or DEFAULT_COMBINATION_MEMBERS),
        },
        "protocol": {
            "horizon": horizon,
            "folds": folds,
            "window_style": window_style,
            "season_length": season_length,
            "primary_metric": primary_metric,
        },
        "series": {
            "scope": series_scope,
            "key": series_key,
            "granularity": granularity,
            "value_column": value_column,
        },
        "filters": (filters or Filters()).cache_key() if filters else {},
        "random_seed": random_seed,
    }

    run = repo.create_run(
        session,
        dataset_id=dataset.id,
        status="queued",
        series_scope=series_scope,
        series_key=series_key,
        granularity=granularity,
        value_column=value_column,
        horizon=horizon,
        folds=folds,
        season_length=season_length,
        window_style=window_style,
        primary_metric=primary_metric,
        config_hash=config_hash(config),
        config=config,
        random_seed=random_seed,
        pipeline_version=dataset.pipeline_version,
        library_versions=library_versions(),
    )
    logger.info("Queued forecast run %s for dataset %s", run.id, dataset.id)
    return run


def execute_run(run_id: uuid.UUID) -> None:
    """The background task. Opens its own session and never raises into FastAPI."""
    session = _open_session()
    started = time.perf_counter()
    try:
        run = repo.get_run(session, run_id)
        if run is None:
            logger.warning("Forecast run %s disappeared before it started", run_id)
            return
        if run.status != "queued":
            logger.info("Forecast run %s is %s, not queued; skipping", run_id, run.status)
            return

        run.status = "running"
        session.commit()

        dataset = session.get(Dataset, run.dataset_id)
        if dataset is None:
            raise NotFound("The dataset was deleted while the run was queued.")

        _execute(session, run, dataset)
        run.status = "ready"
        run.finished_at = datetime.now(UTC)
        run.computed_ms = int((time.perf_counter() - started) * 1000)
        session.commit()
        logger.info("Forecast run %s finished in %s ms", run_id, run.computed_ms)

    except Exception as error:  # noqa: BLE001 - recorded on the row, not swallowed
        logger.exception("Forecast run %s failed", run_id)
        session.rollback()
        run = repo.get_run(session, run_id)
        if run is not None:
            run.status = "failed"
            run.error = f"{type(error).__name__}: {error}"
            run.finished_at = datetime.now(UTC)
            run.computed_ms = int((time.perf_counter() - started) * 1000)
            session.commit()
    finally:
        session.close()


def _execute(session, run: ForecastRun, dataset: Dataset) -> None:
    """Build the series, run the protocol, store everything."""
    filters = Filters()
    series, meta = repo.weekly_series(
        session, dataset.id, filters,
        granularity=run.granularity,
        value_column=run.value_column,
        date_max=pd.Timestamp(dataset.date_max) if dataset.date_max else None,
    )
    run.series_meta = meta

    if not meta.get("available") or len(series) < MIN_PERIODS:
        raise ValidationFailed(
            f"This series has {len(series)} usable {run.granularity}s. A "
            f"{run.horizon}-period horizon over {run.folds} folds needs at least "
            f"{MIN_PERIODS}. Widen the filters, or forecast at a coarser granularity."
        )

    factories = {
        name: _factory(name, run.season_length) for name in run.config["models"]
    }

    try:
        protocol = build_protocol(
            series, horizon=run.horizon, folds=run.folds, style=run.window_style
        )
    except SplitError as error:
        raise ValidationFailed(str(error)) from error

    # The panel lets the tree family into the comparison. Without it RQ1 would
    # compare statistical models with each other, which is a different question
    # from the one the research asks.
    panel, panel_meta = _build_panel(session, run, dataset, series)
    global_factories = (
        {GLOBAL_TREE_MODEL: lambda: GlobalTreeModel(
            spec=PANEL_FEATURE_SPEC, horizon=run.horizon
        )}
        if panel is not None else None
    )
    run.series_meta = {**(run.series_meta or {}), "panel": panel_meta}

    outcome = run_experiment(
        series, factories,
        horizon=run.horizon,
        folds=run.folds,
        season_length=run.season_length,
        combination_rule=run.config["combination"]["rule"],
        combination_members=run.config["combination"]["members"],
        metric=run.primary_metric,
        protocol=protocol,
        panel=panel,
        global_factories=global_factories,
        target_series_id=TOTAL_SERIES_ID if panel is not None else None,
    )

    run.protocol = outcome["protocol"]
    run.summary = _records(outcome["summary"])
    run.significance = outcome["significance"]
    run.combination = outcome["combination"]

    rows = [_result_row(result, run.horizon) for result in outcome["fold_results"]]

    # Selection happens now, from cross-validation only, and is written down
    # before the hold-out is touched.
    selected = _best_model(outcome["summary"], run.primary_metric)
    run.selected_model = selected
    session.flush()

    holdout = run_holdout(
        series, factories,
        horizon=run.horizon,
        season_length=run.season_length,
        protocol=protocol,
        selected=selected,
        panel=panel,
        global_factories=global_factories,
        target_series_id=TOTAL_SERIES_ID if panel is not None else None,
        combination_rule=run.config["combination"]["rule"],
        combination_members=run.config["combination"]["members"],
    )
    run.holdout_scored_at = datetime.fromisoformat(holdout["scored_at"])
    run.holdout_warning = holdout["warning"]
    rows.extend(
        _result_row(result, run.horizon, fold_override=HOLDOUT_FOLD)
        for result in holdout["results"]
    )

    repo.add_results(session, run, rows)

    # An interval for the model that was selected, sized on its CV errors and
    # checked against the hold-out it has not seen.
    if selected:
        run.intervals = _json_safe(build_intervals(
            outcome["_fold_objects"], holdout["_result_objects"], selected,
            level=INTERVAL_LEVEL,
        ))

    # §12.7: does the model rely on the features mutual information favours?
    if panel is not None:
        run.feature_importance = _json_safe(
            _feature_importance(panel, protocol, run)
        )


def _build_panel(session, run, dataset, series: pd.Series):
    """The target series plus the top products, on one shared calendar.

    The total is included as a series so the global model forecasts exactly
    what the local models are scored on. Returns `(None, meta)` when the panel
    cannot be built, and the reason travels with the run rather than the tree
    family silently vanishing from the results table.
    """
    try:
        panel, meta = repo.product_panel(
            session, dataset.id, Filters(),
            granularity=run.granularity,
            limit_products=PANEL_PRODUCT_LIMIT,
        )
    except Exception as error:   # noqa: BLE001 - a missing panel is not a failed run
        return None, {
            "available": False,
            "reason": f"The product panel could not be built: {error}",
        }

    if not meta.get("available") or panel.empty:
        return None, {**meta, "tree_family_excluded": True}

    # Restrict the products to the target's calendar and add the target itself.
    panel = panel[panel["period"].isin(series.index)]
    total = pd.DataFrame({
        "series_id": TOTAL_SERIES_ID,
        "period": series.index,
        "value": series.to_numpy(dtype="float64"),
    })
    combined = pd.concat([total, panel], ignore_index=True)

    meta = {
        **meta,
        "target_series_id": TOTAL_SERIES_ID,
        "series_including_target": int(combined["series_id"].nunique()),
        "feature_spec": PANEL_FEATURE_SPEC.as_dict(),
        "note": (
            "The whole-business total is one series in the panel alongside the "
            "products, so the global model forecasts the same series the local "
            "models are scored on. The global model has seen other series "
            "during the training window and the local models have not: that "
            "asymmetry is the point of the comparison, and the results table "
            "marks it with `uses_exogenous`."
        ),
    }
    return combined, meta


def _feature_importance(panel: pd.DataFrame, protocol, run) -> dict[str, Any]:
    """Permutation importance on held-out rows, compared with the Phase 4 MI rank.

    Fitted on the protocol's training region and permuted on the hold-out, so
    the scores describe what the model relies on to generalise rather than what
    it memorised.
    """
    from app.analytics import features as analytics_features

    spec = FeatureSpec(
        lags=PANEL_FEATURE_SPEC.lags,
        rolling_windows=PANEL_FEATURE_SPEC.rolling_windows,
        calendar=PANEL_FEATURE_SPEC.calendar,
        horizon=1,
    )
    built = build_features(panel, spec)
    if built.empty:
        return {
            "available": False,
            "reason": (
                "No rows survived feature building. A 52-period lag on a short "
                "series leaves nothing; report that rather than an empty table."
            ),
        }

    cutoff = protocol.holdout.train_index[-1]
    train = built[built["period"] <= cutoff]
    validation = built[built["period"] > cutoff]
    columns = feature_names(spec)

    if len(train) < 50 or validation.empty:
        return {
            "available": False,
            "reason": (
                f"Too few rows to attribute importance: {len(train)} training and "
                f"{len(validation)} validation rows after feature building."
            ),
        }

    model = GlobalTreeModel(spec=spec, horizon=1)
    estimator = model._make_estimator()
    estimator.fit(train[columns].to_numpy(), train["y"].to_numpy())

    scores = permutation_importance(
        estimator, validation[columns], validation["y"],
        random_state=run.random_seed or 20260101,
    )
    if not scores.get("available"):
        return scores

    # The Phase 4 side: the same mutual-information ranking the analytics
    # endpoint reports, computed on the same held-out rows so the two rankings
    # describe the same data. `score_features` already leaves a
    # `model_importance: None` placeholder for exactly this moment.
    agreement: dict[str, Any]
    mutual_scores: dict[str, float] = {}
    try:
        mi = analytics_features.score_features(
            validation[[*columns, "y"]], target_column="y"
        )
        if mi.get("available"):
            mutual_scores = {
                str(row["feature"]): float(row["mi_knn"])
                for row in mi["features"]
                if row.get("mi_knn") is not None
            }
            agreement = rank_agreement(to_score_map(scores["rows"]), mutual_scores)
        else:
            agreement = {
                "available": False,
                "reason": f"The mutual-information ranking was unavailable: {mi.get('reason')}",
            }
    except Exception as error:   # noqa: BLE001 - the permutation scores still stand
        logger.warning("Mutual-information comparison failed: %s", error)
        agreement = {"available": False, "reason": f"MI comparison failed: {error}"}

    return {
        "available": True,
        "training_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "permutation_importance": scores,
        "mutual_information": mutual_scores,
        "agreement_with_mutual_information": agreement,
        "completes": (
            "§12.7. Phase 4's feature analysis returns `model_importance: null` "
            "as a placeholder; this is the model-based half, and the agreement "
            "block is the comparison that makes the entropy/MI approach "
            "defensible rather than merely asserted."
        ),
    }


def _json_safe(value: Any) -> Any:
    """Plain JSON types only: numpy scalars and NaN are not JSONB-serialisable."""
    return json.loads(json.dumps(value, default=_coerce))


def _coerce(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if np.isnan(number) else number
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp,)):
        return str(value)
    return str(value)


def _factory(name: str, season_length: int):
    """Build a model by name, passing the season length to those that take one."""
    seasonal = {"seasonal_naive", "seasonal_naive_drift", "fourier"}
    if name in seasonal:
        return lambda n=name, m=season_length: get_model(n, season_length=m)
    return lambda n=name: get_model(n)


def _best_model(summary: pd.DataFrame, metric: str) -> str | None:
    """Lowest mean error on the CV folds. `summarise` already sorts that way."""
    column = f"mean_{metric.lower()}"
    usable = summary[summary[column].notna() & (summary["folds_scored"] > 0)]
    if usable.empty:
        return None
    return str(usable.iloc[0]["model"])


def _result_row(
    result: dict[str, Any], horizon: int, *, fold_override: int | None = None
) -> dict[str, Any]:
    """One `FoldResult` dict turned into a `forecast_results` row."""
    metrics = result.get("metrics") or {}

    def value(name: str) -> float | None:
        entry = metrics.get(name)
        if not entry or entry.get("value") is None:
            return None
        return float(entry["value"])

    return {
        "model": result["model"],
        "fold": fold_override if fold_override is not None else int(result["fold"]),
        "horizon": horizon,
        "uses_exogenous": bool((result.get("details") or {}).get("uses_exogenous", False)),
        "wape": value("WAPE"),
        "mase": value("MASE"),
        "mae": value("MAE"),
        "rmse": value("RMSE"),
        "mape": value("MAPE"),
        "smape": value("sMAPE"),
        "bias": value("Bias"),
        "metrics": metrics,
        "details": result.get("details") or {},
        "error": result.get("error"),
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame to JSON-safe records. NaN is not valid JSON; None is."""
    return json.loads(frame.to_json(orient="records"))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_run_or_404(session, dataset: Dataset, run_id: uuid.UUID) -> ForecastRun:
    run = repo.get_owned_run(session, run_id, dataset.id)
    if run is None:
        raise NotFound("No such forecast run for this dataset.")
    return run


def run_detail(session, run: ForecastRun) -> dict[str, Any]:
    """Everything about one run, in the shape the frontend and the report need."""
    results = repo.results_for_run(session, run.id)
    folds = [r for r in results if r.fold != HOLDOUT_FOLD]
    holdout = [r for r in results if r.fold == HOLDOUT_FOLD]

    return {
        "id": str(run.id),
        "dataset_id": str(run.dataset_id),
        "status": run.status,
        "error": run.error,
        "series": {
            "scope": run.series_scope,
            "key": run.series_key,
            "granularity": run.granularity,
            "value_column": run.value_column,
            **(run.series_meta or {}),
        },
        "protocol": run.protocol,
        "config": run.config,
        "config_hash": run.config_hash,
        "primary_metric": run.primary_metric,
        "summary": run.summary,
        "significance": run.significance,
        "combination": run.combination,
        "intervals": run.intervals,
        "feature_importance": run.feature_importance,
        "selection": {
            "selected_model": run.selected_model,
            "holdout_scored_at": (
                run.holdout_scored_at.isoformat() if run.holdout_scored_at else None
            ),
            "warning": run.holdout_warning,
            "note": (
                "The selected model was chosen on the cross-validation folds and "
                "written down before the hold-out was scored."
            ),
        },
        "cross_validation": [_result_dict(r) for r in folds],
        "holdout": [_result_dict(r) for r in holdout],
        "environment": {
            "library_versions": run.library_versions,
            "random_seed": run.random_seed,
            "pipeline_version": run.pipeline_version,
            "computed_ms": run.computed_ms,
        },
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _result_dict(row) -> dict[str, Any]:
    return {
        "model": row.model,
        "fold": row.fold,
        "is_holdout": row.fold == HOLDOUT_FOLD,
        "uses_exogenous": row.uses_exogenous,
        "wape": float(row.wape) if row.wape is not None else None,
        "mase": float(row.mase) if row.mase is not None else None,
        "mae": float(row.mae) if row.mae is not None else None,
        "rmse": float(row.rmse) if row.rmse is not None else None,
        "mape": float(row.mape) if row.mape is not None else None,
        "smape": float(row.smape) if row.smape is not None else None,
        "bias": float(row.bias) if row.bias is not None else None,
        "metrics": row.metrics,
        "error": row.error,
    }


def run_summary(run: ForecastRun) -> dict[str, Any]:
    """The light shape for the list and the polling endpoint."""
    return {
        "id": str(run.id),
        "status": run.status,
        "error": run.error,
        "series_scope": run.series_scope,
        "series_key": run.series_key,
        "granularity": run.granularity,
        "horizon": run.horizon,
        "folds": run.folds,
        "primary_metric": run.primary_metric,
        "selected_model": run.selected_model,
        "config_hash": run.config_hash,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "computed_ms": run.computed_ms,
    }


def list_runs(session, dataset: Dataset, *, limit: int = 20) -> dict[str, Any]:
    runs = repo.list_runs(session, dataset.id, limit=limit)
    return {"runs": [run_summary(run) for run in runs], "count": len(runs)}


def available_model_list() -> dict[str, Any]:
    """What this server can actually run, discovered before a run is started."""
    rows = available_models()
    # The global tree model is not a `Forecaster`, so it is not in the
    # registry. It still belongs in this list: a client building a model picker
    # from here would otherwise never see the tree family, which is one of the
    # three families RQ1 compares.
    rows.append({
        "model": GLOBAL_TREE_MODEL,
        "label": "Gradient-boosted trees (global)",
        "family": "tree",
        "uses_exogenous": True,
        "min_observations": 0,
        "available": True,
        "unavailable_reason": None,
        "note": (
            "Fitted across a panel of series rather than one, and added to every "
            "run automatically when a product panel can be built. It is not "
            "selectable in `models` because it does not take the single-series "
            "interface."
        ),
    })
    return {
        "models": rows,
        "defaults": {
            "models": list(DEFAULT_MODELS),
            "combination_members": list(DEFAULT_COMBINATION_MEMBERS),
            "horizon": 12,
            "folds": 4,
            "season_length": 52,
            "primary_metric": PRIMARY_METRIC,
            "global_models": [GLOBAL_TREE_MODEL],
            "interval_level": INTERVAL_LEVEL,
        },
    }


def recover_stuck_runs() -> int:
    """Called at start-up: a run left 'running' by a restart can never finish."""
    session = _open_session()
    try:
        count = repo.mark_stuck_runs_failed(session)
        session.commit()
        if count:
            logger.warning("Marked %s interrupted forecast run(s) as failed", count)
        return count
    finally:
        session.close()
