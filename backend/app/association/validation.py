"""Do the rules hold in a period they were not mined on? This is RQ3.

A rule mined and reported on the same baskets is not a finding, it is a
description. Every number in a mining output - support, confidence, lift, the
p-value - is computed on the data that produced the rule, so the rule cannot
fail. Published basket analyses frequently stop there.

The question that matters to a retailer is different and harder: **if I act on
this rule next quarter, will it still be true?** That is answered by mining on
an earlier period and re-measuring on a later one, which is the same move the
forecasting chapter makes with its locked hold-out and the segmentation chapter
makes by moving the window. Three chapters, one discipline: fit on what you
had, measure on what you had not seen.

Two different things are measured here, and they can disagree:

**Rule survival** - take each rule mined on the earlier period and recompute it
on the later one. Does it still clear lift > 1? This asks whether the specific
rules you would have acted on were worth acting on.

**Rule set overlap** - mine both periods independently and compare the two top-N
lists by Jaccard overlap. This asks whether the *method* is stable, which is a
different question: individual rules can survive while the ranking reshuffles,
and a recommendation widget driven by the top 20 cares about the ranking.

A rule can survive with a lift that has halved, so the lift correlation across
periods is reported too. Survival is a threshold; correlation is the shape.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.association.baskets import BasketSet
from app.association.itemsets import FrequentItemsets, frequent_itemsets
from app.association.rules import Rule, generate_rules

SURVIVED_WELL = 0.70
SURVIVED_POORLY = 0.40


def measure_on(
    rules: list[Rule], transactions: list[frozenset[int]]
) -> list[dict[str, Any]]:
    """Recompute each rule's numbers on a different set of baskets.

    No thresholds and no mining: the rules are given, and this counts them. A
    rule whose antecedent never appears in the new period is reported as
    unobservable rather than as failed - the distinction matters, because a
    product that was discontinued tells you nothing about the rule.
    """
    n = len(transactions)
    if n == 0:
        return [{"unobservable": True, "reason": "No baskets in the period."} for _ in rules]

    rows: list[dict[str, Any]] = []
    for rule in rules:
        antecedent, consequent = rule.antecedent, rule.consequent
        both = antecedent_count = consequent_count = 0
        for basket in transactions:
            has_a = antecedent <= basket
            has_c = consequent <= basket
            antecedent_count += has_a
            consequent_count += has_c
            both += has_a and has_c

        if antecedent_count == 0 or consequent_count == 0:
            rows.append({
                "unobservable": True,
                "reason": (
                    "The antecedent never occurs in this period."
                    if antecedent_count == 0
                    else "The consequent never occurs in this period."
                ),
                "antecedent_count": int(antecedent_count),
                "consequent_count": int(consequent_count),
            })
            continue

        confidence = both / antecedent_count
        consequent_support = consequent_count / n
        rows.append({
            "unobservable": False,
            "support": both / n,
            "support_count": int(both),
            "confidence": float(confidence),
            "lift": float(confidence / consequent_support),
            "antecedent_count": int(antecedent_count),
            "consequent_count": int(consequent_count),
        })
    return rows


def validate_rules(
    rules: list[Rule],
    holdout: BasketSet,
    *,
    min_lift: float = 1.0,
    min_support_count: int = 5,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """The RQ3 answer: what share of mined rules still hold out of sample.

    **Surviving takes two things, not one.** The rule's lift on the hold-out
    must exceed `min_lift`, *and* the association must still be statistically
    significant there. Lift alone is not enough: two independent products land
    at a lift of 1.00 on average, so roughly half of all dead rules land
    fractionally above it by chance and would be counted as survivals. That
    would not be a measurement, it would be a coin flip reported as a finding.

    The hold-out p-values get the same Benjamini-Hochberg correction the mining
    step uses, applied across the rules being judged - hundreds of tests here
    too, and the same reason for correcting them.

    `min_support_count` guards the denominator separately. A rule whose
    antecedent appears four times in the hold-out can clear any lift threshold
    on a single basket; those are reported as too thin to judge rather than
    counted either way.
    """
    if not rules:
        return {"available": False, "reason": "No rules to validate."}

    measured = measure_on(rules, holdout.transactions)
    n = holdout.n_transactions

    observable = [
        (rule, row) for rule, row in zip(rules, measured, strict=True)
        if not row.get("unobservable") and row["antecedent_count"] >= min_support_count
    ]
    q_values = _holdout_significance(observable, n)

    survived: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    thin: list[dict[str, Any]] = []
    unobservable = 0
    lost_on_significance = 0
    judged_index = 0

    for rule, row in zip(rules, measured, strict=True):
        if row.get("unobservable"):
            unobservable += 1
            continue
        record = {
            "antecedent": sorted(rule.antecedent),
            "consequent": sorted(rule.consequent),
            "mined_lift": rule.lift,
            "holdout_lift": row["lift"],
            "mined_confidence": rule.confidence,
            "holdout_confidence": row["confidence"],
            "holdout_support_count": row["support_count"],
            "lift_change": row["lift"] - rule.lift,
        }
        if row["antecedent_count"] < min_support_count:
            thin.append(record)
            continue

        q = q_values[judged_index]
        judged_index += 1
        record["holdout_q_value"] = q
        record["holdout_significant"] = bool(q <= alpha)

        if row["lift"] > min_lift and q <= alpha:
            survived.append(record)
        else:
            if row["lift"] > min_lift:
                lost_on_significance += 1
            failed.append(record)

    judged = len(survived) + len(failed)
    if judged == 0:
        return {
            "available": False,
            "reason": (
                f"None of the {len(rules):,} rules could be judged on the hold-out: "
                f"{unobservable:,} were unobservable and {len(thin):,} too thin. "
                f"The hold-out may be too short, or the products too seasonal."
            ),
        }

    rate = len(survived) / judged
    mined_lifts = np.array([r["mined_lift"] for r in survived + failed])
    held_lifts = np.array([r["holdout_lift"] for r in survived + failed])
    correlation = _spearman(mined_lifts, held_lifts)

    survived.sort(key=lambda row: row["holdout_lift"], reverse=True)
    failed.sort(key=lambda row: row["lift_change"])

    return {
        "available": True,
        "rules_mined": len(rules),
        "judged": judged,
        "survived": len(survived),
        "failed": len(failed),
        "too_thin": len(thin),
        "unobservable": unobservable,
        "survival_rate": float(rate),
        "failed_on_significance_alone": lost_on_significance,
        "median_lift_mined": float(np.median(mined_lifts)),
        "median_lift_holdout": float(np.median(held_lifts)),
        "lift_shrinkage": float(np.median(held_lifts) - np.median(mined_lifts)),
        "lift_rank_correlation": correlation,
        "strongest_survivors": survived[:10],
        "largest_falls": failed[:10],
        "verdict": _verdict(rate, correlation, float(np.median(held_lifts) - np.median(mined_lifts))),
        "method_note": (
            f"Rules were mined on the earlier baskets and recomputed, unchanged, "
            f"on {holdout.n_transactions:,} later ones. Nothing was refitted. "
            f"Surviving required both lift above {min_lift} and significance at "
            f"alpha = {alpha} after a Benjamini-Hochberg correction across the "
            f"{judged:,} rules judged; {lost_on_significance:,} rules cleared the "
            f"lift threshold but not the test, which is what independence looks "
            f"like when it lands fractionally above 1.0 by chance. Rules whose "
            f"antecedent occurs fewer than {min_support_count} times in the "
            f"hold-out are excluded from the rate rather than counted either way."
        ),
    }


def _holdout_significance(
    observable: list[tuple[Rule, dict[str, Any]]], n: int
) -> list[float]:
    """One-sided Fisher exact test per rule on the hold-out, BH-corrected.

    Identical in form to the test applied when mining, and for the same reason:
    hundreds of rules are being judged at once, so uncorrected p-values would
    manufacture survivors.
    """
    from scipy.stats import fisher_exact

    from app.association.rules import benjamini_hochberg

    p_values: list[float] = []
    for _, row in observable:
        both = row["support_count"]
        antecedent_only = row["antecedent_count"] - both
        consequent_only = row["consequent_count"] - both
        neither = n - both - antecedent_only - consequent_only
        _, p = fisher_exact(
            [[both, max(0, antecedent_only)], [max(0, consequent_only), max(0, neither)]],
            alternative="greater",
        )
        p_values.append(float(p))

    return benjamini_hochberg(p_values)


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    """Rank correlation, which is the right one: lift is not normally distributed."""
    if a.size < 3:
        return None
    from scipy.stats import spearmanr

    with np.errstate(invalid="ignore"):
        result = spearmanr(a, b)
    value = float(result.statistic)
    return None if np.isnan(value) else value


def _verdict(rate: float, correlation: float | None, shrinkage: float) -> str:
    """The sentence the numbers support, and no stronger."""
    ordering = (
        f" The lift ranking is {'preserved' if correlation >= 0.5 else 'largely lost'} "
        f"across periods (Spearman {correlation:.2f})."
        if correlation is not None else ""
    )
    drift = (
        f" Median lift fell by {abs(shrinkage):.2f} out of sample, which is the "
        f"optimism of measuring a rule on the data that produced it."
        if shrinkage < -0.05 else ""
    )

    if rate >= SURVIVED_WELL:
        return (
            f"{rate:.1%} of rules still hold on baskets they were not mined on. "
            f"The associations describe the business rather than the mining "
            f"window, and acting on the stronger ones is defensible.{ordering}{drift}"
        )
    if rate >= SURVIVED_POORLY:
        return (
            f"{rate:.1%} of rules hold out of sample, so {1 - rate:.1%} of what "
            f"mining produced would not have repeated. The rules should be "
            f"presented with their hold-out figures beside the mined ones, never "
            f"the mined ones alone.{ordering}{drift}"
        )
    return (
        f"Only {rate:.1%} of rules hold out of sample. Most of what mining "
        f"produced is specific to the period it was mined on, so a rule table "
        f"reported without validation would have overstated the findings "
        f"substantially. This is a result about the method, and it is the "
        f"finding to report.{ordering}{drift}"
    )


def rule_set_overlap(
    first: list[Rule], second: list[Rule], *, n: int = 50
) -> dict[str, Any]:
    """Jaccard overlap of the top-N rules mined independently in two periods.

    Different question from survival. Survival asks whether a given rule stayed
    true; this asks whether mining the second period would have *found* the same
    rules. A recommendation list rebuilt each quarter lives on this number.
    """
    def top(rules: list[Rule]) -> set[tuple[tuple[int, ...], tuple[int, ...]]]:
        ranked = sorted(
            (r for r in rules if r.is_association),
            key=lambda r: (-r.lift, -r.support),
        )[:n]
        return {
            (tuple(sorted(r.antecedent)), tuple(sorted(r.consequent))) for r in ranked
        }

    a, b = top(first), top(second)
    if not a or not b:
        return {
            "available": False,
            "reason": "One of the periods produced no associations to compare.",
        }

    shared = a & b
    jaccard = len(shared) / len(a | b)
    return {
        "available": True,
        "n": n,
        "first_rules": len(a),
        "second_rules": len(b),
        "shared": len(shared),
        "jaccard": float(jaccard),
        "note": (
            f"Mining the two periods independently produced top-{n} lists sharing "
            f"{len(shared)} rules (Jaccard {jaccard:.2f}). This measures whether "
            f"the method finds the same rules again, which is a different question "
            f"from whether a given rule stayed true."
        ),
    }


def mine_period(
    baskets: BasketSet,
    *,
    min_support: float,
    min_confidence: float,
    max_length: int,
    min_lift: float = 1.0,
    fdr_alpha: float = 0.05,
) -> tuple[FrequentItemsets, list[Rule]]:
    """Mine one period end to end, with the same settings as any other.

    A convenience, but a load-bearing one: the independent mining of the second
    period must use identical thresholds or the overlap number measures the
    settings rather than the data.
    """
    itemsets = frequent_itemsets(
        baskets.transactions, min_support=min_support, max_length=max_length
    )
    rules = generate_rules(
        itemsets,
        min_confidence=min_confidence,
        min_lift=min_lift,
        fdr_alpha=fdr_alpha,
    )
    return itemsets, rules
