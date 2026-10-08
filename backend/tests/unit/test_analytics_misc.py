"""Breakdowns, relationships, statistics, series profiles and feature scoring."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.breakdowns import rank_breakdown
from app.analytics.features import build_feature_table, score_features
from app.analytics.relationships import (
    correlation_matrix,
    correlation_pair,
    discount_proxy,
    price_quantity_relationship,
)
from app.analytics.series_profile import classify, profile_many, profile_series, spectral_entropy
from app.analytics.statistics import compare_groups, describe, normality_check

BREAKDOWN = pd.DataFrame({
    "product_code": [f"P{index}" for index in range(10)],
    "gross_revenue": [100, 90, 80, 70, 60, 50, 40, 30, 20, 10],
    "units": [1] * 10,
})


# --- breakdowns -------------------------------------------------------------

def test_shares_are_computed_against_the_whole_distribution_not_the_page():
    """"4% of revenue" must stay true when the limit changes."""
    top_three = rank_breakdown(BREAKDOWN, key="product_code", limit=3)
    all_ten = rank_breakdown(BREAKDOWN, key="product_code", limit=10)

    assert top_three["items"][0]["share"] == pytest.approx(all_ten["items"][0]["share"])
    assert top_three["total"] == 550


def test_the_listed_rows_and_the_remainder_account_for_everything():
    result = rank_breakdown(BREAKDOWN, key="product_code", limit=3)
    assert result["others"]["entities"] == 7
    assert result["items"][2]["cumulative_share"] + result["others"]["share"] == pytest.approx(1.0)


def test_ascending_order_lists_the_worst_performers_without_a_pareto_curve():
    result = rank_breakdown(BREAKDOWN, key="product_code", descending=False, limit=3)
    assert result["items"][0]["key"] == "P9"
    assert result["items"][0]["cumulative_share"] is None


def test_an_empty_breakdown_is_safe():
    assert rank_breakdown(pd.DataFrame(), key="product_code")["items"] == []


def test_an_unknown_sort_column_is_rejected():
    with pytest.raises(ValueError):
        rank_breakdown(BREAKDOWN, key="product_code", sort="profit")


# --- relationships ----------------------------------------------------------

def test_pearson_finds_a_linear_relationship():
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(0, 1, 500))
    y = 2 * x + rng.normal(0, 0.1, 500)
    assert correlation_pair(x, y)["pearson"] > 0.98


def test_spearman_beats_pearson_on_a_curved_relationship():
    """Reporting both side by side is the point: the gap is the finding."""
    linear = pd.Series(np.linspace(0, 1, 300))
    curved = pd.Series(np.exp(np.linspace(0, 5, 300)))
    result = correlation_pair(linear, curved)
    assert result["spearman"] > result["pearson"]


def test_too_few_pairs_returns_nothing_rather_than_a_meaningless_number():
    assert correlation_pair(pd.Series([1, 2]), pd.Series([1, 2]))["pearson"] is None


def test_the_correlation_matrix_reports_both_methods_and_their_disagreements():
    rng = np.random.default_rng(4)
    frame = pd.DataFrame({"a": rng.normal(0, 1, 300), "b": rng.normal(0, 1, 300)})
    frame["c"] = frame["a"] ** 3
    result = correlation_matrix(frame, ["a", "b", "c"])

    assert len(result["pearson"]) == 3
    assert len(result["spearman"]) == 3
    assert result["largest_disagreements"]
    assert "not causation" in result["note"]


def test_a_known_elasticity_is_recovered_from_the_log_log_fit():
    rng = np.random.default_rng(5)
    price = rng.uniform(1, 20, 400)
    units = 1000 * price ** -1.4 * rng.lognormal(0, 0.15, 400)
    frame = pd.DataFrame({
        "product_code": [f"P{index % 20}" for index in range(400)],
        "avg_unit_price": price,
        "units": units,
    })

    result = price_quantity_relationship(frame)

    assert result["elasticity_proxy"] == pytest.approx(-1.4, abs=0.2)
    assert len(result["caveats"]) >= 3   # the number never travels without them


def test_the_discount_proxy_compares_a_product_against_its_own_median_price():
    rng = np.random.default_rng(6)
    frame = pd.DataFrame({
        "product_code": [f"P{index % 20}" for index in range(400)],
        "avg_unit_price": rng.uniform(1, 20, 400),
        "units": rng.gamma(2, 10, 400),
    })
    result = discount_proxy(frame)
    assert result["available"] is True
    assert len(result["bands"]) >= 2


# --- statistics -------------------------------------------------------------

def test_describe_reports_mean_and_median_together():
    rng = np.random.default_rng(7)
    result = describe(pd.Series(rng.gamma(2, 10, 1000)))
    assert result["mean"] > 0 and result["median"] > 0
    assert result["mean_over_median"] > 1   # right-skewed


def test_two_groups_are_compared_with_mann_whitney():
    rng = np.random.default_rng(8)
    values = pd.Series(np.r_[rng.normal(100, 10, 300), rng.normal(120, 10, 300)])
    groups = pd.Series(["a"] * 300 + ["b"] * 300)

    result = compare_groups(values, groups)

    assert result["test"]["name"] == "Mann-Whitney U"
    assert result["test"]["significant"] is True
    assert abs(result["test"]["effect_size"]["value"]) > 0.5


def test_more_than_two_groups_use_kruskal_wallis():
    rng = np.random.default_rng(9)
    values = pd.Series(np.r_[
        rng.normal(100, 10, 300), rng.normal(120, 10, 300), rng.normal(140, 10, 300)
    ])
    groups = pd.Series(["a"] * 300 + ["b"] * 300 + ["c"] * 300)
    assert compare_groups(values, groups)["test"]["name"] == "Kruskal-Wallis H"


def test_identical_distributions_produce_a_negligible_effect_size():
    """Asserting "not significant" would be a 1-in-20 flake by construction.
    The effect size is the stable claim, and it is the one the module tells
    readers to use."""
    rng = np.random.default_rng(10)
    values = pd.Series(np.r_[rng.normal(100, 10, 300), rng.normal(100, 10, 300)])
    groups = pd.Series(["a"] * 300 + ["b"] * 300)

    effect = compare_groups(values, groups)["test"]["effect_size"]

    assert abs(effect["value"]) < 0.15
    assert effect["magnitude"] in {"negligible", "small"}


def test_groups_too_small_to_test_are_excluded_with_a_reason():
    result = compare_groups(pd.Series([1, 2, 3]), pd.Series(["a", "a", "b"]))
    assert result["test"] is None
    assert "two groups" in result["reason"]


def test_a_large_sample_carries_a_warning_about_reading_p_values():
    rng = np.random.default_rng(11)
    values = pd.Series(np.r_[rng.normal(100, 10, 8000), rng.normal(100.5, 10, 8000)])
    groups = pd.Series(["a"] * 8000 + ["b"] * 8000)

    test = compare_groups(values, groups)["test"]

    assert test["large_sample_warning"] is True
    assert "effect size" in test["interpretation_note"]


def test_normality_is_described_by_shape_rather_than_a_hypothesis_test():
    rng = np.random.default_rng(12)
    result = normality_check(pd.Series(rng.gamma(1, 10, 2000)))
    assert result["verdict"].startswith("strongly right")
    assert "deliberately not reported" in result["note"]


# --- series profiles --------------------------------------------------------

def test_a_regular_series_has_lower_spectral_entropy_than_noise():
    time = np.arange(104)
    regular = 50 + 10 * np.sin(2 * np.pi * time / 52)
    noise = np.random.default_rng(13).normal(50, 10, 104)
    assert spectral_entropy(regular) < spectral_entropy(noise)


def test_a_constant_series_has_no_spectral_entropy():
    assert spectral_entropy(np.ones(50)) is None


def test_intermittency_classes_follow_the_syntetos_boylan_quadrants():
    assert classify(1.0, 0.1) == "smooth"
    assert classify(1.0, 1.0) == "erratic"
    assert classify(2.0, 0.1) == "intermittent"
    assert classify(2.0, 1.0) == "lumpy"
    assert classify(None, None) == "unknown"


def test_a_steady_seller_is_classified_as_smooth():
    steady = pd.Series([10, 11, 9, 10, 12, 10, 11, 10] * 6)
    assert profile_series(steady)["intermittency_class"] == "smooth"


def test_a_sporadic_seller_has_an_average_demand_interval_above_one():
    sporadic = pd.Series([0, 0, 0, 5, 0, 0, 0, 6] * 6)
    assert profile_series(sporadic)["adi"] > 1.32


def test_profiling_many_series_reports_class_counts():
    rng = np.random.default_rng(14)
    weeks = pd.date_range("2023-01-02", periods=80, freq="W-MON")
    frame = pd.DataFrame({
        "product_code": np.repeat(["A", "B"], 80),
        "period": np.tile(weeks, 2),
        "units": np.r_[rng.poisson(20, 80), rng.poisson(1, 80)],
    })

    result = profile_many(frame, min_periods=26)

    assert result["series_count"] == 2
    assert sum(result["classes"].values()) == 2


def test_series_shorter_than_the_minimum_are_excluded_not_profiled():
    weeks = pd.date_range("2023-01-02", periods=10, freq="W-MON")
    frame = pd.DataFrame({"product_code": "A", "period": weeks, "units": range(10)})
    assert profile_many(frame, min_periods=26)["series"] == []


# --- feature analysis -------------------------------------------------------

def _weekly_sku_frame():
    rng = np.random.default_rng(15)
    frames = []
    for sku in range(12):
        level = rng.integers(5, 40)
        series = level + rng.normal(0, 3, 100) + 8 * np.sin(2 * np.pi * np.arange(100) / 52)
        frames.append(pd.DataFrame({
            "product_code": f"P{sku}",
            "period": pd.date_range("2022-01-03", periods=100, freq="W-MON"),
            "units": np.clip(series, 0, None),
            "avg_unit_price": rng.uniform(2, 8, 100),
        }))
    return pd.concat(frames, ignore_index=True)


def test_the_feature_table_contains_lags_rolling_statistics_and_calendar_features():
    table = build_feature_table(_weekly_sku_frame())
    expected = {"lag_1", "lag_8", "roll_mean_4", "roll_std_12", "week_of_year", "price_ratio"}
    assert expected <= set(table.columns)


def test_lagged_features_only_look_backwards():
    """A rolling mean that included the current week would leak the answer."""
    frame = pd.DataFrame({
        "product_code": "A",
        "period": pd.date_range("2022-01-03", periods=6, freq="W-MON"),
        "units": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    })
    table = build_feature_table(frame)

    assert pd.isna(table["lag_1"].iloc[0])
    assert table["lag_1"].iloc[1] == 10.0
    assert table["lag_1"].iloc[5] == 50.0


def test_features_are_scored_by_two_estimators_and_their_rankings_compared():
    result = score_features(build_feature_table(_weekly_sku_frame()))

    assert result["available"] is True
    assert result["rank_agreement"]["available"] is True
    assert "mi_by_bins" in result["features"][0]
    assert result["features"][0]["feature"].startswith(("lag_", "roll_"))


def test_scoring_states_its_limitations_and_defers_model_importance():
    result = score_features(build_feature_table(_weekly_sku_frame()))
    assert result["model_importance"] is None     # needs a trained model (Phase 5)
    assert len(result["limitations"]) >= 4


def test_too_little_data_to_score_is_refused_with_a_reason():
    frame = pd.DataFrame({
        "product_code": "A",
        "period": pd.date_range("2022-01-03", periods=12, freq="W-MON"),
        "units": range(12),
    })
    result = score_features(build_feature_table(frame))
    assert result["available"] is False
    assert "complete rows" in result["reason"]
