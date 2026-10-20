"""Turning invoice lines into the baskets rules are mined from.

Association rule mining looks deceptively like a one-liner, and almost all of
the damage is done before any mining starts. Four decisions here change every
number downstream, none of them raises an error, and every one of them is a
defensible choice in some other project:

1. **What counts as one basket.** An invoice. Not a customer, not a day.
2. **Whether quantity matters.** It does not - a basket is a *set*. Buying six
   of an item is the same co-occurrence evidence as buying one.
3. **Which lines are not products.** Postage, bank charges and manual
   adjustments co-occur with everything, so left in they generate the highest
   lift rules in the dataset and all of them are meaningless.
4. **What to do about enormous baskets.** One invoice with 500 distinct items
   contributes 124,750 pairs. A handful of wholesale orders can decide the
   entire result.

Every one is recorded in `notes` and travels into the results file, because a
reader cannot check an assumption they cannot see.

**The non-product list is imported, never restated.** An earlier reconciliation
script in this project defined its own copy of that list, drifted from the
pipeline's twelve codes to eight, and disagreed with the database by 85
invoices. A script that restates a rule is worse than no script at all: it
produces a confident number that is wrong. So the list comes from
`preprocessing.field_guide`, the one place it is defined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.preprocessing.field_guide import NON_PRODUCT_CODES

# A basket this large is almost certainly a wholesale order or a data artefact.
# Not a hard rule - it is the default for a *reported*, overridable cap.
LARGE_BASKET = 200


@dataclass(frozen=True)
class BasketSet:
    """Baskets encoded for mining, with every decision that shaped them.

    Items are integers, not strings. Mining intersects item sets millions of
    times and integer ids make that a bitmap operation; the labels come back
    at the reporting step, where there are a few dozen rules rather than a few
    million candidates.
    """

    transactions: list[frozenset[int]]
    labels: dict[int, str]                     # item id -> product code
    names: dict[int, str]                      # item id -> readable name
    invoice_ids: list[str]
    dates: list[pd.Timestamp]
    notes: list[str] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)

    @property
    def n_transactions(self) -> int:
        return len(self.transactions)

    @property
    def n_items(self) -> int:
        return len(self.labels)

    def label(self, item: int) -> str:
        return self.names.get(item) or self.labels.get(item, str(item))

    def describe(self, items) -> list[str]:
        return [self.label(int(i)) for i in sorted(items)]

    def subset(self, mask: list[bool]) -> BasketSet:
        """The same vocabulary, fewer baskets.

        The vocabulary is deliberately *not* rebuilt. Hold-out validation
        compares rules across two basket sets, and that comparison is only
        meaningful if item 42 means the same product in both.
        """
        if len(mask) != len(self.transactions):
            raise ValueError(
                f"{len(mask)} mask entries for {len(self.transactions)} baskets."
            )
        keep = [i for i, flag in enumerate(mask) if flag]
        return BasketSet(
            transactions=[self.transactions[i] for i in keep],
            labels=self.labels,
            names=self.names,
            invoice_ids=[self.invoice_ids[i] for i in keep],
            dates=[self.dates[i] for i in keep],
            notes=[*self.notes, f"Subset to {len(keep):,} of {len(mask):,} baskets."],
            excluded=self.excluded,
        )

    def size_profile(self) -> dict[str, Any]:
        sizes = pd.Series([len(t) for t in self.transactions], dtype="int64")
        if sizes.empty:
            return {"available": False, "reason": "No baskets."}
        return {
            "available": True,
            "baskets": int(len(sizes)),
            "items": self.n_items,
            "mean_size": float(sizes.mean()),
            "median_size": float(sizes.median()),
            "max_size": int(sizes.max()),
            "singletons": int((sizes <= 1).sum()),
            "singleton_share": float((sizes <= 1).mean()),
            "large_baskets": int((sizes >= LARGE_BASKET).sum()),
            "pairs_implied": int((sizes * (sizes - 1) // 2).sum()),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "baskets": self.n_transactions,
            "items": self.n_items,
            "date_min": str(min(self.dates)) if self.dates else None,
            "date_max": str(max(self.dates)) if self.dates else None,
            "excluded": self.excluded,
            "notes": self.notes,
            "size_profile": self.size_profile(),
        }


def build_baskets(
    lines: pd.DataFrame,
    *,
    item_key: str = "product_code",
    drop_returns: bool = True,
    exclude_non_product: bool = True,
    non_product_codes: list[str] | None = None,
    min_basket_size: int = 1,
    max_basket_size: int | None = None,
) -> BasketSet:
    """One basket per invoice, as a set of item ids.

    `lines` needs `invoice_id` and `product_code`; `product_name`,
    `occurred_at` and `is_return` are used when present.

    **On `min_basket_size`, where this code disagrees with a supplied paper.**
    Qiu, Ning, Zhang & Yang (2023) propose exactly this as an improvement to
    Apriori - their "deletion module" - on the grounds that single-item records
    "hold no significance for the algorithm and the subsequent generation of
    results, and they may potentially have a detrimental effect on the
    association rules."

    The default here is 1, keeping them, which is the opposite choice. The
    reason is visible in their own Table 2: on their worked example the rule
    d -> b has confidence 0.67 under standard Apriori and 1.00 after the
    deletion, and their Tables 10 and 11 show the same threshold yielding 3
    rules before and 8 after. The pairs did not occur more often; the
    denominator shrank. Support is defined as a share of all baskets, so
    removing a quarter of them raises every support and confidence figure
    without any new evidence arriving.

    Their framing of this as discovering "a larger set of association rules,
    providing users with more options" is the part worth examining in the
    chapter rather than repeating. `compare_singleton_policies` runs both and
    reports the difference, so the argument can be settled on your data instead
    of asserted either way.
    """
    required = {"invoice_id", item_key}
    missing = required - set(lines.columns)
    if missing:
        raise ValueError(
            f"Basket construction needs {sorted(required)}; missing {sorted(missing)}. "
            f"The field guide marks invoice_id and product_code as the two "
            f"requirements for the association_rules capability."
        )

    notes: list[str] = []
    excluded: dict[str, int] = {}
    frame = lines.copy()
    start = len(frame)

    frame = frame[frame["invoice_id"].notna() & frame[item_key].notna()]
    if (dropped := start - len(frame)) > 0:
        excluded["missing_invoice_or_item"] = dropped

    if drop_returns and "is_return" in frame.columns:
        before = len(frame)
        frame = frame[~frame["is_return"].astype("boolean").fillna(False)]
        excluded["return_lines"] = before - len(frame)
        notes.append(
            "Return lines were excluded. A return is the reversal of a purchase "
            "decision, not a second one, and a credit note listing six items is "
            "not evidence that those six go together."
        )
    elif drop_returns:
        notes.append(
            "drop_returns was requested but the data has no is_return column, "
            "so returns - if any - are still in the baskets."
        )

    codes = [str(c).strip().upper() for c in (non_product_codes or NON_PRODUCT_CODES)]
    if exclude_non_product:
        before = len(frame)
        normalised = frame[item_key].astype(str).str.strip().str.upper()
        frame = frame[~normalised.isin(codes)]
        excluded["non_product_lines"] = before - len(frame)
        notes.append(
            f"Excluded {len(codes)} non-product codes imported from "
            f"preprocessing.field_guide. Postage and bank charges co-occur with "
            f"almost everything, so left in they produce the highest-lift rules "
            f"in the dataset and every one of them is an artefact of billing."
        )

    if frame.empty:
        return BasketSet([], {}, {}, [], [], [*notes, "No usable lines."], excluded)

    frame[item_key] = frame[item_key].astype(str).str.strip().str.upper()

    # Item vocabulary. Sorted so two runs on the same data give the same ids,
    # which matters when a results file is diffed against an earlier one.
    vocabulary = sorted(frame[item_key].unique())
    ids = {code: index for index, code in enumerate(vocabulary)}
    labels = {index: code for code, index in ids.items()}

    names: dict[int, str] = {}
    if "product_name" in frame.columns:
        # One product code can carry several descriptions - the Product model
        # counts them in description_variants. The most frequent one is used,
        # and the code remains the identity.
        for code, group in frame.groupby(item_key, observed=True):
            common = group["product_name"].dropna()
            if not common.empty:
                names[ids[code]] = str(common.mode().iloc[0])

    has_date = "occurred_at" in frame.columns
    grouped = frame.groupby("invoice_id", observed=True)

    transactions: list[frozenset[int]] = []
    invoice_ids: list[str] = []
    dates: list[pd.Timestamp] = []
    too_small = 0
    truncated = 0

    for invoice, group in grouped:
        items = frozenset(ids[code] for code in group[item_key].unique())
        if len(items) < min_basket_size:
            too_small += 1
            continue
        if max_basket_size is not None and len(items) > max_basket_size:
            truncated += 1
            continue
        transactions.append(items)
        invoice_ids.append(str(invoice))
        dates.append(
            pd.Timestamp(group["occurred_at"].min()) if has_date else pd.NaT
        )

    if too_small:
        excluded["baskets_below_min_size"] = too_small
    if min_basket_size > 1:
        notes.append(
            f"min_basket_size={min_basket_size} removed {too_small:,} baskets. "
            f"Support is the share of all baskets, so this raises the support of "
            f"every itemset without any itemset occurring more often. It is a "
            f"deliberate choice and the reported support figures are relative to "
            f"the reduced denominator."
        )
    else:
        notes.append(
            "Single-item baskets were kept. They cannot contribute to a rule, "
            "but they belong in the denominator: support is the share of all "
            "baskets, and dropping them would inflate every support figure."
        )

    if truncated:
        excluded["baskets_above_max_size"] = truncated
        notes.append(
            f"max_basket_size={max_basket_size} removed {truncated:,} baskets. A "
            f"basket of n items contributes n(n-1)/2 pairs, so a few wholesale "
            f"orders can carry more pair evidence than thousands of ordinary "
            f"ones. Removing them is a decision about which population the rules "
            f"describe, not a cleaning step."
        )

    # Items that survived to no basket at all would waste a mining level.
    present = set().union(*transactions) if transactions else set()
    labels = {i: c for i, c in labels.items() if i in present}
    names = {i: n for i, n in names.items() if i in present}

    return BasketSet(
        transactions=transactions,
        labels=labels,
        names=names,
        invoice_ids=invoice_ids,
        dates=dates,
        notes=notes,
        excluded=excluded,
    )


def compare_singleton_policies(
    baskets: BasketSet, *, min_support: float, min_confidence: float, max_length: int = 2
) -> dict[str, Any]:
    """Replicate Qiu et al. (2023) §3.1-3.2 on this data and report the effect.

    Their deletion module removes single-item transactions before mining. This
    mines twice at identical thresholds - once with those baskets, once without
    - and reports what changed. Their claim is that the second run finds more
    rules; the question for the chapter is whether those rules are discoveries
    or the same evidence measured against a smaller denominator.

    The test to apply to the output: if a rule's *support count* is unchanged
    while its support and confidence rise, nothing was discovered.
    """
    from app.association.itemsets import frequent_itemsets
    from app.association.rules import generate_rules

    kept = baskets
    without = baskets.subset([len(t) > 1 for t in baskets.transactions])
    removed = kept.n_transactions - without.n_transactions

    if without.n_transactions == 0:
        return {"available": False, "reason": "Every basket holds a single item."}

    outcomes = {}
    for label, source in (("with_singletons", kept), ("without_singletons", without)):
        itemsets = frequent_itemsets(
            source.transactions, min_support=min_support, max_length=max_length
        )
        # min_lift=0.0 deliberately. This comparison is about what the
        # denominator does to support and confidence, and a lift filter would
        # discard exactly the rules whose support inflates - including
        # d -> b from Qiu et al.'s own Table 2, whose lift is 0.89.
        rules = generate_rules(
            itemsets, min_confidence=min_confidence, min_lift=0.0, test=False
        )
        outcomes[label] = {
            "baskets": source.n_transactions,
            "frequent_itemsets": itemsets.total,
            "rules": len(rules),
            "by_rule": {
                (tuple(sorted(r.antecedent)), tuple(sorted(r.consequent))): r
                for r in rules
            },
        }

    shared = set(outcomes["with_singletons"]["by_rule"]) & set(
        outcomes["without_singletons"]["by_rule"]
    )
    inflated = 0
    examples = []
    for key in sorted(shared):
        before = outcomes["with_singletons"]["by_rule"][key]
        after = outcomes["without_singletons"]["by_rule"][key]
        if after.support_count == before.support_count and after.support > before.support:
            inflated += 1
            if len(examples) < 5:
                examples.append({
                    "antecedent": list(key[0]),
                    "consequent": list(key[1]),
                    "support_count": before.support_count,
                    "support_with": before.support,
                    "support_without": after.support,
                    "confidence_with": before.confidence,
                    "confidence_without": after.confidence,
                })

    gained = len(set(outcomes["without_singletons"]["by_rule"]) - shared)
    for outcome in outcomes.values():
        outcome.pop("by_rule")

    return {
        "available": True,
        "source": (
            "Qiu, Ning, Zhang & Yang (2023), ICMLCA 2023, sections 3.1-3.2 and "
            "Tables 2, 10 and 11."
        ),
        "singletons_removed": removed,
        "singleton_share": float(removed / kept.n_transactions) if kept.n_transactions else 0.0,
        **outcomes,
        "rules_gained": gained,
        "rules_inflated_without_new_evidence": inflated,
        "examples": examples,
        "verdict": (
            f"Removing {removed:,} single-item baskets "
            f"({removed / kept.n_transactions:.1%} of the data) changed the rule "
            f"count from {outcomes['with_singletons']['rules']:,} to "
            f"{outcomes['without_singletons']['rules']:,} at identical thresholds. "
            f"Of the rules present in both runs, {inflated:,} had an unchanged "
            f"support count but a higher support figure - the same baskets, "
            f"divided by a smaller denominator. Qiu et al. (2023) report the "
            f"larger rule count as an improvement; on this data it is at least "
            f"partly an artefact of the denominator, and the chapter should say "
            f"which it is rather than adopting their framing."
        ),
    }


def split_by_date(
    baskets: BasketSet, *, holdout_fraction: float = 0.25
) -> tuple[BasketSet, BasketSet]:
    """Earlier baskets to mine on, later baskets to test on.

    Split by time, never at random. A random split puts baskets from the same
    week on both sides, so a seasonal pairing - crackers with wrapping paper -
    is "confirmed" on the hold-out by baskets that are a few days from the ones
    that produced it. The question RQ3 asks is whether a rule mined in one
    period still holds in the next, and only a chronological split asks it.
    """
    if not 0 < holdout_fraction < 1:
        raise ValueError(f"holdout_fraction must be between 0 and 1, got {holdout_fraction}.")
    if baskets.n_transactions < 2:
        raise ValueError("Need at least two baskets to split.")
    if any(pd.isna(d) for d in baskets.dates):
        raise ValueError(
            "Some baskets have no date, so they cannot be split chronologically. "
            "Include occurred_at in the lines passed to build_baskets."
        )

    order = sorted(range(baskets.n_transactions), key=lambda i: baskets.dates[i])
    cut = int(round(len(order) * (1 - holdout_fraction)))
    cut = max(1, min(cut, len(order) - 1))

    boundary = baskets.dates[order[cut]]
    # Keep a whole day on one side. Splitting mid-day would put two baskets
    # from the same hour on opposite sides of the boundary.
    mine_mask = [date < boundary for date in baskets.dates]
    if not any(mine_mask) or all(mine_mask):
        mine_mask = [i in set(order[:cut]) for i in range(baskets.n_transactions)]

    hold_mask = [not flag for flag in mine_mask]
    return baskets.subset(mine_mask), baskets.subset(hold_mask)
