"""The global model in the comparison, and the intervals built from it.

RQ1 asks how model *families* compare. Without the global tree model in the
table the answer would be about five statistical models, which is a different
question. These tests check that it competes on equal terms - same folds, same
actuals, same scoring - and that the one asymmetry is declared rather than
hidden.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import app.forecasting  # noqa: F401  - registers the models
from app.forecasting.base import get_model
from app.forecasting.evaluate import build_intervals, run_experiment, run_holdout
from app.forecasting.features import FeatureSpec
from app.forecasting.splits import build_protocol
from app.forecasting.trees import GlobalTreeModel

WEEKS = pd.date_range("2009-12-07", periods=106, freq="W-MON")
TIME = np.arange(106)
TARGET = "__TOTAL__"

SPEC = FeatureSpec(lags=(1, 2, 4, 8, 52), rolling_windows=(4, 12), calendar=True)


def _series() -> pd.Series:
    rng = np.random.default_rng(5)
    values = (120_000 + 300 * TIME
              + 45_000 * np.sin(2 * np.pi * (TIME - 14) / 52)
              + rng.normal(0, 9_000, 106))
    return pd.Series(values, index=WEEKS)


def _panel(series: pd.Series, products: int = 20) -> pd.DataFrame:
    rng = np.random.default_rng(6)
    frames = [pd.DataFrame({
        "series_id": TARGET, "period": series.index, "value": series.to_numpy()
    })]
    for index in range(products):
        base = 3_000 * (index + 1)
        frames.append(pd.DataFrame({
            "series_id": f"SKU{index}",
            "period": series.index,
            "value": base + 0.3 * base * np.sin(2 * np.pi * (TIME - 14) / 52)
                     + rng.normal(0, 0.08 * base, 106),
        }))
    return pd.concat(frames, ignore_index=True)


LOCAL = {
    "naive": lambda: get_model("naive"),
    "seasonal_naive": lambda: get_model("seasonal_naive", season_length=52),
    "fourier": lambda: get_model("fourier", season_length=52, harmonics=2),
    "ets": lambda: get_model("ets"),
}
GLOBAL = {"gbt_global": lambda: GlobalTreeModel(spec=SPEC, horizon=12)}


def test_the_tree_family_appears_in_the_same_results_table():
    series, panel = _series(), _panel(_series())
    outcome = run_experiment(
        series, LOCAL, horizon=12, folds=3,
        panel=panel, global_factories=GLOBAL, target_series_id=TARGET,
    )

    models = set(outcome["summary"]["model"])
    assert "gbt_global" in models
    assert "seasonal_naive" in models          # scored side by side


def test_the_global_model_is_scored_on_every_fold():
    series, panel = _series(), _panel(_series())
    outcome = run_experiment(
        series, LOCAL, horizon=12, folds=3,
        panel=panel, global_factories=GLOBAL, target_series_id=TARGET,
    )
    row = outcome["summary"].set_index("model").loc["gbt_global"]

    assert row["folds_scored"] == 3
    assert row["folds_failed"] == 0


def test_the_asymmetry_is_declared_in_the_results_table():
    """A model that saw other series during training is not competing on equal
    information, and A1 §8.4 requires that to be visible."""
    series, panel = _series(), _panel(_series())
    outcome = run_experiment(
        series, LOCAL, horizon=12, folds=3,
        panel=panel, global_factories=GLOBAL, target_series_id=TARGET,
    )
    flags = outcome["summary"].set_index("model")["uses_exogenous"]

    assert flags["gbt_global"] is True or flags["gbt_global"] == True   # noqa: E712
    assert not flags["seasonal_naive"]


def test_the_global_model_sees_no_data_past_its_folds_training_end():
    """The leakage check for the pooled path. A spike planted after the first
    fold's training window must not change that fold's forecast."""
    series = _series()
    panel = _panel(series)
    protocol = build_protocol(series, horizon=12, folds=3)
    cutoff = protocol.folds[0].train_index[-1]

    contaminated = panel.copy()
    future = contaminated["period"] > cutoff
    contaminated.loc[future, "value"] = 1e9

    clean_run = run_experiment(
        series, {}, horizon=12, folds=3, protocol=protocol,
        panel=panel, global_factories=GLOBAL, target_series_id=TARGET,
    )
    dirty_run = run_experiment(
        series, {}, horizon=12, folds=3, protocol=protocol,
        panel=contaminated, global_factories=GLOBAL, target_series_id=TARGET,
    )

    clean = next(r for r in clean_run["_fold_objects"]
                 if r.model == "gbt_global" and r.fold == 1)
    dirty = next(r for r in dirty_run["_fold_objects"]
                 if r.model == "gbt_global" and r.fold == 1)

    assert np.allclose(clean.forecast, dirty.forecast)


def test_a_missing_panel_is_reported_rather_than_dropping_the_family_silently():
    """The worst failure here would be a results table that looks complete but
    is missing a family nobody noticed was absent."""
    outcome = run_experiment(
        _series(), LOCAL, horizon=12, folds=3,
        global_factories=GLOBAL, target_series_id=TARGET,   # no panel
    )

    notes = outcome["global_models"]["notes"]
    assert notes
    assert "tree family is missing" in notes[0]
    assert "gbt_global" not in set(outcome["summary"]["model"])


def test_a_target_absent_from_the_panel_is_reported():
    series = _series()
    panel = _panel(series)
    panel = panel[panel["series_id"] != TARGET]      # the total is not in it

    outcome = run_experiment(
        series, LOCAL, horizon=12, folds=3,
        panel=panel, global_factories=GLOBAL, target_series_id=TARGET,
    )

    assert any("not in the panel" in note for note in outcome["global_models"]["notes"])


def test_the_panel_size_is_recorded_with_the_results():
    series, panel = _series(), _panel(_series())
    outcome = run_experiment(
        series, LOCAL, horizon=12, folds=3,
        panel=panel, global_factories=GLOBAL, target_series_id=TARGET,
    )
    assert outcome["global_models"]["panel_series"] == 21     # 20 products + the total


# -- intervals -----------------------------------------------------------


def test_intervals_are_sized_on_cv_errors_and_checked_on_the_holdout():
    series, panel = _series(), _panel(_series())
    protocol = build_protocol(series, horizon=12, folds=3)

    outcome = run_experiment(series, LOCAL, horizon=12, folds=3, protocol=protocol,
                             panel=panel, global_factories=GLOBAL, target_series_id=TARGET)
    selected = outcome["summary"].iloc[0]["model"]
    holdout = run_holdout(series, LOCAL, horizon=12, protocol=protocol, selected=selected,
                          panel=panel, global_factories=GLOBAL, target_series_id=TARGET)

    interval = build_intervals(outcome["_fold_objects"], holdout["_result_objects"], selected)

    assert interval["available"] is True
    assert interval["errors_used"] == 36          # 3 folds x 12 steps
    assert len(interval["lower"]) == len(interval["upper"]) == 12
    assert interval["coverage"]["available"] is True
    assert "cross-validation" in interval["sizing_note"]


def test_the_interval_brackets_its_own_point_forecast():
    series, panel = _series(), _panel(_series())
    protocol = build_protocol(series, horizon=12, folds=3)
    outcome = run_experiment(series, LOCAL, horizon=12, folds=3, protocol=protocol)
    selected = outcome["summary"].iloc[0]["model"]
    holdout = run_holdout(series, LOCAL, horizon=12, protocol=protocol, selected=selected)

    interval = build_intervals(outcome["_fold_objects"], holdout["_result_objects"], selected)

    for low, high in zip(interval["lower"], interval["upper"], strict=True):
        assert low <= high


def test_a_model_with_no_cv_forecasts_gets_no_interval_and_says_why():
    series = _series()
    protocol = build_protocol(series, horizon=12, folds=3)
    outcome = run_experiment(series, LOCAL, horizon=12, folds=3, protocol=protocol)
    holdout = run_holdout(series, LOCAL, horizon=12, protocol=protocol, selected="naive")

    interval = build_intervals(outcome["_fold_objects"], holdout["_result_objects"], "nonexistent")

    assert interval["available"] is False
    assert "no usable cross-validation forecasts" in interval["reason"]


def test_coverage_is_reported_against_what_was_promised():
    series = _series()
    protocol = build_protocol(series, horizon=12, folds=3)
    outcome = run_experiment(series, LOCAL, horizon=12, folds=3, protocol=protocol)
    selected = outcome["summary"].iloc[0]["model"]
    holdout = run_holdout(series, LOCAL, horizon=12, protocol=protocol, selected=selected)

    coverage = build_intervals(
        outcome["_fold_objects"], holdout["_result_objects"], selected, level=0.80
    )["coverage"]

    assert coverage["nominal"] == 0.80
    assert 0.0 <= coverage["observed"] <= 1.0
    assert coverage["verdict"]
    assert "own uncertainty" in coverage["caveat"]


def test_the_combination_is_scored_on_the_holdout_too():
    """The defect this guards against: cross-validation selected
    `combination_median`, the hold-out table did not contain it, and no
    prediction interval could be built for the one model that was chosen. A
    protocol that cannot score its own choice is not a protocol."""
    series = _series()
    protocol = build_protocol(series, horizon=12, folds=3)

    outcome = run_experiment(series, LOCAL, horizon=12, folds=3, protocol=protocol)
    selected = outcome["summary"].iloc[0]["model"]

    holdout = run_holdout(series, LOCAL, horizon=12, protocol=protocol, selected=selected)
    scored = set(holdout["summary"]["model"])

    assert "combination_median" in scored
    assert selected in scored, f"the selected model {selected!r} was not scored"


def test_an_interval_can_be_built_for_a_selected_combination():
    series = _series()
    protocol = build_protocol(series, horizon=12, folds=3)
    outcome = run_experiment(series, LOCAL, horizon=12, folds=3, protocol=protocol)
    holdout = run_holdout(series, LOCAL, horizon=12, protocol=protocol,
                          selected="combination_median")

    interval = build_intervals(
        outcome["_fold_objects"], holdout["_result_objects"], "combination_median"
    )

    assert interval["available"] is True
    assert len(interval["lower"]) == 12
