"""Dependence measures from Ni et al. (2020), and why lift alone is not enough.

Ni, Luo, Lu & Zhu, "Mining the Local Dependency Itemset in a Products Network",
*ACM Transactions on Management Information Systems* 11(1), Article 3, April
2020, §4, Equations (2)-(10).

Their §4.3 makes a criticism of lift that this project had not accounted for,
and it is worth quoting rather than paraphrasing:

    "Indicator lift has one major drawback. As can be seen from Equation (5),
    when f00 increases, the value of lift raises, too, where f00 is the number
    of transactions that do not contain x and y. Thus, the value of lift does
    not have a fixed upper bound."

In a retail dataset this matters more than it first appears. f00 - baskets
containing neither product - is almost every basket, because a catalogue has
thousands of products and a basket holds a handful. Two rare items bought
together twice can therefore post a spectacular lift, and the number is driven
by the size of the catalogue rather than by the strength of the relationship.
Lift is reported here because the retail literature reports it (Jirapatsil &
Phumchusri 2022, Equation 5), but it is reported alongside three measures that
do not share the defect.

The four measures, using the contingency table of their Table 2, where f11 is
baskets containing both items, f10 the antecedent only, f01 the consequent
only, and f00 neither:

**all_confidence** (their Equation 3, from Lee et al. 2003) - the support of
the itemset over the support of its most common member. Bounded [0, 1]. It
answers "in the worst case, how often does seeing one of these imply the
others?", so a pairing with one very popular member cannot score highly.

**IS** (their Equation 4, from Tan & Kumar 2000) - the cosine measure,
support(X) over the square root of the product of the parts' supports. Bounded
[0, 1]. Note the square root: this is cosine, not lift, and the two are easy to
confuse when reading the formula quickly.

**Nlift** (their Equation 8) - lift recomputed with supports taken over the
*universe* of the pair, meaning only the baskets containing at least one of the
items, instead of over all baskets. Their Equation 9 shows this is algebraically
equal to 1 - (f10 / (f11 + f10)) * (f01 / (f11 + f01)), which is bounded in
[0, 1] and contains no f00 term at all. It is the direct repair of the defect
quoted above.

**cross_support** (their Equation 10, from Tan et al. 2005) - the ratio of the
smaller support to the larger. Low values mean the two items sell at very
different rates, which is the situation where a high confidence is least
informative. Used as a filter rather than a score.

**A note on generality.** Ni et al. define these for a pair of items {x, y}.
Here they are computed for a rule's antecedent against its consequent, treating
each side as one block, which reduces to their definition exactly when both
sides are single items. `all_confidence` is given in Lee et al.'s itemset form
(support over the largest member's support), which is the usual generalisation.
Say in the chapter that the generalisation is yours; the paper does not make it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Ni et al. do not prescribe thresholds. These are descriptive bands used only
# for wording, and the wording says so.
STRONG_DEPENDENCE = 0.5


@dataclass(frozen=True)
class Dependence:
    """The four measures for one rule, computed from counts alone."""

    all_confidence: float
    cosine: float                 # their IS
    normalised_lift: float        # their Nlift
    cross_support: float

    def as_dict(self) -> dict[str, float]:
        return {
            "all_confidence": self.all_confidence,
            "cosine_is": self.cosine,
            "normalised_lift": self.normalised_lift,
            "cross_support": self.cross_support,
        }


def dependence(
    *,
    both: int,
    antecedent: int,
    consequent: int,
    n_transactions: int,
    largest_item: int | None = None,
) -> Dependence:
    """All four measures from the contingency counts.

    `both` is f11, `antecedent` is f11 + f10, `consequent` is f11 + f01.
    `largest_item` is the occurrence count of the most common single item in
    the rule, used for all_confidence in Lee et al.'s itemset form; without it
    the larger of the two sides is used, which is their pairwise definition.
    """
    if n_transactions <= 0:
        raise ValueError("n_transactions must be positive.")
    if both < 0 or antecedent < both or consequent < both:
        raise ValueError(
            f"Impossible counts: both={both}, antecedent={antecedent}, "
            f"consequent={consequent}. The joint count cannot exceed either "
            f"margin."
        )

    denominator = max(largest_item or 0, antecedent, consequent)
    all_confidence = both / denominator if denominator else 0.0

    cosine = (
        both / ((antecedent * consequent) ** 0.5)
        if antecedent and consequent else 0.0
    )

    # Equation (6): the universe is the baskets holding at least one side.
    # |A or C| = |A| + |C| - |A and C|, so no second pass over the data.
    universe = antecedent + consequent - both
    normalised_lift = (
        (universe * both) / (antecedent * consequent)
        if universe and antecedent and consequent else 0.0
    )

    cross_support = (
        min(antecedent, consequent) / max(antecedent, consequent)
        if max(antecedent, consequent) else 0.0
    )

    return Dependence(
        all_confidence=float(all_confidence),
        cosine=float(cosine),
        normalised_lift=float(normalised_lift),
        cross_support=float(cross_support),
    )


def lift_inflation(
    *, both: int, antecedent: int, consequent: int, n_transactions: int
) -> dict[str, Any]:
    """How much of a rule's lift comes from the catalogue rather than the pair.

    Ni et al.'s criticism, made measurable. Plain lift rises with f00 - the
    baskets containing neither item - which in retail is nearly every basket.
    Nlift removes that term. The ratio between them is how much of the headline
    number was an artefact of how large the catalogue is.

    This is the function to run when a rule posts a lift of 300 and someone
    asks whether that is real.
    """
    if not antecedent or not consequent or not both:
        return {"available": False, "reason": "A margin is zero; lift is undefined."}

    lift = (both * n_transactions) / (antecedent * consequent)
    measures = dependence(
        both=both, antecedent=antecedent, consequent=consequent,
        n_transactions=n_transactions,
    )
    f00 = n_transactions - (antecedent + consequent - both)

    return {
        "available": True,
        "lift": float(lift),
        "normalised_lift": measures.normalised_lift,
        "ratio": float(lift / measures.normalised_lift) if measures.normalised_lift else None,
        "f00": int(f00),
        "f00_share": float(f00 / n_transactions),
        "note": (
            f"Plain lift is {lift:.1f}; normalised lift is "
            f"{measures.normalised_lift:.3f}. {f00 / n_transactions:.1%} of baskets "
            f"contain neither item, and plain lift rises with that count while "
            f"normalised lift does not (Ni et al. 2020, Equations 5 and 9). The "
            f"larger the gap, the more of the headline number came from the size "
            f"of the catalogue rather than from the strength of the pairing."
        ),
    }


def describe(measures: Dependence) -> str:
    """One sentence a reader without the formulas can act on."""
    parts = []
    if measures.normalised_lift >= STRONG_DEPENDENCE:
        parts.append(
            f"a strong dependence that does not depend on catalogue size "
            f"(normalised lift {measures.normalised_lift:.2f})"
        )
    else:
        parts.append(
            f"a weak dependence once catalogue size is removed "
            f"(normalised lift {measures.normalised_lift:.2f})"
        )

    if measures.cross_support < 0.1:
        parts.append(
            f"between items selling at very different rates (cross-support "
            f"{measures.cross_support:.2f}), where confidence is least informative"
        )
    return "This rule describes " + ", ".join(parts) + "."
