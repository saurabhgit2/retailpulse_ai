"""The harness, combination, intervals and significance tests.

The end-to-end test at the bottom is the one to show a supervisor: a series
with a known seasonal structure, where seasonal naive must beat naive, and the
whole protocol runs without touching the hold-out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import app.forecasting  # noqa: F401  - registers the models
from app.forecasting.base import get_model
from app.forecasting.combination import combination_table, combine
from app.forecasting.evaluate import (
    errors_by_horizon_step,
    results_table,
    run_experiment,
    run_fold,
    run_holdout,
    summarise,
)
from app.forecasting.splits import build_protocol
from app.forecasting.intervals import coverage, from_backtest
from app.forecasting.significance import compare_models, friedman_test, pairwise_comparisons

WEEKS = pd.date_range("2010-01-04", periods=160, freq="W-MON")
TIME = np.arange(160)
SEASONAL = pd.Series(
    1000 + 3 * TIME + 250 * np.sin(2 * np.pi * TIME / 52)
    + np.random.default_rng(7).normal(0, 25, 160),
    index=WEEKS,
)

LADDER = {
    "naive": lambda: get_model("naive"),
    "seasonal_naive": lambda: get_model("seasonal_naive", season_length=52),
    "moving_average": lambda: get_model("moving_average", window=4),
    "fourier": lambda: get_model("fourier", season_length=52, harmonics=2),
    "ets": lambda: get_model("ets"),
}


# -- combination ---------------------------------------------------------


def test_the_median_combination_ignores_one_wild_member():
    """Aras et al.: the median is 'less prone to be affected by extreme values
    than the simple mean combination'. This is that property, measured."""
    members = {
        "a": np.array([100.0, 100.0]),
        "b": np.array([102.0, 102.0]),
        "c": np.array([98.0, 98.0]),
        "wild": np.array([10_000.0, 10_000.0]),
    }
    by_median = combine(members, "median")["point"]
    by_mean = combine(members, "mean")["point"]

    assert np.all(by_median < 110)
    assert np.all(by_mean > 2000)


def test_the_combination_reports_how_far_apart_its_members_are():
    """Wide disagreement at a horizon step is itself a signal, and it feeds the
    method card rather than being discarded."""
    result = combine({"a": np.array([100.0, 100.0]), "b": np.array([140.0, 100.0])}, "median")
    assert list(result["member_spread"]) == [40.0, 0.0]
    assert result["mean_disagreement"] == pytest.approx(20.0)


def test_least_squares_weights_are_refused_with_the_reason():
    """Not an omission: Aras et al. found LS weights worst of all the
    combination rules, and worse than the single models."""
    with pytest.raises(ValueError) as error:
        combine({"a": np.array([1.0])}, "ls_weights")   # type: ignore[arg-type]
    assert "deliberately not" in str(error.value)


def test_members_of_different_lengths_are_refused():
    with pytest.raises(ValueError) as error:
        combine({"a": np.array([1.0, 2.0]), "b": np.array([1.0])})
    assert "different lengths" in str(error.value)


def test_a_trim_on_too_few_members_is_flagged_rather_than_silently_useless():
    result = combine({"a": np.array([1.0]), "b": np.array([2.0]), "c": np.array([3.0])},
                     "trimmed_mean")
    assert any("removes nothing" in note for note in result["notes"])


def test_the_combination_table_counts_folds_won_not_just_the_average():
    """A combination can win on average while losing on most folds."""
    members = pd.DataFrame({"a": [10.0, 10.0, 10.0, 100.0], "b": [9.0, 9.0, 9.0, 9.0]})
    combined = pd.Series([9.5, 9.5, 9.5, 20.0])

    table = combination_table(members, combined).set_index("member")

    # 'a' is beaten by the combination on all four folds; 'b' beats it on all
    # four, even though 'b' and the combination have similar mean error. An
    # average alone would not show that.
    assert table.loc["a", "folds_combination_better"] == 4
    assert table.loc["b", "folds_combination_better"] == 0
    assert table.loc["b", "mean_improvement"] < 0


# -- significance --------------------------------------------------------


def test_friedman_detects_a_consistent_winner():
    errors = pd.DataFrame({
        "good": [1.0, 1.1, 0.9, 1.2, 1.0, 1.1, 0.95, 1.05, 1.0, 1.1],
        "fair": [2.0, 2.1, 1.9, 2.2, 2.0, 2.1, 1.95, 2.05, 2.0, 2.1],
        "poor": [3.0, 3.1, 2.9, 3.2, 3.0, 3.1, 2.95, 3.05, 3.0, 3.1],
    })
    result = friedman_test(errors)

    assert result["available"] is True
    assert result["reject_null_at_05"] is True
    assert result["best_by_mean_rank"] == "good"
    assert result["mean_ranks"]["good"] < result["mean_ranks"]["poor"]


def test_friedman_does_not_reject_when_the_models_are_interchangeable():
    rng = np.random.default_rng(3)
    errors = pd.DataFrame({name: rng.normal(10, 1, 12) for name in ("a", "b", "c")})
    assert friedman_test(errors)["reject_null_at_05"] is False


def test_friedman_needs_three_models_and_says_so():
    errors = pd.DataFrame({"a": [1.0, 2.0], "b": [2.0, 3.0]})
    result = friedman_test(errors)
    assert result["available"] is False
    assert "at least 3" in result["reason"]


def test_few_blocks_are_reported_as_a_caveat_not_hidden():
    """Four CV folds is what this project has. The chi-square approximation is
    poor there, and the number has to travel with that warning."""
    errors = pd.DataFrame({"a": [1.0, 1.1, 0.9, 1.2], "b": [2.0, 2.1, 1.9, 2.2],
                           "c": [3.0, 3.1, 2.9, 3.2]})
    result = friedman_test(errors)
    assert any("approximate" in caveat for caveat in result["caveats"])


def test_a_model_that_failed_on_some_folds_is_counted_out_loud():
    errors = pd.DataFrame({
        "a": [1.0, 1.1, 0.9, 1.2],
        "b": [2.0, np.nan, 1.9, 2.2],
        "c": [3.0, 3.1, 2.9, 3.2],
    })
    result = friedman_test(errors)
    assert result["blocks_dropped"] == 1
    assert any("dropped" in caveat for caveat in result["caveats"])


def test_pairwise_comparisons_are_bonferroni_corrected():
    rng = np.random.default_rng(11)
    errors = pd.DataFrame({
        "a": rng.normal(10, 1, 20),
        "b": rng.normal(12, 1, 20),
        "c": rng.normal(14, 1, 20),
    })
    table = pairwise_comparisons(errors)

    assert len(table) == 3                                  # 3 choose 2
    assert (table["p_value_bonferroni"] >= table["p_value"]).all()
    assert table.attrs["correction"] == "Bonferroni, 3 comparisons"


def test_the_summary_refuses_to_name_a_winner_when_the_test_does_not_reject():
    rng = np.random.default_rng(5)
    errors = pd.DataFrame({name: rng.normal(10, 1, 12) for name in ("a", "b", "c")})

    summary = compare_models(errors)["summary"]

    assert "not distinguishable from noise" in summary
    assert "should not be presented as a finding" in summary


def test_the_summary_demands_effect_sizes_when_it_does_reject():
    errors = pd.DataFrame({
        "good": [1.0, 1.1, 0.9, 1.2, 1.0, 1.1, 0.95, 1.05, 1.0, 1.1, 1.0, 1.1],
        "fair": [2.0, 2.1, 1.9, 2.2, 2.0, 2.1, 1.95, 2.05, 2.0, 2.1, 2.0, 2.1],
        "poor": [3.0, 3.1, 2.9, 3.2, 3.0, 3.1, 2.95, 3.05, 3.0, 3.1, 3.0, 3.1],
    })
    summary = compare_models(errors)["summary"]
    assert "effect sizes" in summary


# -- intervals -----------------------------------------------------------


def test_intervals_widen_with_the_horizon_when_the_errors_do():
    errors = {step: list(np.random.default_rng(step).normal(0, 10 * step, 30))
              for step in range(1, 7)}
    point = np.full(6, 100.0)

    result = from_backtest(errors, point, level=0.80)
    widths = result["upper"] - result["lower"]

    assert widths[-1] > widths[0] * 3


def test_an_interval_is_shifted_by_a_biased_models_errors():
    """Signed errors, deliberately: a model that is consistently 20 low should
    get an interval shifted up, not a symmetric one around a biased point."""
    errors = {step: [20.0] * 30 for step in range(1, 4)}   # actual always 20 above
    result = from_backtest(errors, np.full(3, 100.0), level=0.80)

    assert result["lower"][0] == pytest.approx(120.0)
    assert result["upper"][0] == pytest.approx(120.0)


def test_the_lower_bound_is_not_negative_for_sales():
    errors = {1: list(np.random.default_rng(0).normal(0, 500, 40))}
    result = from_backtest(errors, np.array([50.0]), level=0.95)
    assert result["lower"][0] >= 0.0


def test_a_step_with_too_few_errors_borrows_the_pooled_distribution_and_says_so():
    errors = {1: [1.0] * 30, 2: [2.0, 3.0]}
    result = from_backtest(errors, np.full(2, 100.0))

    assert any("pooled" in note for note in result["notes"])


def test_coverage_calls_a_too_narrow_interval_what_it_is():
    actual = np.arange(100, dtype=float)
    lower, upper = actual - 0.1, actual + 0.1
    lower[:50] = actual[:50] + 5        # half the points fall outside

    result = coverage(actual, lower, upper, level=0.80)

    assert result["observed"] == pytest.approx(0.5)
    assert "too narrow" in result["verdict"]


def test_coverage_reports_its_own_uncertainty():
    actual = np.arange(10, dtype=float)
    result = coverage(actual, actual - 1, actual + 1, level=0.80)
    assert "carries its own uncertainty" in result["caveat"]


# -- the harness ---------------------------------------------------------


def test_the_experiment_runs_the_whole_ladder_on_every_fold():
    outcome = run_experiment(SEASONAL, LADDER, horizon=12, folds=3)
    table = outcome["per_fold_table"]

    assert set(LADDER) <= set(table.columns)
    assert "combination_median" in table.columns
    assert len(table) == 3


def test_seasonal_naive_beats_naive_when_seasonality_dominates():
    """The sanity check on the whole harness. If this fails, the folds, the
    models or the metrics are wrong, and nothing downstream can be trusted."""
    flat_seasonal = pd.Series(
        1000 + 250 * np.sin(2 * np.pi * TIME / 52)
        + np.random.default_rng(7).normal(0, 25, 160),
        index=WEEKS,
    )
    summary = run_experiment(flat_seasonal, LADDER, horizon=12, folds=3)["summary"]
    scores = summary.set_index("model")["mean_wape"]

    assert scores["seasonal_naive"] < scores["naive"]


def test_a_trend_handicaps_plain_seasonal_naive_and_the_drift_variant_fixes_it():
    """A measured property of the benchmark, not an assumption. On SEASONAL
    the trend adds 3 per week, so 156 over a season; plain seasonal naive
    repeats last year's level and is systematically that much low, which is
    enough for naive to beat it. Online Retail II trends, so the drift-adjusted
    variant is the benchmark that belongs in the results table - and the
    comparison between the two is worth a paragraph in the discussion."""
    ladder = {
        "naive": lambda: get_model("naive"),
        "seasonal_naive": lambda: get_model("seasonal_naive", season_length=52),
        "seasonal_naive_drift": lambda: get_model("seasonal_naive_drift", season_length=52),
    }
    scores = run_experiment(SEASONAL, ladder, horizon=12, folds=3)["summary"] \
        .set_index("model")["mean_wape"]

    assert scores["seasonal_naive"] > scores["naive"]            # the handicap
    assert scores["seasonal_naive_drift"] < scores["naive"]      # corrected
    assert scores["seasonal_naive_drift"] < scores["seasonal_naive"]


def test_the_experiment_does_not_score_the_holdout():
    """Selection happens on CV folds only. This is the property that makes the
    hold-out number meaningful when it is finally produced."""
    outcome = run_experiment(SEASONAL, LADDER, horizon=12, folds=3)

    assert outcome["holdout_scored"] is False
    holdout_end = outcome["protocol"]["holdout"]["test_end"]
    for fold in outcome["protocol"]["folds"]:
        assert fold["test_end"] < holdout_end


def test_a_model_that_raises_is_recorded_and_does_not_stop_the_run():
    """A three-hour experiment must not die at model six."""
    class Exploding:
        @staticmethod
        def is_available():
            return True, None

        def fit(self, *args, **kwargs):
            raise RuntimeError("deliberate failure")

    ladder = {**LADDER, "broken": lambda: Exploding()}
    outcome = run_experiment(SEASONAL, ladder, horizon=12, folds=3)
    summary = outcome["summary"].set_index("model")

    assert summary.loc["broken", "folds_failed"] == 3
    assert "deliberate failure" in summary.loc["broken", "first_error"]
    assert summary.loc["seasonal_naive", "folds_scored"] == 3


def test_the_summary_flags_which_models_used_exogenous_features():
    summary = run_experiment(SEASONAL, LADDER, horizon=12, folds=3)["summary"]
    assert set(summary["uses_exogenous"]) == {False}        # none of these do


def test_errors_are_collected_per_horizon_step_for_the_intervals():
    """Step 1's interval must come from step-1 errors and step 12's from
    step-12 errors, or the interval does not widen with the horizon."""
    protocol = build_protocol(SEASONAL, horizon=12, folds=3)
    results = []
    for split in protocol.folds:
        results.extend(run_fold(SEASONAL, split, LADDER, season_length=52))

    steps = errors_by_horizon_step(results, "seasonal_naive")

    assert set(steps) == set(range(1, 13))
    assert all(len(values) == 3 for values in steps.values())   # one per fold

    interval = from_backtest(steps, np.full(12, 1000.0))
    assert np.all(interval["upper"] >= interval["lower"])


def test_the_holdout_is_scored_once_and_timestamped():
    outcome = run_holdout(SEASONAL, LADDER, horizon=12, selected="seasonal_naive")

    assert outcome["holdout_scored"] is True
    assert outcome["selected_before_scoring"] == "seasonal_naive"
    assert outcome["warning"] is None
    assert outcome["scored_at"]


def test_scoring_the_holdout_without_declaring_a_selection_is_warned_about():
    """'We selected on CV and confirmed on hold-out' and 'we ran everything on
    the hold-out and reported the best' are different experiments."""
    outcome = run_holdout(SEASONAL, LADDER, horizon=12)
    assert "No model was named as selected" in outcome["warning"]


def test_the_results_table_is_folds_by_models():
    outcome = run_experiment(SEASONAL, LADDER, horizon=12, folds=3)
    table = outcome["per_fold_table"]
    assert table.index.name == "fold"
    assert table.notna().any().any()
