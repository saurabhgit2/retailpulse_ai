"""Frequent itemsets: which combinations of products occur together often enough.

Apriori, implemented here rather than imported, for two reasons. The honest one
is that it adds no dependency to a project that already pins its stack
carefully. The better one is that the algorithm *is* the method section - a
reader who asks "how did you handle the combinatorial explosion" deserves a
real answer, and "mlxtend did it" is not one.

**The idea in one line.** A set of items cannot be frequent if any part of it
is rare. If {tea, mug} appears in only 3 baskets, then {tea, mug, spoon} cannot
appear in more than 3, so there is no point counting it. That is the downward
closure property, and it is the only thing standing between this and counting
2^n subsets. With 4,000 products, 2^n is a number with 1,200 digits.

**Why the counting is bitmaps.** Each item carries the set of baskets it
appears in - the "vertical" layout, as opposed to the usual list-of-baskets.
Support of {A, B} is then the size of the intersection of two sets, and if each
set is a packed bit array, that intersection is a single vectorised AND over a
few kilobytes. Counting a candidate costs the same whether it occurs 3 times or
30,000.

The code reports how many candidates it evaluated and how many closure pruned
away, because that ratio is the evidence that the pruning did its job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable

import numpy as np

# Number of set bits in each possible byte. Turns popcount into a table lookup
# over a few thousand bytes, which numpy does at memory speed.
_POPCOUNT = np.unpackbits(
    np.arange(256, dtype=np.uint8)[:, None], axis=1
).sum(axis=1).astype(np.int32)


class MiningError(ValueError):
    """The mining cannot proceed, with a reason a human can act on."""


@dataclass
class FrequentItemsets:
    """Every itemset at or above the support threshold, by length."""

    by_length: dict[int, dict[frozenset[int], int]]
    n_transactions: int
    min_support: float
    min_count: int
    max_length: int
    candidates_evaluated: int = 0
    pruned_by_closure: int = 0
    stopped_early: str | None = None
    notes: list[str] = field(default_factory=list)

    def count(self, itemset: Iterable[int]) -> int:
        key = frozenset(itemset)
        return self.by_length.get(len(key), {}).get(key, 0)

    def support(self, itemset: Iterable[int]) -> float:
        if not self.n_transactions:
            return 0.0
        return self.count(itemset) / self.n_transactions

    def all_itemsets(self) -> dict[frozenset[int], int]:
        merged: dict[frozenset[int], int] = {}
        for level in self.by_length.values():
            merged.update(level)
        return merged

    @property
    def total(self) -> int:
        return sum(len(level) for level in self.by_length.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_transactions": self.n_transactions,
            "min_support": self.min_support,
            "min_count": self.min_count,
            "max_length": self.max_length,
            "itemsets_by_length": {k: len(v) for k, v in sorted(self.by_length.items())},
            "itemsets_total": self.total,
            "candidates_evaluated": self.candidates_evaluated,
            "pruned_by_closure": self.pruned_by_closure,
            "pruning_note": (
                f"Downward closure removed {self.pruned_by_closure:,} candidates "
                f"before they were counted; {self.candidates_evaluated:,} were "
                f"counted. Without the pruning every candidate would have had to "
                f"be counted."
            ),
            "stopped_early": self.stopped_early,
            "notes": self.notes,
        }


def _bitmaps(transactions: list[frozenset[int]], items: Iterable[int]) -> dict[int, np.ndarray]:
    """One packed bit array per item: which baskets contain it."""
    n = len(transactions)
    columns: dict[int, np.ndarray] = {item: np.zeros(n, dtype=bool) for item in items}
    for row, basket in enumerate(transactions):
        for item in basket:
            column = columns.get(item)
            if column is not None:
                column[row] = True
    return {item: np.packbits(column) for item, column in columns.items()}


def _popcount(packed: np.ndarray) -> int:
    return int(_POPCOUNT[packed].sum())


def _generate_candidates(
    previous: list[tuple[int, ...]], length: int
) -> tuple[list[tuple[int, ...]], int]:
    """Join step plus closure prune.

    Two frequent (k-1)-itemsets sharing their first k-2 items join into one
    k-candidate. Sorting makes that a prefix comparison, so the join is linear
    in the number of frequent sets rather than quadratic over all pairs.

    The prune then checks every (k-1)-subset of the candidate. The join alone
    only guarantees that two of them are frequent; closure says *all* of them
    must be, and checking is a set lookup against work already done.
    """
    frequent = set(previous)
    candidates: list[tuple[int, ...]] = []
    pruned = 0

    groups: dict[tuple[int, ...], list[int]] = {}
    for itemset in previous:
        groups.setdefault(itemset[:-1], []).append(itemset[-1])

    for prefix, tails in groups.items():
        for left, right in combinations(sorted(tails), 2):
            candidate = (*prefix, left, right)
            if length > 2 and any(
                subset not in frequent
                for subset in combinations(candidate, length - 1)
            ):
                pruned += 1
                continue
            candidates.append(candidate)

    return candidates, pruned


def frequent_itemsets(
    transactions: list[frozenset[int]],
    *,
    min_support: float = 0.01,
    max_length: int = 3,
    max_candidates_per_level: int = 2_000_000,
) -> FrequentItemsets:
    """Apriori. Every itemset occurring in at least `min_support` of baskets.

    `max_length` is a real constraint, not a performance knob. Rules of length
    four and above are numerous, individually rare, and almost never actionable
    - a category manager cannot use "customers who bought these three things
    also bought a fourth". Three is the default because it allows a two-item
    antecedent, which is the longest condition a shelf layout or a
    recommendation widget can actually express.
    """
    if not 0 < min_support <= 1:
        raise MiningError(f"min_support must be in (0, 1]; got {min_support}.")
    if max_length < 1:
        raise MiningError(f"max_length must be at least 1; got {max_length}.")

    n = len(transactions)
    if n == 0:
        return FrequentItemsets({}, 0, min_support, 0, max_length,
                                notes=["No baskets to mine."])

    # Ceiling, so min_support is a floor and not "approximately a floor". With
    # 20,000 baskets at 1%, an itemset in exactly 200 is frequent and one in
    # 199 is not.
    min_count = int(np.ceil(min_support * n))
    min_count = max(min_count, 1)

    counts: dict[int, int] = {}
    for basket in transactions:
        for item in basket:
            counts[item] = counts.get(item, 0) + 1

    level_one = {
        frozenset((item,)): count for item, count in counts.items() if count >= min_count
    }
    result = FrequentItemsets(
        by_length={1: level_one},
        n_transactions=n,
        min_support=min_support,
        min_count=min_count,
        max_length=max_length,
        candidates_evaluated=len(counts),
    )
    if not level_one:
        result.notes.append(
            f"No single item reaches {min_support:.2%} of {n:,} baskets "
            f"({min_count:,} baskets), so nothing can be frequent. Lower "
            f"min_support or check the basket construction."
        )
        return result

    frequent_items = sorted(next(iter(s)) for s in level_one)
    bitmaps = _bitmaps(transactions, frequent_items)

    previous = [tuple(sorted(s)) for s in level_one]
    previous.sort()

    for length in range(2, max_length + 1):
        candidates, pruned = _generate_candidates(previous, length)
        result.pruned_by_closure += pruned

        if len(candidates) > max_candidates_per_level:
            result.stopped_early = (
                f"Level {length} generated {len(candidates):,} candidates, above "
                f"the {max_candidates_per_level:,} guard. Mining stopped at "
                f"length {length - 1}. Raise min_support rather than the guard: "
                f"a level this size means the threshold is admitting almost "
                f"every item, and the rules it produces will be individually "
                f"rare."
            )
            break

        level: dict[frozenset[int], int] = {}
        for candidate in candidates:
            packed = bitmaps[candidate[0]]
            for item in candidate[1:]:
                packed = np.bitwise_and(packed, bitmaps[item])
            count = _popcount(packed)
            result.candidates_evaluated += 1
            if count >= min_count:
                level[frozenset(candidate)] = count

        if not level:
            break
        result.by_length[length] = level
        previous = sorted(tuple(sorted(s)) for s in level)

    return result


def top_itemsets(
    itemsets: FrequentItemsets, *, length: int | None = None, n: int = 20
) -> list[dict[str, Any]]:
    """The most common itemsets, for the descriptive table before any rules."""
    pool = (
        itemsets.by_length.get(length, {})
        if length is not None
        else itemsets.all_itemsets()
    )
    ranked = sorted(pool.items(), key=lambda pair: pair[1], reverse=True)[:n]
    return [
        {
            "items": sorted(itemset),
            "length": len(itemset),
            "count": count,
            "support": count / itemsets.n_transactions if itemsets.n_transactions else 0.0,
        }
        for itemset, count in ranked
    ]
