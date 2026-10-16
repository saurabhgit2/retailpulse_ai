"""The parts of the forecasting service that need no database.

Validation, hashing and row shaping are pure functions, and they are where the
protocol discipline is actually implemented - so they are worth testing without
standing a database up.
"""

from __future__ import annotations

import pandas as pd
import pytest

import app.forecasting  # noqa: F401  - registers the models
from app.core.errors import Conflict, ValidationFailed
from app.db.models.forecast import HOLDOUT_FOLD
from app.services import forecast_service as service


class _Dataset:
    """Enough of a Dataset for the readiness check."""

    def __init__(self, status: str = "ready") -> None:
        self.status = status


def test_an_unprocessed_dataset_cannot_be_forecast():
    with pytest.raises(Conflict) as error:
        service.ensure_ready(_Dataset(status="processing"))
    assert "not finished processing" in str(error.value)


def test_a_ready_dataset_passes():
    service.ensure_ready(_Dataset())     # does not raise


def test_the_config_hash_ignores_key_order():
    """Two identical experiments written differently must hash the same, or
    'did this run use the same protocol?' becomes unanswerable."""
    first = {"models": ["a", "b"], "protocol": {"horizon": 12, "folds": 4}}
    second = {"protocol": {"folds": 4, "horizon": 12}, "models": ["a", "b"]}
    assert service.config_hash(first) == service.config_hash(second)


def test_the_config_hash_changes_when_the_protocol_changes():
    base = {"protocol": {"horizon": 12, "folds": 4}}
    changed = {"protocol": {"horizon": 13, "folds": 4}}
    assert service.config_hash(base) != service.config_hash(changed)


def test_an_unknown_model_is_refused_with_the_list_of_real_ones():
    with pytest.raises(ValidationFailed) as error:
        service.validate_request(
            horizon=12, folds=4, season_length=52,
            models=["prophet"], window_style="expanding",
        )
    message = str(error.value)
    assert "prophet" in message and "seasonal_naive" in message


def test_a_model_whose_library_is_missing_is_refused_before_the_run_starts():
    """An hour into an experiment is the wrong moment to find out."""
    from app.forecasting.base import available_models

    missing = [r["model"] for r in available_models() if not r["available"]]
    if not missing:
        pytest.skip("every optional dependency is installed here")

    with pytest.raises(ValidationFailed) as error:
        service.validate_request(
            horizon=12, folds=4, season_length=52,
            models=missing[:1], window_style="expanding",
        )
    assert "cannot run on this server" in str(error.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizon": 0},
        {"horizon": 500},
        {"folds": 0},
        {"folds": 99},
        {"season_length": 0},
        {"window_style": "random"},
        {"models": []},
    ],
)
def test_impossible_requests_are_refused(kwargs):
    base = dict(horizon=12, folds=4, season_length=52,
                models=["naive"], window_style="expanding")
    base.update(kwargs)
    with pytest.raises(ValidationFailed):
        service.validate_request(**base)


def test_the_best_model_is_the_lowest_mean_error_with_at_least_one_scored_fold():
    summary = pd.DataFrame({
        "model": ["broken", "good", "fair"],
        "mean_wape": [None, 5.0, 9.0],
        "folds_scored": [0, 3, 3],
    })
    assert service._best_model(summary, "WAPE") == "good"


def test_no_model_is_selected_when_every_one_failed():
    """Returning a name here would put a model that never ran into the report."""
    summary = pd.DataFrame({
        "model": ["a", "b"], "mean_wape": [None, None], "folds_scored": [0, 0],
    })
    assert service._best_model(summary, "WAPE") is None


def test_a_result_row_keeps_the_observation_counts_not_just_the_value():
    """A WAPE computed on 38 of 52 weeks is a different number from one
    computed on all 52, and the typed column alone cannot tell them apart."""
    result = {
        "model": "ets",
        "fold": 2,
        "error": None,
        "metrics": {
            "WAPE": {"name": "WAPE", "value": 12.5, "observations_used": 12},
            "MAPE": {"name": "MAPE", "value": 9.1, "observations_used": 8,
                     "observations_excluded": 4, "note": "4 of 12 periods had a zero actual"},
            "MASE": {"name": "MASE", "value": None, "observations_used": 0},
        },
        "details": {"uses_exogenous": False},
    }

    row = service._result_row(result, horizon=12)

    assert row["wape"] == 12.5
    assert row["mase"] is None                     # unavailable, not zero
    assert row["metrics"]["MAPE"]["observations_excluded"] == 4
    assert row["fold"] == 2


def test_the_holdout_row_is_written_as_fold_zero():
    """The hold-out has to be distinguishable from the folds used for
    selection, or the whole protocol argument collapses."""
    result = {"model": "naive", "fold": 1, "metrics": {}, "details": {}, "error": None}
    row = service._result_row(result, horizon=12, fold_override=HOLDOUT_FOLD)
    assert row["fold"] == HOLDOUT_FOLD == 0


def test_a_failed_model_still_produces_a_row_carrying_its_error():
    result = {"model": "ets", "fold": 1, "metrics": {}, "details": {},
              "error": "RuntimeError: singular matrix"}
    row = service._result_row(result, horizon=12)

    assert row["wape"] is None
    assert "singular matrix" in row["error"]


def test_records_turn_nan_into_null_rather_than_invalid_json():
    """NaN is not valid JSON. A JSONB column would reject it, and the run would
    fail at the very end after all the work was done."""
    frame = pd.DataFrame({"model": ["a"], "mean_wape": [float("nan")]})
    assert service._records(frame) == [{"model": "a", "mean_wape": None}]


def test_the_library_versions_recorded_include_the_ones_that_change_answers():
    versions = service.library_versions()
    for name in ("python", "numpy", "pandas", "scipy", "scikit-learn"):
        assert versions[name]
    # Absence is recorded too: "xgboost was not installed" is a fact about the
    # run, not a gap in the record.
    assert "xgboost" in versions


def test_the_default_combination_excludes_the_sanity_baselines():
    """Aras et al. combine genuine candidates. Including naive drags the median
    towards a forecast nobody would ship."""
    assert "naive" not in service.DEFAULT_COMBINATION_MEMBERS
    assert "drift" not in service.DEFAULT_COMBINATION_MEMBERS
    assert "ets" in service.DEFAULT_COMBINATION_MEMBERS


def test_the_seasonal_models_receive_the_season_length():
    model = service._factory("seasonal_naive", 26)()
    assert model.season_length == 26

    plain = service._factory("naive", 26)()
    assert not hasattr(plain, "season_length")
