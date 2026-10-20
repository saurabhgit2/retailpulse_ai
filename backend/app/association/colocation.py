"""Putting the rules to work: which products should be stored together.

Jirapatsil & Phumchusri, "Market Basket Analysis for Fresh Products location
improvement: A case study of E-Commerce Business Warehouse", MSIE 2022, ACM,
https://doi.org/10.1145/3535782.3535786.

Their paper is the answer to "so what". They mine rules on 2,366 transactions,
observe that "many pairs with high Lift number are far away from each other",
rearrange the warehouse so associated products sit together, and measure the
result: average picking distance per order falls from 31.8 m to 14.5 m, a
54.4% reduction. The rules are not the finding; the rearrangement is.

**What is reproduced here, and what is not.** Their warehouse is known to them
and not to us - 100 locations across four refrigerators and two shelves, with
measured walking distances. Online Retail II contains no layout, so metres
cannot be computed and any figure in metres would be invented.

What *can* be computed on the real baskets is the quantity a layout is chosen
to minimise. Group the catalogue into zones, then for each historical order
count how many distinct zones a picker must visit to fill it. That number is
real, it is derived entirely from the data, and a layout that lowers it is
exactly the layout their method is looking for. Reporting "zones visited per
order fell by X%" is the honest form of their claim; reporting metres would not
be.

**The grouping is greedy, and deliberately so.** Optimal assignment of products
to capacitated zones is NP-hard, and a heuristic that is explained is worth
more here than an optimum that is asserted. The method: start a zone with the
unplaced product having the greatest total affinity, repeatedly add whichever
unplaced product has the highest summed affinity to the products already in the
zone, and close the zone when it is full. Products with no affinity at all are
placed afterwards by popularity, because they still need somewhere to live.

**The baseline matters more than the method.** A grouping always looks good
until it is compared with something. Two baselines are reported: random
assignment averaged over several seeds, which is the honest null, and
popularity order, which is what a warehouse without analysis usually drifts
into. Their 54.4% is a before-and-after on one real layout; the equivalent
here is against a stated baseline, and the baseline is named with the number.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np

from app.association.rules import Rule

AFFINITY_MEASURES = ("normalised_lift", "lift", "confidence", "support", "leverage")


def affinity_graph(
    rules: Iterable[Rule], *, weight: str = "normalised_lift"
) -> dict[tuple[int, int], float]:
    """Undirected product-to-product affinity from the rules.

    A rule is directed; a shelf is not. Both directions of the same pair are
    therefore collapsed by taking the stronger of the two, and multi-item rules
    contribute to every pair they span.

    `normalised_lift` is the default rather than plain lift, because lift rises
    with the number of baskets containing neither product (Ni et al. 2020,
    §4.3) and a catalogue of several thousand products makes that almost every
    basket. Using plain lift here would let two rare items dominate the layout.
    """
    if weight not in AFFINITY_MEASURES:
        raise ValueError(
            f"Unknown affinity measure {weight!r}. "
            f"Available: {', '.join(AFFINITY_MEASURES)}."
        )

    edges: dict[tuple[int, int], float] = {}
    for rule in rules:
        value = getattr(rule, weight, None)
        if value is None or not np.isfinite(value) or value <= 0:
            continue
        items = sorted(rule.antecedent | rule.consequent)
        for position, left in enumerate(items):
            for right in items[position + 1:]:
                key = (int(left), int(right))
                edges[key] = max(edges.get(key, 0.0), float(value))
    return edges


def assign_zones(
    catalogue: Iterable[int],
    affinity: dict[tuple[int, int], float],
    *,
    zone_capacity: int,
    popularity: dict[int, int] | None = None,
) -> dict[int, int]:
    """Greedy capacitated grouping. Returns item -> zone index."""
    catalogue = sorted({int(item) for item in catalogue})
    if zone_capacity < 1:
        raise ValueError(f"zone_capacity must be at least 1; got {zone_capacity}.")
    if not catalogue:
        return {}

    neighbours: dict[int, dict[int, float]] = defaultdict(dict)
    for (left, right), value in affinity.items():
        if left in set(catalogue) and right in set(catalogue):
            neighbours[left][right] = value
            neighbours[right][left] = value

    total_affinity = {item: sum(neighbours[item].values()) for item in catalogue}
    popularity = popularity or {}

    unplaced = set(catalogue)
    assignment: dict[int, int] = {}
    zone = 0

    while unplaced:
        # Seed with the most connected unplaced product; ties broken by
        # popularity and then by id, so the result is reproducible.
        seed = max(
            unplaced,
            key=lambda item: (total_affinity.get(item, 0.0), popularity.get(item, 0), -item),
        )
        members = [seed]
        unplaced.discard(seed)

        while len(members) < zone_capacity and unplaced:
            best, best_score = None, 0.0
            for candidate in unplaced:
                score = sum(neighbours[candidate].get(member, 0.0) for member in members)
                if score > best_score:
                    best, best_score = candidate, score

            if best is None:
                # Nothing left has any affinity with this zone. The zone still
                # has physical capacity, so it is filled by popularity rather
                # than closed.
                #
                # Closing it instead is a real and costly mistake: on a
                # long-tailed catalogue only a small minority of products
                # appear in any rule, so every unconnected product would start
                # and close a zone of its own. A layout of hundreds of
                # one-product zones needs more visits per order than a random
                # layout that at least packs its shelves, and the comparison
                # then measures the bug rather than the rules.
                best = max(
                    unplaced, key=lambda item: (popularity.get(item, 0), -item)
                )
            members.append(best)
            unplaced.discard(best)

        for item in members:
            assignment[item] = zone
        zone += 1

    return assignment


def picking_effort(
    transactions: list[frozenset[int]], assignment: dict[int, int]
) -> dict[str, Any]:
    """Distinct zones a picker must visit per order.

    The measurable stand-in for Jirapatsil & Phumchusri's walking distance.
    Orders whose items are all unassigned are skipped and counted, rather than
    scored as zero zones, which would flatter any layout.
    """
    visited: list[int] = []
    skipped = 0
    for basket in transactions:
        zones = {assignment[item] for item in basket if item in assignment}
        if not zones:
            skipped += 1
            continue
        visited.append(len(zones))

    if not visited:
        return {"available": False, "reason": "No orders could be scored."}

    values = np.array(visited, dtype=float)
    return {
        "available": True,
        "orders_scored": int(values.size),
        "orders_skipped": skipped,
        "mean_zones_per_order": float(values.mean()),
        "median_zones_per_order": float(np.median(values)),
        "max_zones_per_order": int(values.max()),
        "single_zone_orders": int((values == 1).sum()),
        "single_zone_share": float((values == 1).mean()),
    }


def evaluate_layout(
    transactions: list[frozenset[int]],
    catalogue: Iterable[int],
    affinity: dict[tuple[int, int], float],
    *,
    zone_capacity: int = 20,
    popularity: dict[int, int] | None = None,
    random_seeds: int = 5,
    seed: int = 20260101,
) -> dict[str, Any]:
    """The rule-driven layout against two baselines. The RQ3 "so what".

    A reduction against random says the rules carry information a shuffle does
    not. A reduction against popularity order says they carry information a
    warehouse manager would not already have, which is the harder and more
    useful claim.
    """
    catalogue = sorted({int(item) for item in catalogue})
    if not catalogue:
        return {"available": False, "reason": "Empty catalogue."}

    popularity = popularity or {}
    rule_based = assign_zones(
        catalogue, affinity, zone_capacity=zone_capacity, popularity=popularity
    )
    measured = picking_effort(transactions, rule_based)
    if not measured.get("available"):
        return {"available": False, "reason": measured.get("reason")}

    # Baseline 1: random assignment, averaged over seeds so one lucky shuffle
    # cannot decide the result.
    rng = np.random.default_rng(seed)
    random_means = []
    for _ in range(max(1, random_seeds)):
        shuffled = list(catalogue)
        rng.shuffle(shuffled)
        layout = {item: index // zone_capacity for index, item in enumerate(shuffled)}
        outcome = picking_effort(transactions, layout)
        if outcome.get("available"):
            random_means.append(outcome["mean_zones_per_order"])
    random_mean = float(np.mean(random_means)) if random_means else None

    # Baseline 2: popularity order - what a warehouse drifts into without
    # analysis, with fast movers grouped near the front.
    by_popularity = sorted(catalogue, key=lambda item: -popularity.get(item, 0))
    popularity_layout = {
        item: index // zone_capacity for index, item in enumerate(by_popularity)
    }
    popularity_measured = picking_effort(transactions, popularity_layout)

    def reduction(baseline: float | None) -> float | None:
        if not baseline:
            return None
        return float((baseline - measured["mean_zones_per_order"]) / baseline)

    against_random = reduction(random_mean)
    against_popularity = reduction(
        popularity_measured.get("mean_zones_per_order")
        if popularity_measured.get("available") else None
    )

    return {
        "available": True,
        "zone_capacity": zone_capacity,
        "zones_used": len(set(rule_based.values())),
        "rule_based": measured,
        "random_baseline_mean": random_mean,
        "random_seeds": len(random_means),
        "popularity_baseline": popularity_measured,
        "reduction_vs_random": against_random,
        "reduction_vs_popularity": against_popularity,
        "verdict": _verdict(against_random, against_popularity, measured),
        "method_note": (
            "Jirapatsil & Phumchusri (2022) report a 54.4% reduction in average "
            "picking distance after rearranging a known warehouse. Online Retail "
            "II carries no layout, so distance in metres cannot be computed and "
            "is not reported. The quantity here is the number of distinct storage "
            "zones a picker must visit per historical order, which is what a "
            "layout is chosen to minimise and is derived entirely from the data. "
            "The percentages are against the stated baselines, not against a "
            "previous real layout, so they are not comparable to their 54.4%."
        ),
    }


def _verdict(
    against_random: float | None, against_popularity: float | None, measured: dict
) -> str:
    mean = measured["mean_zones_per_order"]
    parts = [
        f"A rule-driven grouping needs {mean:.2f} zone visits per order on average, "
        f"and {measured['single_zone_share']:.1%} of orders can be filled from a "
        f"single zone."
    ]
    if against_random is not None:
        parts.append(
            f"That is {against_random:.1%} fewer than random assignment"
            if against_random > 0 else
            f"That is {abs(against_random):.1%} MORE than random assignment, which "
            f"means the grouping is not working and should not be reported as an "
            f"improvement"
        )
    if against_popularity is not None:
        parts.append(
            f"and {against_popularity:.1%} fewer than grouping by popularity alone"
            if against_popularity > 0 else
            f"but no better than grouping by popularity alone "
            f"({abs(against_popularity):.1%} worse), so the rules add nothing a "
            f"sales ranking would not have given"
        )
    return " ".join(parts) + "."
