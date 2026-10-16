"""The harness: run the ladder over the folds and produce the results table.

One function does the experiment, so there is exactly one place where "how the
comparison was run" is defined. Everything it does is declared in the arguments
and recorded in the output; nothing is decided by looking at a result.

The order is fixed and enforced:

1. Build the protocol and **check it for leakage** before anything is fitted.
2. For each fold, for each model: fit on the fold's training window only,
   predict the fold's horizon, score it.
3. Combine the member forecasts per fold, and score the combination the same way.
4. Rank, test for significance, and only then touch the hold-out.
5. Score the hold-out once and record the timestamp.

Step 4 is the one that matters. Every selection decision - which models, which
parameters, whether the combination helps - is made on cross-validation folds.
The hold-out is scored at the end, once, and its number is not allowed to
change anything. `run_holdout` records `scored_at` so the sequence is auditable.

A model that raises is caught, recorded with its error, and does not stop the
run. A three-hour experiment that dies at model six because one series has a
constant training window is a waste of three hours, and the failure is itself a
result worth reporting - it usually means a series should not have been in the
sample.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.forecasting import metrics as metric_module
from app.forecasting.base import ForecastResult, Forecaster
from app.forecasting.combination import combine
from app.forecasting.significance import compare_models
from app.forecasting.splits import Protocol, Split, assert_no_leakage, build_protocol

# The measure the ladder is ranked on. WAPE because it is defined on zero
# weeks, weights periods by size, and does not need a training window the way
# MASE does. Every other measure is still computed and reported.
PRIMARY_METRIC = "WAPE"

ModelFactory = Callable[[], Forecaster]


@dataclass
class FoldResult:
    model: str
    fold: int
    metrics: dict[str, metric_module.Metric]
    forecast: np.ndarray
    actual: np.ndarray
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "fold": self.fold,
            "error": self.error,
            "metrics": {name: m.as_dict() for name, m in self.metrics.items()},
            "details": self.details,
        }


def _score(
    actual: np.ndarray, forecast: np.ndarray, training: pd.Series, season_length: int
) -> dict[str, metric_module.Metric]:
    return metric_module.evaluate(
        actual, forecast, training=training, season_length=season_length
    )


def run_fold(
    series: pd.Series,
    split: Split,
    factories: dict[str, ModelFactory],
    *,
    season_length: int = 52,
) -> list[FoldResult]:
    """Fit and score every model on one fold."""
    train, test = split.take(series)
    actual = test.to_numpy(dtype="float64")
    results: list[FoldResult] = []

    for name, factory in factories.items():
        try:
            model = factory()
            ready, reason = type(model).is_available()
            if not ready:
                results.append(FoldResult(
                    model=name, fold=split.fold, metrics={},
                    forecast=np.full(len(actual), np.nan), actual=actual,
                    error=reason,
                ))
                continue

            model.fit(train)
            prediction: ForecastResult = model.predict(split.horizon)
            results.append(FoldResult(
                model=name,
                fold=split.fold,
                metrics=_score(actual, prediction.point, train, season_length),
                forecast=prediction.point,
                actual=actual,
                details=prediction.metadata,
            ))
        except Exception as error:      # noqa: BLE001 - recorded, not swallowed
            results.append(FoldResult(
                model=name, fold=split.fold, metrics={},
                forecast=np.full(len(actual), np.nan), actual=actual,
                error=f"{type(error).__name__}: {error}",
            ))
    return results


def run_fold_global(
    series: pd.Series,
    panel: pd.DataFrame,
    split: Split,
    global_factories: dict[str, Callable[[], Any]],
    *,
    target_series_id: str,
    season_length: int = 52,
) -> list[FoldResult]:
    """Fit a pooled model on many series, score it on the target one.

    A global model does not fit the `Forecaster` interface, and forcing it to
    would be dishonest about what it is: `Forecaster` takes one series, and the
    entire point of a global model is that one SKU has only ~105 weekly points
    and a tree ensemble needs thousands of rows. So it gets its own fold
    runner, and the results join the same table.

    **What makes this fair.** The panel is cut at the fold's last training
    period, exactly as the local models see only `split.train`. The model then
    forecasts the target series over the same test window, and is scored by the
    same function against the same actuals. The one asymmetry - the global
    model has seen *other series* during that period, which the local models
    have not - is real, is the point of the comparison, and is why the results
    table carries a `uses_exogenous` column. Say it in the method: this is
    local statistical models versus global learned models, not model A versus
    model B on identical information.
    """
    train, test = split.take(series)
    actual = test.to_numpy(dtype="float64")
    last_training_period = train.index[-1]

    # The cut is on the panel's own calendar, so a series with a different
    # start still contributes only its past.
    history = panel[panel["period"] <= last_training_period]

    results: list[FoldResult] = []
    for name, factory in global_factories.items():
        try:
            if history.empty:
                raise ValueError("No panel rows at or before this fold's training end.")
            model = factory()
            model.fit(history)
            point = np.asarray(model.predict(history, target_series_id), dtype="float64")

            if len(point) != split.horizon:
                raise ValueError(
                    f"{name} returned {len(point)} values for a horizon of "
                    f"{split.horizon}."
                )

            results.append(FoldResult(
                model=name,
                fold=split.fold,
                metrics=_score(actual, point, train, season_length),
                forecast=point,
                actual=actual,
                details={**model.describe(), "uses_exogenous": True},
            ))
        except Exception as error:      # noqa: BLE001 - recorded, not swallowed
            results.append(FoldResult(
                model=name, fold=split.fold, metrics={},
                forecast=np.full(len(actual), np.nan), actual=actual,
                error=f"{type(error).__name__}: {error}",
            ))
    return results


def errors_by_horizon_step(results: list[FoldResult], model: str) -> dict[int, list[float]]:
    """Signed errors per horizon step, pooled across folds. Feeds `intervals`."""
    collected: dict[int, list[float]] = {}
    for result in results:
        if result.model != model or result.error:
            continue
        for step, (actual, forecast) in enumerate(
            zip(result.actual, result.forecast, strict=True), start=1
        ):
            collected.setdefault(step, []).append(float(actual - forecast))
    return collected


def build_intervals(
    cv_results: list[FoldResult],
    holdout_results: list[FoldResult],
    model: str,
    *,
    level: float = 0.80,
) -> dict[str, Any]:
    """Prediction intervals for one model, sized from its own CV errors.

    The intervals come from the errors the model made **during
    cross-validation**, per horizon step, and are then checked against the
    hold-out. That order matters: sizing an interval on the window you then
    measure coverage on would guarantee good coverage and prove nothing.

    Returns the interval around the hold-out point forecast plus the observed
    coverage, so the report can put nominal and actual side by side. An 80%
    interval that contains the truth 55% of the time is worse than no interval,
    because it looks like information.
    """
    from app.forecasting.intervals import coverage, from_backtest

    errors = errors_by_horizon_step(cv_results, model)
    if not errors:
        return {
            "available": False,
            "reason": (
                f"'{model}' produced no usable cross-validation forecasts, so "
                f"there are no errors to size an interval from."
            ),
        }

    target = next(
        (r for r in holdout_results if r.model == model and not r.error), None
    )
    if target is None:
        return {
            "available": False,
            "reason": f"'{model}' has no hold-out forecast to put an interval around.",
        }

    interval = from_backtest(errors, target.forecast, level=level)
    observed = coverage(target.actual, interval["lower"], interval["upper"], level=level)

    return {
        "available": True,
        "model": model,
        "level": level,
        "method": interval["method"],
        "errors_used": interval["errors_used"],
        "notes": interval["notes"],
        "point": [float(v) for v in target.forecast],
        "lower": [None if np.isnan(v) else float(v) for v in interval["lower"]],
        "upper": [None if np.isnan(v) else float(v) for v in interval["upper"]],
        "actual": [float(v) for v in target.actual],
        "coverage": observed,
        "sizing_note": (
            "Sized on cross-validation errors and checked against the hold-out. "
            "Sizing on the hold-out itself would guarantee good coverage and "
            "demonstrate nothing."
        ),
    }


def results_table(results: list[FoldResult], metric: str = PRIMARY_METRIC) -> pd.DataFrame:
    """Models as rows, folds as columns, one error measure. Lower is better."""
    rows: dict[str, dict[int, float]] = {}
    for result in results:
        value = result.metrics.get(metric)
        rows.setdefault(result.model, {})[result.fold] = (
            np.nan if value is None or value.value is None else float(value.value)
        )
    table = pd.DataFrame(rows).sort_index()
    table.index.name = "fold"
    return table


def summarise(results: list[FoldResult], metric: str = PRIMARY_METRIC) -> pd.DataFrame:
    """One row per model: mean, spread, folds completed, exogenous flag."""
    rows = []
    for model in sorted({r.model for r in results}):
        mine = [r for r in results if r.model == model]
        values = [
            float(r.metrics[metric].value)
            for r in mine
            if not r.error and metric in r.metrics and r.metrics[metric].value is not None
        ]
        failures = [r.error for r in mine if r.error]
        rows.append({
            "model": model,
            f"mean_{metric.lower()}": float(np.mean(values)) if values else np.nan,
            f"sd_{metric.lower()}": float(np.std(values, ddof=1)) if len(values) > 1 else np.nan,
            f"worst_{metric.lower()}": float(np.max(values)) if values else np.nan,
            "folds_scored": len(values),
            "folds_failed": len(failures),
            "uses_exogenous": bool(mine[0].details.get("uses_exogenous", False)) if mine else False,
            "first_error": failures[0] if failures else None,
        })
    table = pd.DataFrame(rows)
    return table.sort_values(f"mean_{metric.lower()}", na_position="last").reset_index(drop=True)


def run_experiment(
    series: pd.Series,
    factories: dict[str, ModelFactory],
    *,
    horizon: int = 12,
    folds: int = 4,
    season_length: int = 52,
    combination_rule: str = "median",
    combination_members: list[str] | None = None,
    metric: str = PRIMARY_METRIC,
    protocol: Protocol | None = None,
    panel: pd.DataFrame | None = None,
    global_factories: dict[str, Callable[[], Any]] | None = None,
    target_series_id: str | None = None,
) -> dict[str, Any]:
    """Cross-validate the ladder. **Does not touch the hold-out.**

    Returns the fold results, the summary table, the combination, and the
    significance test - everything needed to decide what to run on the
    hold-out, and nothing that depends on having seen it.
    """
    declared = protocol or build_protocol(series, horizon=horizon, folds=folds)
    assert_no_leakage(declared.folds, declared.holdout)

    results: list[FoldResult] = []
    for split in declared.folds:
        results.extend(run_fold(series, split, factories, season_length=season_length))

    # Global models join the same table, scored on the same actuals by the same
    # function. Without them RQ1 compares statistical models with each other
    # rather than comparing families, which is a different question.
    global_notes: list[str] = []
    if global_factories:
        if panel is None or panel.empty or not target_series_id:
            global_notes.append(
                "Global models were requested but no panel (or no target series "
                "id) was supplied, so the tree family is missing from this "
                "comparison. Say so rather than reporting the ranking as if all "
                "families were present."
            )
        elif target_series_id not in set(panel["series_id"].astype(str)):
            global_notes.append(
                f"The target series '{target_series_id}' is not in the panel, so "
                f"the global models had nothing to forecast. The panel must "
                f"contain the series being compared."
            )
        else:
            for split in declared.folds:
                results.extend(run_fold_global(
                    series, panel, split, global_factories,
                    target_series_id=target_series_id,
                    season_length=season_length,
                ))

    # The combination is formed per fold from whichever members succeeded there,
    # so one model failing on one fold does not remove the combination entirely.
    members = combination_members or [
        name for name in factories if name not in {"naive", "drift"}
    ]
    combination_results: list[FoldResult] = []
    combination_notes: list[str] = []
    for split in declared.folds:
        train, test = split.take(series)
        available = {
            r.model: r.forecast
            for r in results
            if r.fold == split.fold and r.model in members and not r.error
            and not np.isnan(r.forecast).all()
        }
        if len(available) < 2:
            combination_notes.append(
                f"Fold {split.fold}: only {len(available)} member(s) produced a "
                f"forecast, so no combination was formed."
            )
            continue
        combined = combine(available, rule=combination_rule)   # type: ignore[arg-type]
        actual = test.to_numpy(dtype="float64")
        combination_results.append(FoldResult(
            model=f"combination_{combination_rule}",
            fold=split.fold,
            metrics=_score(actual, combined["point"], train, season_length),
            forecast=np.asarray(combined["point"]),
            actual=actual,
            details={
                "members": combined["members"],
                "rule": combination_rule,
                "mean_disagreement": combined["mean_disagreement"],
                "uses_exogenous": False,
            },
        ))
        combination_notes.extend(combined["notes"])

    everything = results + combination_results
    table = results_table(everything, metric)
    significance = compare_models(table.dropna(axis=1, how="any"))

    return {
        "protocol": declared.as_dict(),
        "metric": metric,
        "fold_results": [r.as_dict() for r in everything],
        # The objects themselves, for callers that need the arrays rather than
        # the JSON view - `build_intervals` needs the per-step forecasts. The
        # leading underscore marks them as not part of the stored record.
        "_fold_objects": everything,
        "per_fold_table": table,
        "summary": summarise(everything, metric),
        "significance": significance,
        "combination": {
            "rule": combination_rule,
            "members": members,
            "notes": combination_notes,
        },
        "global_models": {
            "requested": sorted(global_factories or {}),
            "target_series_id": target_series_id,
            "panel_series": (
                int(panel["series_id"].nunique()) if panel is not None and not panel.empty
                else 0
            ),
            "notes": global_notes,
        },
        "holdout_scored": False,
        "note": (
            "These are cross-validation results. Model selection ends here; the "
            "hold-out is scored once, afterwards, by run_holdout()."
        ),
    }


def run_holdout(
    series: pd.Series,
    factories: dict[str, ModelFactory],
    *,
    horizon: int = 12,
    season_length: int = 52,
    protocol: Protocol | None = None,
    selected: str | None = None,
    panel: pd.DataFrame | None = None,
    global_factories: dict[str, Callable[[], Any]] | None = None,
    target_series_id: str | None = None,
    combination_rule: str = "median",
    combination_members: list[str] | None = None,
) -> dict[str, Any]:
    """Score the locked hold-out. Called once, at the end, and timestamped.

    `selected` records which model cross-validation chose, *before* this ran.
    Passing it is not required but is strongly advised: it is the difference
    between "we selected on CV and confirmed on hold-out" and "we ran
    everything on the hold-out and reported the best", which are different
    experiments with different claims.

    **The combination is formed here too.** An earlier version ran only the
    individual models, so when cross-validation selected the combination - which
    is exactly what Aras et al. (2017) predict will happen - the selected model
    had no hold-out score at all, and no prediction interval could be built for
    it. A protocol that cannot score its own choice is not a protocol.
    """
    declared = protocol or build_protocol(series, horizon=horizon, folds=1)
    holdout = declared.holdout
    results = run_fold(series, holdout, factories, season_length=season_length)
    if global_factories and panel is not None and not panel.empty and target_series_id:
        results.extend(run_fold_global(
            series, panel, holdout, global_factories,
            target_series_id=target_series_id, season_length=season_length,
        ))

    train, test = holdout.take(series)
    members = combination_members or [
        name for name in factories if name not in {"naive", "drift"}
    ]
    available = {
        r.model: r.forecast for r in results
        if r.model in members and not r.error and not np.isnan(r.forecast).all()
    }
    combination_note: str | None = None
    if len(available) >= 2:
        combined = combine(available, rule=combination_rule)   # type: ignore[arg-type]
        actual = test.to_numpy(dtype="float64")
        results.append(FoldResult(
            model=f"combination_{combination_rule}",
            fold=holdout.fold,
            metrics=_score(actual, combined["point"], train, season_length),
            forecast=np.asarray(combined["point"]),
            actual=actual,
            details={
                "members": combined["members"],
                "rule": combination_rule,
                "mean_disagreement": combined["mean_disagreement"],
                "uses_exogenous": False,
            },
        ))
    else:
        combination_note = (
            f"Only {len(available)} member(s) produced a hold-out forecast, so no "
            f"combination was formed. If the combination was the selected model, "
            f"it has no hold-out score and that must be said rather than silently "
            f"reporting the next model down."
        )

    return {
        "scored_at": datetime.now(UTC).isoformat(),
        "selected_before_scoring": selected,
        "holdout": holdout.as_dict(),
        "results": [r.as_dict() for r in results],
        "_result_objects": results,
        "summary": summarise(results),
        "combination_note": combination_note,
        "holdout_scored": True,
        "warning": (
            None if selected else
            "No model was named as selected before the hold-out was scored. The "
            "hold-out can then only be reported as a descriptive result, not as "
            "confirmation of a selection made independently of it."
        ),
    }
