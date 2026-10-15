"""Model-based feature importance, and the §12.7 agreement check.

The point of this module is a comparison, not a ranking: Phase 4's
entropy/mutual-information approach has no support in the seventeen supplied
papers, so showing empirically how it relates to a standard model-based method
is what makes it defensible. These tests check that the comparison is honest -
that it detects agreement when there is agreement, disagreement when there is
not, and refuses to report either when there is too little to go on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from app.forecasting.importance import (
    correlated_pairs,
    permutation_importance,
    rank_agreement,
    to_score_map,
)


def _fitted(rows: int = 600, seed: int = 0):
    """A model where `signal` matters, `weak` matters a little and `noise` not at all."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "signal": rng.normal(0, 1, rows),
        "weak": rng.normal(0, 1, rows),
        "noise": rng.normal(0, 1, rows),
    })
    target = 10 * frame["signal"] + 1.5 * frame["weak"] + rng.normal(0, 0.5, rows)

    split = rows // 2
    model = HistGradientBoostingRegressor(max_depth=3, random_state=0)
    model.fit(frame.iloc[:split].to_numpy(), target.iloc[:split].to_numpy())
    return model, frame.iloc[split:], target.iloc[split:]


def test_the_feature_that_drives_the_target_ranks_first():
    model, features, target = _fitted()
    result = permutation_importance(model, features, target, random_state=1)

    assert result["available"] is True
    assert result["rows"][0]["feature"] == "signal"
    assert result["rows"][0]["rank"] == 1


def test_a_pure_noise_feature_scores_near_zero():
    """Not clipped to zero: a feature the model does slightly better without is
    worth seeing as such."""
    model, features, target = _fitted()
    scores = {row["feature"]: row["importance"] for row in
              permutation_importance(model, features, target, random_state=1)["rows"]}

    assert scores["noise"] < scores["weak"] < scores["signal"]
    assert abs(scores["noise"]) < scores["signal"] / 10


def test_importance_is_measured_against_the_models_own_baseline():
    model, features, target = _fitted()
    result = permutation_importance(model, features, target, random_state=1)
    assert result["baseline_score"] > 0
    assert result["rows"][0]["relative"] > 0


def test_repeated_shuffles_give_a_spread_not_just_a_number():
    """One shuffle is one draw. The standard deviation is what says whether the
    ordering is stable."""
    model, features, target = _fitted()
    rows = permutation_importance(model, features, target, n_repeats=5, random_state=1)["rows"]
    assert all("std_dev" in row for row in rows)
    assert rows[0]["std_dev"] >= 0


def test_the_result_is_reproducible_for_a_fixed_seed():
    model, features, target = _fitted()
    first = permutation_importance(model, features, target, random_state=7)
    second = permutation_importance(model, features, target, random_state=7)
    assert [r["feature"] for r in first["rows"]] == [r["feature"] for r in second["rows"]]


def test_an_empty_validation_frame_is_reported_rather_than_raising():
    model, _, _ = _fitted()
    result = permutation_importance(model, pd.DataFrame(), pd.Series(dtype="float64"))
    assert result["available"] is False
    assert "No validation rows" in result["reason"]


def test_correlated_features_are_flagged_because_they_confound_the_attribution():
    """Shuffling lag_1 while lag_2 survives lets the model recover the signal,
    so both look unimportant. The report must not read that as irrelevance."""
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 300)
    frame = pd.DataFrame({
        "lag_1": base,
        "lag_2": base + rng.normal(0, 0.01, 300),   # near-duplicate
        "other": rng.normal(0, 1, 300),
    })

    pairs = correlated_pairs(frame)

    assert pairs
    assert set(pairs[0]["features"]) == {"lag_1", "lag_2"}
    assert pairs[0]["correlation"] > 0.9


def test_uncorrelated_features_produce_no_warning():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({name: rng.normal(0, 1, 300) for name in ("a", "b", "c")})
    assert correlated_pairs(frame) == []


def test_the_caveat_about_correlated_features_travels_with_the_scores():
    model, features, target = _fitted()
    result = permutation_importance(model, features, target, random_state=1)
    assert any("correlated" in caveat for caveat in result["caveats"])
    assert any("held-out" in caveat for caveat in result["caveats"])


# -- the §12.7 comparison ------------------------------------------------


def test_identical_rankings_agree_perfectly():
    scores = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}
    result = rank_agreement(scores, dict(scores))

    assert result["spearman_rho"] == pytest.approx(1.0)
    assert result["top_k_overlap_count"] == 5


def test_reversed_rankings_disagree_and_the_verdict_says_so():
    model_scores = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}
    information_scores = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0}

    result = rank_agreement(model_scores, information_scores)

    assert result["spearman_rho"] == pytest.approx(-1.0)
    assert "disagree" in result["verdict"]
    assert "limitation" in result["verdict"]


def test_a_weak_correlation_is_not_reported_as_either_success_or_failure():
    """The honest middle case. Claiming 'MI works' from rho = 0.4 would be
    exactly the overclaim this comparison exists to avoid."""
    rng = np.random.default_rng(3)
    names = [f"f{i}" for i in range(12)]
    model_scores = {n: float(v) for n, v in zip(names, rng.normal(0, 1, 12))}
    information_scores = {n: float(v) for n, v in zip(names, rng.normal(0, 1, 12))}

    verdict = rank_agreement(model_scores, information_scores)["verdict"]
    assert "weakly" in verdict or "disagree" in verdict


def test_too_few_shared_features_is_refused_rather_than_correlated():
    result = rank_agreement({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0})
    assert result["available"] is False
    assert "at least 3" in result["reason"]


def test_only_features_scored_by_both_methods_are_compared():
    model_scores = {"a": 3.0, "b": 2.0, "c": 1.0, "only_model": 9.0}
    information_scores = {"a": 3.0, "b": 2.0, "c": 1.0, "only_mi": 9.0}

    result = rank_agreement(model_scores, information_scores)

    assert result["features_compared"] == 3


def test_a_thin_comparison_carries_its_own_warning():
    """With five features a correlation of 0.9 means very little, and the
    number must not travel without the count."""
    scores = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}
    result = rank_agreement(scores, dict(scores))
    assert result["caveats"]
    assert "5 features" in result["caveats"][0]


def test_the_grounding_note_states_why_the_comparison_exists():
    scores = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}
    note = rank_agreement(scores, dict(scores))["grounding_note"]
    assert "no support in the seventeen supplied papers" in note


def test_score_maps_drop_features_with_no_score():
    rows = [
        {"feature": "a", "importance": 1.0},
        {"feature": "b", "importance": None},
    ]
    assert to_score_map(rows) == {"a": 1.0}
