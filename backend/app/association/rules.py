"""From frequent itemsets to rules, and the measures that say which ones mean anything.

**Confidence alone is a trap, and it is the trap this module exists to avoid.**
If 60% of all baskets contain a carrier bag, then "cake stand -> carrier bag"
has confidence around 0.60 for every product on the shelf. It will look like
the strongest rule in the dataset and it says nothing: the bag is popular, not
associated. Lift is confidence divided by the consequent's own support, so the
bag rule lands at 1.0 - exactly what independence predicts - and a real pairing
lands above it.

So the measures are reported together and the verdict is never confidence:

- **support** - share of baskets containing the whole rule. How often it applies.
- **confidence** - P(consequent | antecedent). How reliable it is when it does.
- **lift** - confidence / P(consequent). Above 1 is association, 1 is
  independence, below 1 is *dis*association. Symmetric, so it cannot tell you
  the direction of anything.

The first three are Equations (1) to (5) of Jirapatsil & Phumchusri (2022),
whose §3.1 also states the decision rule used by `is_association` below: "The
basic rule of the Lift value is needed to be close to 1, which means the rule
is wholly independent. According to Lift value >1, the value is indicated as a
useful rule pattern and strongly associated rule between one product to another
product."

Four further measures come from Ni et al. (2020) and are computed in
`measures.py`: all_confidence, IS (cosine), normalised lift and cross-support.
They exist because lift has a defect that matters badly in retail - it grows
with the number of baskets containing neither product, which in a catalogue of
thousands is nearly every basket. See that module for the quotation and the
arithmetic.

The remaining three are standard in the data mining literature but do **not**
appear in the four papers supplied for this project. Present them as your own
additions, or find and read a source before citing one:
- **leverage** - P(A and C) - P(A)P(C). The same comparison in absolute terms,
  which lift's ratio hides: a lift of 8 on three baskets is noise.
- **conviction** - how much more often the rule would be wrong if A and C were
  independent. Unlike lift it is asymmetric, so it does distinguish A -> C from
  C -> A.
- **Zhang's metric** - bounded in [-1, 1] and defined for dissociation as well,
  which lift handles poorly at the low end.

**And then a significance test, because mining generates rules in bulk.** Ten
thousand candidate rules tested at p < 0.05 produce five hundred "significant"
rules from pure noise. This is the same multiple-comparisons problem the
forecasting chapter met with Friedman and a Bonferroni correction, and it is
larger here: there are thousands of rules, not eight models. Each rule gets a
one-sided Fisher exact test on its 2x2 table, and the p-values are corrected
with Benjamini-Hochberg.

Benjamini-Hochberg rather than Bonferroni, deliberately. Bonferroni controls
the chance of *any* false positive, which is the right target when a single
wrong claim damages the conclusion - as in the model comparison. Here the
output is a ranked list a manager will act on a few of, so the right target is
the share of false discoveries among those reported, which is what BH controls,
and it does so with far more power on thousands of tests. Say which you used
and why; a reader who knows the difference will ask.

**On whether significance testing of rules has precedent in the supplied
literature: partly.** Ni et al. (2020) §2.4 describe the dependence rules of
Silverstein et al. (1998), in which "the dependence of a itemset is measured by
chi-square test... if the p value corresponding to the chi-square value of the
itemset is low, then the hypothesis that the items in itemset are independent
is rejected." That is the same hypothesis this module tests, by the exact
(Fisher) version of the same test on the same 2x2 table. The *correction* for
multiple testing is not from any of the four papers and remains your own
methodological choice. Cite Ni et al. for the test, not for the correction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any, Iterable

import numpy as np

from app.association.itemsets import FrequentItemsets
from app.association.measures import dependence

# Conventional readings. Descriptive bands for wording, not decision thresholds.
STRONG_LIFT = 3.0
MEANINGFUL_LIFT = 1.0


@dataclass(frozen=True)
class Rule:
    """One rule and everything needed to judge it."""

    antecedent: frozenset[int]
    consequent: frozenset[int]
    support: float
    support_count: int
    antecedent_support: float
    consequent_support: float
    confidence: float
    lift: float
    leverage: float
    conviction: float
    zhang: float
    p_value: float | None = None
    q_value: float | None = None          # Benjamini-Hochberg adjusted
    significant: bool | None = None

    # Ni et al. (2020), Equations 3, 4, 8 and 10. See measures.py. These are
    # bounded in [0, 1] and, unlike lift, do not grow with the number of
    # baskets containing neither side of the rule.
    all_confidence: float = 0.0
    cosine: float = 0.0                   # their IS
    normalised_lift: float = 0.0          # their Nlift
    cross_support: float = 0.0

    @property
    def key(self) -> tuple[frozenset[int], frozenset[int]]:
        return (self.antecedent, self.consequent)

    @property
    def is_association(self) -> bool:
        """Does this rule describe a real co-occurrence?

        Lift must exceed 1 - a confident rule at lift 1.0 is a popular item,
        not an association - and if a test was run it must also have survived
        the correction. Confidence appears nowhere in this decision, which is
        the whole point.
        """
        if not np.isfinite(self.lift) or self.lift <= MEANINGFUL_LIFT:
            return False
        return self.significant is not False

    def as_dict(self, labels=None) -> dict[str, Any]:
        def render(items: frozenset[int]) -> list[str]:
            return (
                [labels(i) for i in sorted(items)]
                if labels else [str(i) for i in sorted(items)]
            )

        return {
            "antecedent": render(self.antecedent),
            "consequent": render(self.consequent),
            "antecedent_ids": sorted(self.antecedent),
            "consequent_ids": sorted(self.consequent),
            "support": self.support,
            "support_count": self.support_count,
            "confidence": self.confidence,
            "lift": self.lift,
            "leverage": self.leverage,
            "conviction": self.conviction if np.isfinite(self.conviction) else None,
            "zhang": self.zhang,
            "all_confidence": self.all_confidence,
            "cosine_is": self.cosine,
            "normalised_lift": self.normalised_lift,
            "cross_support": self.cross_support,
            "p_value": self.p_value,
            "q_value": self.q_value,
            "significant": self.significant,
            "is_association": self.is_association,
        }


def _zhang(support: float, antecedent: float, consequent: float, confidence: float) -> float:
    """Zhang's metric: bounded, and meaningful for dissociation as well as association."""
    numerator = confidence - consequent
    denominator = max(confidence * (1 - consequent), consequent * (1 - confidence))
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def generate_rules(
    itemsets: FrequentItemsets,
    *,
    min_confidence: float = 0.2,
    min_lift: float = 1.0,
    min_cross_support: float = 0.0,
    max_consequent_length: int = 1,
    test: bool = True,
    fdr_alpha: float = 0.05,
) -> list[Rule]:
    """Every rule from the frequent itemsets that clears the declared thresholds.

    **`max_consequent_length` defaults to 1** - single-item consequents only.
    Two reasons, both practical. A recommendation widget and a shelf plan can
    act on "also buy X"; neither can act on "also buy X and Y together". And
    allowing multi-item consequents multiplies the rule count by roughly 2^k
    per itemset, which multiplies the multiple-testing burden for output nobody
    uses.

    `min_lift` defaults to 1.0, which admits rules at exactly independence so
    they appear in the output and can be seen to be uninteresting. Raise it to
    filter; do not raise it before showing a reader that the filter was needed.
    """
    if not 0 <= min_confidence <= 1:
        raise ValueError(f"min_confidence must be in [0, 1]; got {min_confidence}.")

    n = itemsets.n_transactions
    if not n:
        return []

    rules: list[Rule] = []
    for length, level in sorted(itemsets.by_length.items()):
        if length < 2:
            continue
        for itemset, count in level.items():
            support = count / n
            items = sorted(itemset)
            for size in range(1, min(max_consequent_length, length - 1) + 1):
                for consequent_items in combinations(items, size):
                    consequent = frozenset(consequent_items)
                    antecedent = itemset - consequent

                    antecedent_count = itemsets.count(antecedent)
                    consequent_count = itemsets.count(consequent)
                    if not antecedent_count or not consequent_count:
                        # Can only happen if an itemset was supplied without its
                        # subsets; closure guarantees it does not happen here.
                        continue

                    antecedent_support = antecedent_count / n
                    consequent_support = consequent_count / n
                    confidence = count / antecedent_count
                    if confidence < min_confidence:
                        continue

                    lift = confidence / consequent_support
                    if lift < min_lift:
                        continue

                    # Ni et al.'s measures, from the same counts - no extra
                    # pass over the baskets. all_confidence uses Lee et al.'s
                    # itemset form, so it needs the most common single item in
                    # the rule rather than the larger of the two sides.
                    largest_item = max(
                        itemsets.count({item}) for item in itemset
                    )
                    measures = dependence(
                        both=count,
                        antecedent=antecedent_count,
                        consequent=consequent_count,
                        n_transactions=n,
                        largest_item=largest_item,
                    )
                    if measures.cross_support < min_cross_support:
                        continue

                    leverage = support - antecedent_support * consequent_support
                    conviction = (
                        float("inf") if confidence >= 1.0
                        else (1 - consequent_support) / (1 - confidence)
                    )

                    rules.append(
                        Rule(
                            all_confidence=measures.all_confidence,
                            cosine=measures.cosine,
                            normalised_lift=measures.normalised_lift,
                            cross_support=measures.cross_support,
                            antecedent=antecedent,
                            consequent=consequent,
                            support=support,
                            support_count=count,
                            antecedent_support=antecedent_support,
                            consequent_support=consequent_support,
                            confidence=confidence,
                            lift=lift,
                            leverage=leverage,
                            conviction=conviction,
                            zhang=_zhang(
                                support, antecedent_support, consequent_support, confidence
                            ),
                        )
                    )

    if test and rules:
        rules = test_rules(rules, n_transactions=n, alpha=fdr_alpha)

    rules.sort(key=lambda rule: (-rule.lift, -rule.support))
    return rules


def test_rules(rules: list[Rule], *, n_transactions: int, alpha: float = 0.05) -> list[Rule]:
    """One-sided Fisher exact test per rule, then Benjamini-Hochberg across all of them.

    The 2x2 table is baskets with and without the antecedent against baskets
    with and without the consequent. Fisher rather than chi-square because many
    rules sit on small counts, which is exactly where chi-square's
    approximation fails, and the cost of being exact is negligible at this
    scale.

    One-sided ("greater") because the question is whether the consequent
    appears *more* often with the antecedent than without. A two-sided test
    would also flag dissociation, which is interesting but is a different
    finding and should not be mixed into the same list.
    """
    from scipy.stats import fisher_exact

    n = n_transactions
    p_values: list[float] = []
    for rule in rules:
        both = rule.support_count
        antecedent_only = int(round(rule.antecedent_support * n)) - both
        consequent_only = int(round(rule.consequent_support * n)) - both
        neither = n - both - antecedent_only - consequent_only
        table = [[both, max(0, antecedent_only)], [max(0, consequent_only), max(0, neither)]]
        _, p = fisher_exact(table, alternative="greater")
        p_values.append(float(p))

    q_values = benjamini_hochberg(p_values)

    # `replace` rather than naming every field: an earlier version listed the
    # fields explicitly, and adding a measure to Rule would then have silently
    # dropped it here on every tested rule.
    return [
        replace(rule, p_value=p, q_value=q, significant=bool(q <= alpha))
        for rule, p, q in zip(rules, p_values, q_values, strict=True)
    ]


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Adjusted p-values controlling the false discovery rate.

    Each p is scaled by m/rank, then made monotone from the largest downwards
    so a rule can never be reported as more significant than a weaker-ranked
    one. Returned in the input order.
    """
    m = len(p_values)
    if m == 0:
        return []

    order = np.argsort(np.asarray(p_values, dtype=float), kind="stable")
    ranked = np.asarray(p_values, dtype=float)[order]
    scaled = ranked * m / np.arange(1, m + 1)

    # Monotone from the top: an adjusted value is never larger than the one
    # above it, which is what makes the procedure a valid step-up test.
    adjusted = np.minimum.accumulate(scaled[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)

    output = np.empty(m, dtype=float)
    output[order] = adjusted
    return [float(v) for v in output]


def summarise(rules: list[Rule], *, alpha: float = 0.05) -> dict[str, Any]:
    """What the rule set as a whole looks like. The honest headline, not the best rule."""
    if not rules:
        return {
            "available": False,
            "reason": "No rules cleared the declared thresholds.",
            "guidance": (
                "That is a result, not a failure. It means no product pairing in "
                "this data is both common enough and reliable enough at the "
                "thresholds declared before the run. Lowering them afterwards to "
                "produce rules would be choosing the answer."
            ),
        }

    lifts = np.array([r.lift for r in rules if np.isfinite(r.lift)])
    associations = [r for r in rules if r.is_association]
    tested = [r for r in rules if r.p_value is not None]
    significant = [r for r in tested if r.significant]
    lost = sum(1 for r in tested if r.p_value <= alpha and not r.significant)

    return {
        "available": True,
        "rules": len(rules),
        "associations": len(associations),
        "tested": len(tested),
        "significant": len(significant),
        "lost_to_correction": lost,
        "median_lift": float(np.median(lifts)) if lifts.size else None,
        "max_lift": float(lifts.max()) if lifts.size else None,
        "median_support": float(np.median([r.support for r in rules])),
        "correction": f"Benjamini-Hochberg at alpha = {alpha}",
        "note": (
            f"{len(significant):,} of {len(tested):,} rules survived the "
            f"false-discovery-rate correction. "
            + (
                f"{lost:,} were significant on their raw p-value and were "
                f"rejected by it - which is what testing thousands of rules at "
                f"once does, and why the correction is not optional."
                if lost else
                "The correction rejected nothing: every rule significant at the "
                "raw threshold stayed significant after it. That means these "
                "associations sit far from the threshold, not that the "
                "correction was unnecessary - it had to be applied to know."
            )
        ),
    }


def top_rules(rules: Iterable[Rule], *, by: str = "lift", n: int = 20) -> list[Rule]:
    """The strongest rules by one measure, associations only.

    Ranking the full list would put independence-level rules in a table headed
    "strongest associations", so the filter comes first.
    """
    allowed = {
        "lift", "confidence", "support", "leverage", "conviction", "zhang",
        "all_confidence", "cosine", "normalised_lift", "cross_support",
    }
    if by not in allowed:
        raise ValueError(f"Cannot rank by {by!r}. Available: {', '.join(sorted(allowed))}.")
    pool = [r for r in rules if r.is_association]
    return sorted(
        pool,
        key=lambda rule: (
            getattr(rule, by) if np.isfinite(getattr(rule, by)) else float("-inf")
        ),
        reverse=True,
    )[:n]
