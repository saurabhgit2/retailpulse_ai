"""Ranked breakdowns: products, regions, categories (architecture §12.5).

One function serves all three, because "revenue by X, ranked, with each row's
share and the running cumulative share" is the same question each time. The
cumulative share is what turns a bar chart into a Pareto curve, and Pareto is
the shape retail decisions are usually made on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.kpis import concentration

SORTABLE = ("gross_revenue", "net_revenue", "units", "orders")


def rank_breakdown(
    frame: pd.DataFrame,
    *,
    key: str,
    sort: str = "gross_revenue",
    descending: bool = True,
    limit: int = 20,
    label_column: str | None = None,
) -> dict[str, object]:
    """Rank the rows of an aggregated frame and describe the distribution.

    `frame` has one row per entity (product, region, category) with the value
    columns already summed by SQL. Shares are computed against the **whole**
    distribution, not just the rows returned, so "this product is 4% of
    revenue" stays true when the limit changes.
    """
    if sort not in SORTABLE:
        raise ValueError(f"sort must be one of {SORTABLE}")

    if frame.empty or key not in frame.columns:
        return {
            "key": key, "sort": sort, "descending": descending,
            "items": [], "total": 0.0, "entities": 0,
            "others": None, "concentration": None,
        }

    data = frame.copy()
    for column in SORTABLE:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)

    if sort not in data.columns:
        raise ValueError(f"The aggregate has no column {sort!r}")

    total = float(data[sort].sum())
    ordered = data.sort_values(sort, ascending=not descending).reset_index(drop=True)

    # Cumulative share follows the ranking, so it is only a Pareto curve when
    # sorted descending. Ascending ("worst performers") gets shares but no
    # cumulative column, because a cumulative share from the bottom up would
    # invite the wrong reading.
    head = ordered.head(limit).copy()
    head["share"] = head[sort] / total if total else np.nan
    if descending:
        head["cumulative_share"] = head["share"].cumsum()
    else:
        head["cumulative_share"] = np.nan

    items = []
    for position, row in enumerate(head.itertuples(index=False), start=1):
        item: dict[str, object] = {
            "rank": position,
            "key": getattr(row, key),
            "share": None if pd.isna(row.share) else float(row.share),
            "cumulative_share": (
                None if pd.isna(row.cumulative_share) else float(row.cumulative_share)
            ),
        }
        if label_column and label_column in head.columns:
            item["label"] = getattr(row, label_column)
        for column in SORTABLE:
            if column in head.columns:
                item[column] = float(getattr(row, column))
        items.append(item)

    remainder = ordered.iloc[limit:]
    others = None
    if not remainder.empty:
        others = {"entities": int(len(remainder))}
        for column in SORTABLE:
            if column in remainder.columns:
                others[column] = float(remainder[column].sum())
        others["share"] = float(remainder[sort].sum() / total) if total else None

    return {
        "key": key,
        "sort": sort,
        "descending": descending,
        "entities": int(len(ordered)),
        "total": total,
        "items": items,
        "others": others,
        "concentration": concentration(ordered.set_index(key)[sort]) if descending else None,
    }
