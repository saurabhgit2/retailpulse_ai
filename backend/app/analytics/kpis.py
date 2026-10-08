"""KPI definitions (architecture §12.4).

Every figure on the dashboard is defined here once, so the dashboard cannot
contradict itself and "how exactly do you calculate AOV?" has one answer.

Two rules carried from the architecture:

* a KPI that needs a field the dataset does not have is **hidden, not faked**
  (`None` rather than 0);
* growth is reported **only when both periods are complete**. Comparing a part
  week against a whole one manufactures a decline that is not there.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PeriodTotals:
    """What SQL aggregates for one period. All sums, cheap to compute."""

    gross_revenue: float = 0.0        # sum of revenue on non-return lines
    returns_value: float = 0.0        # absolute value of revenue on return lines
    units: float = 0.0                # sum of quantity on non-return lines
    orders: int | None = None         # distinct invoice_id, or None without invoices
    active_customers: int | None = None   # distinct non-null customer_id
    guest_revenue: float = 0.0        # revenue on lines with no customer
    lines: int = 0                    # row count, for sanity checks

    @property
    def net_revenue(self) -> float:
        return self.gross_revenue - self.returns_value


def _ratio(numerator: float, denominator: float | None) -> float | None:
    """Divide, or return None when the denominator is missing or zero.

    A None here means "cannot be computed", which the UI shows as a dash. It is
    not the same as zero, and conflating them is how dashboards start lying.
    """
    if denominator is None or denominator == 0 or not np.isfinite(denominator):
        return None
    return float(numerator) / float(denominator)


def growth(current: float | None, previous: float | None) -> float | None:
    """(current - previous) / previous, or None when it is not meaningful."""
    if current is None or previous is None:
        return None
    if previous == 0 or not np.isfinite(previous):
        return None
    return (float(current) - float(previous)) / abs(float(previous))


def build_kpis(
    current: PeriodTotals,
    previous: PeriodTotals | None = None,
    *,
    periods_comparable: bool = False,
    comparison_note: str | None = None,
) -> dict[str, object]:
    """The KPI block for one filtered period, with an optional comparison.

    `periods_comparable` is the caller's assertion that both windows are the
    same length and both complete. When it is False every growth figure is
    None and the note explains why, rather than the number quietly misleading.
    """
    aov = _ratio(current.gross_revenue, current.orders)
    return_rate = _ratio(current.returns_value, current.gross_revenue)
    guest_share = _ratio(current.guest_revenue, current.gross_revenue)

    previous_values: dict[str, float | int | None] = {}
    growth_values: dict[str, float | None] = {}

    if previous is not None:
        previous_aov = _ratio(previous.gross_revenue, previous.orders)
        previous_values = {
            "gross_revenue": previous.gross_revenue,
            "net_revenue": previous.net_revenue,
            "returns_value": previous.returns_value,
            "units": previous.units,
            "orders": previous.orders,
            "active_customers": previous.active_customers,
            "average_order_value": previous_aov,
        }
        if periods_comparable:
            growth_values = {
                "gross_revenue": growth(current.gross_revenue, previous.gross_revenue),
                "net_revenue": growth(current.net_revenue, previous.net_revenue),
                "units": growth(current.units, previous.units),
                "orders": growth(current.orders, previous.orders),
                "active_customers": growth(current.active_customers, previous.active_customers),
                "average_order_value": growth(aov, previous_aov),
            }
        else:
            growth_values = dict.fromkeys(
                ["gross_revenue", "net_revenue", "units", "orders",
                 "active_customers", "average_order_value"],
                None,
            )

    return {
        "values": {
            "gross_revenue": float(current.gross_revenue),
            "returns_value": float(current.returns_value),
            "net_revenue": float(current.net_revenue),
            "units": float(current.units),
            "orders": current.orders,
            "average_order_value": aov,
            "active_customers": current.active_customers,
            "return_rate": return_rate,
            "guest_revenue_share": guest_share,
            "lines": current.lines,
        },
        "previous": previous_values or None,
        "growth": growth_values or None,
        "comparison": {
            "comparable": bool(periods_comparable and previous is not None),
            "note": comparison_note,
        },
    }


def gini(values: pd.Series | np.ndarray) -> float | None:
    """Gini coefficient of a non-negative distribution.

    0 = every product earns the same; 1 = one product earns everything. Computed
    from the sorted cumulative share, which is the Lorenz-curve definition:

        G = (2 * sum(i * x_i) / (n * sum(x))) - (n + 1) / n
    """
    series = pd.Series(values).dropna().astype(float)
    series = series[series >= 0]
    if series.empty or series.sum() <= 0:
        return None
    ordered = np.sort(series.to_numpy())
    n = ordered.size
    if n == 1:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2.0 * np.sum(index * ordered)) / (n * ordered.sum()) - (n + 1) / n)


def concentration(revenue_by_entity: pd.Series, top_fraction: float = 0.2) -> dict[str, object]:
    """Pareto share and Gini for products or customers (architecture §12.4).

    `top_share` answers "what fraction of revenue comes from the top 20% of
    products?". In most retail datasets the answer is well above 20%, and how
    far above is the interesting part.
    """
    series = pd.Series(revenue_by_entity).dropna().astype(float)
    series = series[series > 0]
    if series.empty:
        return {"entities": 0, "top_fraction": top_fraction, "top_share": None, "gini": None}

    ordered = series.sort_values(ascending=False)
    count = len(ordered)
    take = max(1, int(np.ceil(count * top_fraction)))
    return {
        "entities": count,
        "top_fraction": top_fraction,
        "top_count": take,
        "top_share": float(ordered.iloc[:take].sum() / ordered.sum()),
        "gini": gini(ordered),
    }
