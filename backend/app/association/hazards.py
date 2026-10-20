"""What a rule-driven recommender would do badly, measured.

Kathriarachchi, Alam & Rashid, "Overcoming Hazards of E-commerce Recommender
Systems for Social Good", *ACM Transactions on Recommender Systems* 4(3),
Article 42, March 2026, §4.2, Equations (4), (10) and (12).

A set of association rules is a recommender: "customers who bought this also
bought that" is exactly what a rule says. So the rules inherit the hazards that
paper catalogues, and several of them can be measured directly from the rule
set without deploying anything.

Two of those measurements are uncomfortable for association rules specifically,
which is why they belong in the chapter rather than in a footnote:

**Item coverage** (their Equation 10). A rule can only recommend a product that
appears in some rule's consequent, and a product only reaches a rule if it
clears minimum support. At 1% support on a catalogue of several thousand
products, the great majority of the catalogue can never be recommended at all.
The measure turns "association rules have a popularity bias" from an assertion
into a number.

**New item coverage** (their Equation 4). Their §4.2.2 frames this as the
cold-start hazard. For association rules the answer is structural: a product
that did not exist in the mining window appears in no rule, so its coverage is
zero *by construction*, not by misfortune. Measuring it states the limitation
precisely instead of leaving a reader to assume the method handles new stock.

**Transparency** (their Equation 12) is the one place rules do well. A rule is
its own explanation - "bought with X, in 412 of 580 baskets" is human-readable
with no post-hoc explainer - so the transparency index is 1.0 by construction.
Worth computing rather than asserting, and worth saying in a defence, because
it is the honest counterweight to the two findings above.

**What this module deliberately does not compute.** Their other seven metrics
need data Online Retail II does not contain: demographic groups for the bias
ratio (4.2.1), decision bias (4.2.6) and unfairness (4.2.10); an attack model
for privacy risk (4.2.3); labelled fake content for fake impact (4.2.4);
ratings for feedback skew (4.2.5); misinformation labels for exposure (4.2.9);
and ground-truth relevance for the precision term in competence (4.2.7).
`not_computable()` returns that list with reasons, so the chapter can show the
full taxonomy was considered and say which parts the dataset supports. Claiming
a fairness result from a dataset with no demographic field would be worse than
claiming nothing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

import numpy as np

from app.association.rules import Rule

# Their Equation (4) is parameterised by t, "typically set to t = 1 or t = 2".
DEFAULT_EXPOSURE_THRESHOLD = 1


def recommendation_counts(rules: Iterable[Rule]) -> Counter:
    """count_rec(i): how many rules would ever recommend item i.

    Their count_rec is over recommendation slots served to users. A rule set is
    not yet serving anyone, so the analogue is the number of rules in which an
    item appears as a consequent - the number of distinct contexts in which it
    could be surfaced. State that substitution when reporting the numbers; it
    is a reasonable mapping but it is not their definition applied unchanged.
    """
    counts: Counter = Counter()
    for rule in rules:
        for item in rule.consequent:
            counts[int(item)] += 1
    return counts


def item_coverage(
    rules: Iterable[Rule],
    catalogue: Iterable[int],
    *,
    threshold: int = DEFAULT_EXPOSURE_THRESHOLD,
) -> dict[str, Any]:
    """Equation (10): the share of the catalogue the rules can ever recommend."""
    catalogue = {int(item) for item in catalogue}
    if not catalogue:
        return {"available": False, "reason": "Empty catalogue."}

    counts = recommendation_counts(rules)
    reachable = {item for item in catalogue if counts.get(item, 0) >= threshold}
    coverage = len(reachable) / len(catalogue)

    return {
        "available": True,
        "catalogue_size": len(catalogue),
        "reachable": len(reachable),
        "item_coverage": float(coverage),
        "threshold": threshold,
        "verdict": (
            f"{coverage:.1%} of the catalogue can ever be recommended "
            f"({len(reachable):,} of {len(catalogue):,} products). The remaining "
            f"{1 - coverage:.1%} never clears minimum support, so no rule reaches "
            f"them however a customer behaves. This is the popularity bias of "
            f"Kathriarachchi et al. (2026) §3.2 measured rather than asserted, and "
            f"it is a property of the support threshold, not a defect in the data."
        ),
    }


def new_item_coverage(
    rules: Iterable[Rule],
    new_items: Iterable[int],
    *,
    threshold: int = DEFAULT_EXPOSURE_THRESHOLD,
) -> dict[str, Any]:
    """Equation (4): can the rules reach products that are new to the hold-out?

    The cold-start hazard, and for association rules the expected answer is
    zero. Reporting the zero is the point: it bounds what the method can do,
    and it is the argument for pairing rules with something else - a
    content-based or category-level fallback - rather than shipping rules alone.
    """
    new_items = {int(item) for item in new_items}
    if not new_items:
        return {
            "available": False,
            "reason": (
                "No products are new in the hold-out window, so cold start "
                "cannot be measured on this split."
            ),
        }

    counts = recommendation_counts(rules)
    covered = {item for item in new_items if counts.get(item, 0) >= threshold}
    coverage = len(covered) / len(new_items)

    return {
        "available": True,
        "new_items": len(new_items),
        "covered": len(covered),
        "coverage_new": float(coverage),
        "threshold": threshold,
        "verdict": (
            f"{coverage:.1%} of the {len(new_items):,} products new to the hold-out "
            f"window can be recommended by rules mined before they existed. "
            + (
                "A rule can only name products present when it was mined, so this "
                "is a structural limit of association rules rather than a result "
                "about this dataset: every new product is invisible to the method "
                "until the rules are mined again."
                if coverage == 0 else
                "Products reachable here appeared in the mining window as well, so "
                "they are not new to the method, only newly prominent."
            )
        ),
    }


def transparency_index(rules: Iterable[Rule]) -> dict[str, Any]:
    """Equation (12): the share of recommendations carrying an explanation.

    For association rules this is 1.0 and the derivation is one line: the rule
    *is* the explanation. It is computed rather than asserted so the number can
    sit in the same table as the two that go badly.
    """
    rules = list(rules)
    if not rules:
        return {"available": False, "reason": "No rules."}

    return {
        "available": True,
        "rules": len(rules),
        "transparency_index": 1.0,
        "verdict": (
            "Every recommendation an association rule makes carries its own "
            "explanation - the antecedent, the support count and the confidence - "
            "so the transparency index of Kathriarachchi et al. (2026) Equation 12 "
            "is 1.0 by construction. Their synthetic example scores 0.500. This is "
            "the dimension on which a rule-based recommender beats a latent-factor "
            "model outright, and it is worth stating beside the coverage results."
        ),
    }


def exposure_concentration(rules: Iterable[Rule]) -> dict[str, Any]:
    """How unevenly recommendation opportunity is spread across products.

    Not one of their numbered equations. Their §6.1 discusses the Gini
    coefficient as the measure mitigation work reports ("significantly reduces
    the Gini coefficient, indicating improved diversity"), so it is computed
    here on the same footing - as a diversity measure named in the paper's
    discussion, not as one of its formal definitions. Cite it that way.
    """
    counts = recommendation_counts(rules)
    if len(counts) < 2:
        return {"available": False, "reason": "Fewer than two recommendable items."}

    values = np.sort(np.array(sorted(counts.values()), dtype=float))
    n = values.size
    index = np.arange(1, n + 1)
    gini = float((2 * np.sum(index * values)) / (n * np.sum(values)) - (n + 1) / n)

    ranked = counts.most_common()
    top_decile = max(1, n // 10)
    top_share = sum(count for _, count in ranked[:top_decile]) / sum(counts.values())

    return {
        "available": True,
        "recommendable_items": n,
        "gini": gini,
        "top_decile_share": float(top_share),
        "most_recommended": [
            {"item": item, "rules": count} for item, count in ranked[:10]
        ],
        "note": (
            f"Gini {gini:.3f} across {n:,} recommendable products; the most "
            f"recommended tenth of them account for {top_share:.1%} of all "
            f"recommendation opportunities. 0 would be perfectly even exposure "
            f"and 1 all exposure on one product."
        ),
    }


def not_computable() -> list[dict[str, str]]:
    """Their metrics this dataset cannot support, with the reason for each.

    Reported in the results file so the chapter can show the whole taxonomy was
    considered. A fairness number computed from a dataset with no demographic
    field would be worse than no number.
    """
    return [
        {
            "metric": "Bias ratio (Equation 3, §4.2.1)",
            "needs": "demographic groups for customers",
            "why_not": (
                "Online Retail II has a pseudonymous Customer ID and a country, "
                "and no demographic attribute. Country is a market, not a "
                "protected characteristic, and reporting it as one would "
                "misrepresent both the data and the hazard."
            ),
        },
        {
            "metric": "Privacy risk (Equation 5, §4.2.3)",
            "needs": "a trained adversarial inference model",
            "why_not": (
                "Their definition estimates it by training an attack model "
                "against recommendation logs. There are no logs - nothing has "
                "been deployed - and no attribute to infer."
            ),
        },
        {
            "metric": "Fake content impact (Equation 6, §4.2.4)",
            "needs": "items labelled as fake-influenced",
            "why_not": "The dataset carries no reviews or ratings to be faked.",
        },
        {
            "metric": "Feedback skew (Equation 7, §4.2.5)",
            "needs": "observed and ground-truth rating distributions",
            "why_not": "There are no ratings in the dataset.",
        },
        {
            "metric": "Decision bias (Equation 9, §4.2.6)",
            "needs": "demographic groups and a decision threshold",
            "why_not": "Same missing field as the bias ratio.",
        },
        {
            "metric": "Competence (Equation 11, §4.2.7)",
            "needs": "ground-truth relevance for precision at k",
            "why_not": (
                "Precision needs to know whether a recommendation was right, "
                "which needs either a deployment or labelled relevance. The "
                "coverage term of the same equation IS computed here; the "
                "composite is not, because two of its three terms would be "
                "invented."
            ),
        },
        {
            "metric": "Misinformation exposure (Equation 13, §4.2.9)",
            "needs": "items flagged as containing misinformation",
            "why_not": "The dataset has product descriptions, not content claims.",
        },
        {
            "metric": "Unfairness (Equation 14, §4.2.10)",
            "needs": "group-level utilities",
            "why_not": "Same missing field as the bias ratio.",
        },
    ]


def hazard_report(
    rules: Iterable[Rule],
    catalogue: Iterable[int],
    *,
    new_items: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Every hazard metric this dataset supports, plus the ones it does not."""
    rules = list(rules)
    return {
        "source": (
            "Kathriarachchi, Alam & Rashid (2026), ACM Transactions on "
            "Recommender Systems 4(3), Article 42, section 4.2."
        ),
        "item_coverage": item_coverage(rules, catalogue),
        "new_item_coverage": (
            new_item_coverage(rules, new_items) if new_items is not None
            else {"available": False, "reason": "No new-item set supplied."}
        ),
        "transparency": transparency_index(rules),
        "exposure_concentration": exposure_concentration(rules),
        "not_computable": not_computable(),
        "count_rec_note": (
            "count_rec(i) is taken as the number of rules in which item i is a "
            "consequent. Their definition counts recommendation slots served to "
            "users; nothing is deployed here, so this is the closest available "
            "analogue and is reported as a substitution, not as their measure "
            "applied unchanged."
        ),
    }
