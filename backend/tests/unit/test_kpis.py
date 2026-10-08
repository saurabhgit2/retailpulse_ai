"""KPI definitions (architecture §12.4).

The rules being protected: net revenue subtracts returns, a KPI without its
source column is hidden rather than zero, and growth is withheld unless both
periods are genuinely comparable.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.analytics.kpis import PeriodTotals, build_kpis, concentration, gini, growth

CURRENT = PeriodTotals(
    gross_revenue=1000, returns_value=50, units=400, orders=100,
    active_customers=60, guest_revenue=200, lines=500,
)
PREVIOUS = PeriodTotals(
    gross_revenue=800, returns_value=40, units=320, orders=80,
    active_customers=55, guest_revenue=150, lines=420,
)


def test_net_revenue_subtracts_returns():
    values = build_kpis(CURRENT)["values"]
    assert values["net_revenue"] == 950


def test_average_order_value_is_gross_over_orders():
    assert build_kpis(CURRENT)["values"]["average_order_value"] == pytest.approx(10.0)


def test_return_rate_and_guest_share():
    values = build_kpis(CURRENT)["values"]
    assert values["return_rate"] == pytest.approx(0.05)
    assert values["guest_revenue_share"] == pytest.approx(0.2)


def test_growth_against_a_comparable_period():
    result = build_kpis(CURRENT, PREVIOUS, periods_comparable=True)
    assert result["growth"]["gross_revenue"] == pytest.approx(0.25)


def test_growth_is_withheld_when_the_periods_are_not_comparable():
    """Comparing a part period against a whole one invents a trend."""
    result = build_kpis(
        CURRENT, PREVIOUS, periods_comparable=False, comparison_note="final week is partial"
    )
    assert all(value is None for value in result["growth"].values())
    assert result["comparison"]["note"] == "final week is partial"
    assert result["comparison"]["comparable"] is False


def test_a_kpi_without_its_source_column_is_hidden_not_faked():
    """No invoice column means no order count, so AOV is None rather than 0."""
    totals = PeriodTotals(gross_revenue=500, orders=None)
    assert build_kpis(totals)["values"]["average_order_value"] is None


def test_growth_against_zero_is_undefined():
    assert growth(5, 0) is None
    assert growth(None, 10) is None


def test_gini_is_zero_when_everything_is_equal():
    assert gini(pd.Series([10, 10, 10, 10])) == pytest.approx(0.0, abs=1e-9)


def test_gini_approaches_one_when_one_entity_takes_everything():
    assert gini(pd.Series([0.0001] * 99 + [1000])) > 0.95


def test_gini_of_nothing_is_none():
    assert gini(pd.Series([], dtype=float)) is None


def test_concentration_reports_the_top_twenty_percent():
    result = concentration(pd.Series([100, 50, 30, 10, 5, 3, 2]))
    assert result["entities"] == 7
    assert result["top_count"] == 2          # ceil(7 * 0.2)
    assert result["top_share"] > 0.2         # revenue is concentrated
    assert result["gini"] is not None
