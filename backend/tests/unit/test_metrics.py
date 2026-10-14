"""Forecast error measures, and their behaviour on zeros.

Finding F7: weekly SKU sales are often zero, and that is where the percentage
measures go wrong. Most of these tests are about that.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.forecasting.metrics import (
    bias,
    evaluate,
    mae,
    mape,
    mase,
    revenue_weighted_mape,
    rmse,
    smape,
    wape,
)

ACTUAL = [100.0, 110.0, 90.0, 120.0]
PERFECT = list(ACTUAL)


def test_a_perfect_forecast_scores_zero_on_every_error_measure():
    results = evaluate(ACTUAL, PERFECT, training=ACTUAL)
    for name in ("MAE", "RMSE", "MAPE", "sMAPE", "WAPE", "Bias"):
        assert results[name].value == pytest.approx(0.0)


def test_mae_and_rmse_agree_when_every_error_is_the_same_size():
    predicted = [v + 10 for v in ACTUAL]
    assert mae(ACTUAL, predicted).value == pytest.approx(10.0)
    assert rmse(ACTUAL, predicted).value == pytest.approx(10.0)


def test_rmse_exceeds_mae_when_one_miss_is_large():
    """The reason both are reported: they rank models differently when the
    error distribution has a tail."""
    predicted = [100.0, 110.0, 90.0, 220.0]      # one big miss
    assert rmse(ACTUAL, predicted).value > mae(ACTUAL, predicted).value


def test_bias_is_signed_so_a_consistent_under_forecast_is_visible():
    low = [v - 10 for v in ACTUAL]
    assert bias(ACTUAL, low).value == pytest.approx(10.0)     # actual above forecast
    high = [v + 10 for v in ACTUAL]
    assert bias(ACTUAL, high).value == pytest.approx(-10.0)
    assert mae(ACTUAL, low).value == mae(ACTUAL, high).value  # magnitude is blind to it


def test_mape_excludes_zero_actuals_and_says_how_many():
    """Silently dropping them would report an error computed on an easier
    dataset than the one claimed."""
    actual = [100.0, 0.0, 50.0, 0.0]
    predicted = [110.0, 5.0, 45.0, 2.0]

    result = mape(actual, predicted)

    assert result.excluded == 2
    assert result.used == 2
    assert "2 of 4" in result.note
    assert result.value == pytest.approx((0.10 + 0.10) / 2 * 100)


def test_mape_is_undefined_rather_than_zero_when_every_actual_is_zero():
    result = mape([0.0, 0.0, 0.0], [1.0, 2.0, 3.0])
    assert result.value is None
    assert "undefined" in result.note


def test_wape_is_defined_on_a_window_containing_zeros():
    """This is why WAPE is a primary metric and MAPE is not."""
    actual = [100.0, 0.0, 50.0, 0.0]
    predicted = [110.0, 5.0, 45.0, 2.0]

    result = wape(actual, predicted)

    assert result.value == pytest.approx((10 + 5 + 5 + 2) / 150 * 100)
    assert result.used == 4          # nothing dropped
    assert result.excluded == 0


def test_wape_weights_periods_by_their_size():
    """A 50% miss on a 2-unit week should not count as much as a 50% miss on a
    200-unit week. MAPE says they are equal; WAPE does not."""
    small_miss = wape([200.0, 2.0], [200.0, 3.0]).value
    large_miss = wape([200.0, 2.0], [100.0, 2.0]).value
    assert large_miss > small_miss

    by_mape_small = mape([200.0, 2.0], [200.0, 3.0]).value
    by_mape_large = mape([200.0, 2.0], [100.0, 2.0]).value
    assert by_mape_small == pytest.approx(by_mape_large)   # MAPE cannot tell them apart


def test_smape_tolerates_a_zero_actual_when_the_forecast_is_not_zero():
    result = smape([0.0, 100.0], [10.0, 110.0])
    assert result.value is not None
    assert result.excluded == 0


def test_mase_scales_against_seasonal_naive_on_the_training_window():
    """A model that exactly matches seasonal naive scores 1.0 by construction."""
    rng = np.random.default_rng(0)
    training = pd.Series(1000 + rng.normal(0, 50, 60))
    actual = [1000.0, 1010.0, 990.0]
    # The seasonal-naive forecast with period 1 repeats the last training value.
    naive = [float(training.iloc[-1])] * 3

    scale = float(np.mean(np.abs(training.to_numpy()[1:] - training.to_numpy()[:-1])))
    expected = float(np.mean(np.abs(np.array(actual) - np.array(naive)))) / scale

    assert mase(actual, naive, training).value == pytest.approx(expected)


def test_mase_is_below_one_when_the_model_beats_the_naive_benchmark():
    training = pd.Series([100.0, 120.0, 80.0, 130.0, 70.0, 125.0] * 6)   # noisy
    actual = [100.0, 100.0, 100.0]
    good = [100.0, 100.0, 100.0]
    assert mase(actual, good, training).value == pytest.approx(0.0)


def test_mase_is_refused_rather_than_infinite_on_a_constant_training_series():
    """A flat history makes the scaling denominator zero. Returning inf would
    propagate into the mean rank and silently reorder the results table."""
    result = mase([1.0, 2.0], [1.0, 2.0], pd.Series([5.0] * 20))
    assert result.value is None
    assert "denominator is zero" in result.note


def test_mase_says_so_when_the_training_window_is_too_short_for_the_period():
    result = mase([1.0], [1.0], pd.Series([1.0, 2.0, 3.0]), season_length=52)
    assert result.value is None
    assert "too few" in result.note


def test_evaluate_reports_mase_as_unavailable_rather_than_omitting_it():
    """An absent row in a results table reads as 'the model failed'."""
    results = evaluate(ACTUAL, PERFECT)
    assert "MASE" in results
    assert results["MASE"].value is None
    assert "No training window" in results["MASE"].note


def test_mismatched_lengths_are_refused_with_both_numbers():
    with pytest.raises(ValueError) as error:
        mae([1.0, 2.0, 3.0], [1.0, 2.0])
    assert "3" in str(error.value) and "2" in str(error.value)


def test_the_paper_definition_of_wape_weights_products_by_revenue_share():
    """Auppakorn & Phumchusri (2022) weight each product's MAPE by its share of
    revenue. Their Table 3 reports WAPE 16.7 for XGBoost across seven products;
    this reproduces the arithmetic of that aggregation on their own figures."""
    per_product = pd.DataFrame({
        "product": ["Milk", "Baby Milk Powder", "Sauce", "Detergent",
                    "Disposable Diaper", "Soft Drink", "Cooking Oil"],
        "mape": [21.7, 10.2, 14.6, 23.6, 13.8, 18.8, 15.91],
        "weight": [0.15, 0.22, 0.08, 0.18, 0.13, 0.07, 0.17],
    })

    result = revenue_weighted_mape(per_product)

    assert result.value == pytest.approx(16.7, abs=0.1)
    assert result.used == 7


def test_a_series_with_no_usable_mape_is_dropped_and_the_weights_renormalised():
    per_product = pd.DataFrame({
        "mape": [20.0, None, 10.0],
        "weight": [0.5, 0.25, 0.25],
    })

    result = revenue_weighted_mape(per_product)

    assert result.excluded == 1
    # 0.5 and 0.25 renormalise to 2/3 and 1/3, not 0.5 and 0.25 of a short total.
    assert result.value == pytest.approx(20.0 * (2 / 3) + 10.0 * (1 / 3))
    assert "renormalised" in result.note
