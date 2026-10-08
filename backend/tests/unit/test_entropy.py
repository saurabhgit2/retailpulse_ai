"""Entropy and mutual information, checked against values you can work out by hand.

These are the formulas the report explains, so the tests are written as
arithmetic rather than as "whatever the function returned last time".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics import entropy as E


def test_fair_coin_is_one_bit():
    assert E.entropy_from_counts([50, 50]) == pytest.approx(1.0)


def test_four_equally_likely_categories_are_two_bits():
    assert E.entropy_from_counts([1, 1, 1, 1]) == pytest.approx(2.0)


def test_quarter_three_quarters_is_the_textbook_value():
    # -(0.25 log2 0.25 + 0.75 log2 0.75) = 0.811278...
    assert E.entropy_from_counts([25, 75]) == pytest.approx(0.8112781244591328)


def test_a_single_category_carries_no_information():
    assert E.entropy_from_counts([7]) == 0.0
    assert E.normalised_entropy(pd.Series(["a"] * 10)) == 0.0


def test_empty_input_is_zero_not_an_error():
    assert E.entropy_from_counts([]) == 0.0


def test_normalised_entropy_is_one_when_categories_are_balanced():
    assert E.normalised_entropy(pd.Series(["a"] * 50 + ["b"] * 50)) == pytest.approx(1.0)


def test_a_concentrated_column_has_low_normalised_entropy():
    """Country on Online Retail II: one market dominates, so H/log2(k) is low."""
    country = pd.Series(["UK"] * 920 + ["France"] * 40 + ["Germany"] * 25 + ["EIRE"] * 15)
    assert E.normalised_entropy(country) < 0.4


def test_missing_values_are_ignored_rather_than_counted_as_a_category():
    with_missing = pd.Series(["a", "b", None, "a"])
    assert E.entropy(with_missing) == pytest.approx(E.entropy_from_counts([2, 1]))


def test_independent_variables_have_almost_no_mutual_information():
    rng = np.random.default_rng(0)
    left = pd.Series(rng.integers(0, 4, 4000))
    right = pd.Series(rng.integers(0, 4, 4000))
    assert E.mutual_information(left, right) < 0.01


def test_mutual_information_with_itself_equals_its_entropy():
    rng = np.random.default_rng(0)
    values = pd.Series(rng.integers(0, 4, 4000))
    assert E.mutual_information(values, values) == pytest.approx(E.entropy(values))


def test_mutual_information_is_never_negative():
    """Floating point can produce -2e-16 on independent columns; it is clamped."""
    rng = np.random.default_rng(1)
    left = pd.Series(rng.integers(0, 3, 500))
    right = pd.Series(rng.integers(0, 3, 500))
    assert E.mutual_information(left, right) >= 0.0


def test_knowing_x_removes_all_uncertainty_about_a_function_of_x():
    rng = np.random.default_rng(2)
    x = pd.Series(rng.integers(0, 4, 2000))
    y = x.map({0: "lo", 1: "lo", 2: "hi", 3: "hi"})
    assert E.conditional_entropy(y, x) == pytest.approx(0.0, abs=1e-9)
    assert E.mutual_information(y, x) == pytest.approx(E.entropy(y))


def test_symmetric_uncertainty_is_one_for_identical_columns():
    values = pd.Series(["a", "b", "c", "a", "b", "c"])
    assert E.symmetric_uncertainty(values, values) == pytest.approx(1.0)


def test_quantile_bins_survive_heavily_tied_data():
    """qcut raises when edges repeat; the wrapper drops duplicates instead."""
    tied = pd.Series([1] * 95 + [2, 3, 4, 5, 6])
    binned = E.quantile_bins(tied, 10)
    assert len(binned) == len(tied)


def test_profile_reports_mutual_information_at_three_bin_counts():
    """Binning changes the answer, so the sensitivity is part of the output."""
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"country": rng.choice(["UK", "FR", "DE"], 1000)})
    target = pd.Series(rng.gamma(2, 50, 1000))

    profile = E.profile_categorical(frame, "country", target)

    assert set(profile.mi_by_bins) == {3, 5, 10}
    assert profile.as_dict()["feature"] == "country"
    assert profile.distinct_values == 3
