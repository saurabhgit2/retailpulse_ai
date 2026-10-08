"""Distribution summaries: skew, robust spread and outlier counts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.distributions import describe_distribution


def test_a_right_skewed_distribution_has_its_mean_above_its_median():
    rng = np.random.default_rng(7)
    skewed = pd.Series(np.concatenate([rng.gamma(2, 10, 5000), [50_000]]))

    result = describe_distribution(skewed, field="revenue")

    assert result["count"] == 5001
    assert result["summary"]["median"] < result["summary"]["mean"]
    assert result["summary"]["strongly_skewed"] is True


def test_percentiles_are_ordered():
    rng = np.random.default_rng(8)
    result = describe_distribution(pd.Series(rng.gamma(2, 10, 2000)))
    percentiles = result["percentiles"]
    assert percentiles["25"] <= percentiles["50"] <= percentiles["75"] <= percentiles["99"]


def test_the_histogram_accounts_for_every_value():
    rng = np.random.default_rng(9)
    result = describe_distribution(pd.Series(rng.gamma(2, 10, 3000)), bins=40)
    assert len(result["histogram"]["counts"]) == 40
    assert sum(result["histogram"]["counts"]) == 3000


def test_outliers_are_counted_but_the_wording_says_they_are_kept():
    rng = np.random.default_rng(10)
    values = pd.Series(np.concatenate([rng.normal(100, 5, 1000), [1000, 1200]]))
    result = describe_distribution(values)

    assert result["outliers"]["tukey_count"] >= 2
    assert "never removed" in result["outliers"]["note"]


def test_a_constant_series_has_no_outliers_and_does_not_divide_by_zero():
    """With every value identical the MAD is zero; nothing can be unusual."""
    result = describe_distribution(pd.Series([5.0] * 100))
    assert result["summary"]["std_dev"] == 0
    assert result["outliers"]["robust_z_count"] == 0


def test_an_empty_series_is_reported_rather_than_raising():
    assert describe_distribution(pd.Series([], dtype=float))["count"] == 0


def test_normal_data_has_shape_statistics_near_zero():
    rng = np.random.default_rng(11)
    result = describe_distribution(pd.Series(rng.normal(100, 15, 20_000)))

    assert result["summary"]["skewness"] == pytest.approx(0.0, abs=0.1)
    assert result["summary"]["kurtosis_excess"] == pytest.approx(0.0, abs=0.2)
    assert result["summary"]["strongly_skewed"] is False


def test_the_coefficient_of_variation_is_withheld_when_the_mean_is_near_zero():
    values = pd.Series([-10.0, 10.0, -10.0, 10.0])
    assert describe_distribution(values)["summary"]["coefficient_of_variation"] is None
