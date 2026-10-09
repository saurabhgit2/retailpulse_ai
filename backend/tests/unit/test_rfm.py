"""RFM aggregation.

Follows Chen, Sain & Guo (2012), the paper behind the Online Retail dataset:
three variables aggregated per customer, as the input to the clustering that
happens in Phase 5b. The tests protect the definitions, not the clustering.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.rfm import build_rfm

END = pd.Timestamp("2011-12-09")


def _customers(count: int = 400, seed: int = 0, frequency=None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    last = END - pd.to_timedelta(rng.integers(0, 300, count), unit="D")
    first = last - pd.to_timedelta(rng.integers(0, 400, count), unit="D")
    return pd.DataFrame({
        "customer": [f"C{index}" for index in range(count)],
        "first_purchase": first,
        "last_purchase": last,
        "frequency": rng.integers(1, 30, count) if frequency is None else frequency,
        "monetary_gross": rng.gamma(2, 500, count),
        "returns_value": rng.gamma(1, 20, count),
        "units": rng.integers(1, 500, count),
        "lines": rng.integers(1, 200, count),
    })


def test_recency_is_measured_from_the_end_of_the_data_not_today():
    """The dataset is historical. Measuring from the present would make every
    customer's recency grow each time the report is run."""
    result = build_rfm(_customers())
    assert result["as_of"] == "2011-12-09"


def test_every_customer_lands_in_exactly_one_group():
    customers = _customers()
    result = build_rfm(customers)
    assert sum(group["customers"] for group in result["segments"]) == len(customers)


def test_revenue_shares_across_groups_sum_to_one():
    result = build_rfm(_customers())
    assert sum(group["monetary_share"] for group in result["segments"]) == pytest.approx(1.0)


def test_monetary_is_net_of_returns():
    """A customer who returns most of what they buy is not a top customer."""
    customers = _customers(count=10, seed=1)
    customers["monetary_gross"] = 1000.0
    customers["returns_value"] = [0.0] * 5 + [900.0] * 5

    result = build_rfm(customers)
    table = pd.DataFrame(result["table"])

    assert table["monetary"].max() == pytest.approx(1000.0)
    assert table["monetary"].min() == pytest.approx(100.0)
    assert "less returns" in result["monetary_definition"]


def test_best_customers_score_highest_on_every_dimension():
    """Recency is inverted when scored, so that 5 means "good" on all three and
    the scores are comparable."""
    result = build_rfm(_customers())
    table = pd.DataFrame(result["table"])

    best_recency = table.loc[table["r_score"] == table["r_score"].max(), "recency_days"]
    worst_recency = table.loc[table["r_score"] == table["r_score"].min(), "recency_days"]
    assert best_recency.max() < worst_recency.min()

    best_money = table.loc[table["m_score"] == table["m_score"].max(), "monetary"]
    worst_money = table.loc[table["m_score"] == table["m_score"].min(), "monetary"]
    assert best_money.min() > worst_money.max()


def test_champions_are_more_recent_and_spend_more_than_hibernating():
    groups = {group["segment"]: group for group in build_rfm(_customers())["segments"]}
    if "champions" in groups and "hibernating" in groups:
        assert groups["champions"]["median_recency_days"] < groups["hibernating"]["median_recency_days"]
        assert groups["champions"]["median_monetary"] > groups["hibernating"]["median_monetary"]


def test_customers_who_bought_once_do_not_break_the_quintiles():
    """qcut raises when every edge is identical. The ranking is done first and
    duplicate edges dropped, so the scores compress instead of failing."""
    result = build_rfm(_customers(frequency=1))

    assert result["available"] is True
    assert any("only once" in note for note in result["clustering_notes"])


def test_the_scaling_warning_from_the_source_paper_is_carried_forward():
    """Chen et al. state that k-means is sensitive to outliers and to variables
    on incomparable scales. Phase 5b should inherit that, not rediscover it."""
    notes = build_rfm(_customers())["clustering_notes"]
    assert any("Chen" in note for note in notes)
    assert any("standardised" in note for note in notes)


def test_skewed_monetary_values_trigger_a_transform_suggestion():
    customers = _customers(count=200, seed=3)
    customers["monetary_gross"] = np.concatenate([
        np.full(199, 100.0), [500_000.0]
    ])
    result = build_rfm(customers)
    notes = " ".join(result["clustering_notes"])
    assert "transform before standardising" in notes


def test_the_labels_are_not_presented_as_a_clustering_result():
    caveats = build_rfm(_customers())["caveats"]
    assert any("RQ2" in caveat for caveat in caveats)
    assert any("not a clustering result" in caveat for caveat in caveats)


def test_guests_are_called_out_as_excluded():
    assert any("Guest" in caveat for caveat in build_rfm(_customers())["caveats"])


def test_an_empty_customer_set_is_reported_rather_than_raising():
    assert build_rfm(pd.DataFrame())["available"] is False


def test_a_log_transform_is_not_suggested_when_monetary_value_can_be_negative():
    """Customers whose returns exceed their purchases have negative net value.
    log(x) is undefined there, so advice to "take a log" would send the
    clustering work into a wall of NaNs."""
    customers = _customers(count=200, seed=4)
    customers.loc[:4, "returns_value"] = 99_999.0     # five net-negative customers

    result = build_rfm(customers)
    notes = " ".join(result["clustering_notes"])

    assert result["negative_monetary_customers"] >= 5
    assert result["minimum_monetary"] < 0
    assert "plain log will not work" in notes
    assert "signed" in notes and "excluding them" in notes


def test_an_all_positive_monetary_distribution_keeps_the_simple_advice():
    customers = _customers(count=200, seed=5)
    customers["returns_value"] = 0.0

    result = build_rfm(customers)
    notes = " ".join(result["clustering_notes"])

    assert result["negative_monetary_customers"] == 0
    assert "plain log will not work" not in notes


def test_the_skew_direction_matches_its_sign():
    """A negative skewness described as "right-skewed" is the kind of wrong
    detail that survives into a report."""
    customers = _customers(count=200, seed=4)
    customers.loc[:4, "returns_value"] = 99_999.0     # drags the tail left

    result = build_rfm(customers)
    notes = " ".join(result["clustering_notes"])

    assert result["distributions"]["monetary"]["skewness"] < 0
    assert "left-skewed" in notes
    assert "right-skewed" not in notes
