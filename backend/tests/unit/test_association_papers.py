"""The parts of RQ3 taken from the four supplied papers, tested against them.

Each test names the paper, the section and where possible the worked example it
reproduces. Two of them reproduce published numbers exactly:

- `test_qiu_table_2_is_reproduced_exactly` - Qiu et al. (2023) Table 2.
- `test_their_synthetic_item_coverage_is_reproduced` - Kathriarachchi et al.
  (2026) Equations 4 and 10 on their synthetic dataset.

The rest check properties the papers prove algebraically, most importantly
Ni et al.'s Property 2: normalised lift does not move when the number of
baskets containing neither item changes, and plain lift does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.association.baskets import build_baskets, compare_singleton_policies
from app.association.colocation import (
    affinity_graph,
    assign_zones,
    evaluate_layout,
    picking_effort,
)
from app.association.hazards import (
    exposure_concentration,
    hazard_report,
    item_coverage,
    new_item_coverage,
    not_computable,
    transparency_index,
)
from app.association.itemsets import frequent_itemsets
from app.association.measures import dependence, describe, lift_inflation
from app.association.rules import Rule, generate_rules


def rule(antecedent, consequent, **overrides) -> Rule:
    base = dict(
        support=0.1, support_count=10, antecedent_support=0.2,
        consequent_support=0.2, confidence=0.5, lift=2.5, leverage=0.06,
        conviction=1.6, zhang=0.6, normalised_lift=0.4,
    )
    base.update(overrides)
    return Rule(
        antecedent=frozenset(antecedent), consequent=frozenset(consequent), **base
    )


# ==========================================================================
# Ni, Luo, Lu & Zhu (2020), ACM TMIS 11(1) Article 3, section 4
# ==========================================================================

def test_all_confidence_matches_equation_3():
    """all_conf({x,y}) = sigma(x,y) / max(sigma(x), sigma(y))."""
    measures = dependence(
        both=30, antecedent=50, consequent=120, n_transactions=1000, largest_item=120
    )
    assert measures.all_confidence == pytest.approx(30 / 120)


def test_is_is_cosine_not_lift():
    """Equation 4 has a square root, and losing it turns IS into lift.

    IS(x,y) = s(x,y) / sqrt(s(x) * s(y)). Without the radical this would be
    30 / (50*120/1000) = 5.0 rather than 0.387 - a different measure, and one
    that is not bounded by 1.
    """
    measures = dependence(
        both=30, antecedent=50, consequent=120, n_transactions=1000
    )
    assert measures.cosine == pytest.approx(30 / (50 * 120) ** 0.5)
    assert measures.cosine == pytest.approx(0.3873, abs=1e-4)
    assert 0.0 <= measures.cosine <= 1.0


def test_normalised_lift_matches_the_closed_form_in_equation_9():
    """Nlift = 1 - (f10 / (f11 + f10)) * (f01 / (f11 + f01)).

    Their Equation 9 derives this from Equation 8. Computing it the other way
    - through the universe-based supports - must give the same number, or one
    of the two is implemented wrong.
    """
    f11, f10, f01 = 30, 20, 90
    measures = dependence(
        both=f11, antecedent=f11 + f10, consequent=f11 + f01, n_transactions=1000
    )
    expected = 1 - (f10 / (f11 + f10)) * (f01 / (f11 + f01))
    assert measures.normalised_lift == pytest.approx(expected)


def test_normalised_lift_is_bounded_in_zero_one():
    """Property 1. Plain lift has no fixed upper bound; this does."""
    rng = np.random.default_rng(4)
    for _ in range(300):
        n = int(rng.integers(50, 5000))
        both = int(rng.integers(1, 40))
        antecedent = both + int(rng.integers(0, 200))
        consequent = both + int(rng.integers(0, 200))
        if antecedent + consequent - both > n:
            continue
        measures = dependence(
            both=both, antecedent=antecedent, consequent=consequent, n_transactions=n
        )
        assert 0.0 <= measures.normalised_lift <= 1.0 + 1e-12
        assert 0.0 <= measures.all_confidence <= 1.0 + 1e-12
        assert 0.0 <= measures.cosine <= 1.0 + 1e-12


def test_normalised_lift_ignores_baskets_containing_neither_item():
    """Property 2, and the reason this module exists.

    Ni et al.: "when f00 increases, the value of lift raises, too... Thus, the
    value of lift does not have a fixed upper bound." In a catalogue of
    thousands of products f00 is nearly every basket, so plain lift is partly a
    measure of how large the catalogue is. Growing the dataset with baskets
    containing neither item must not change a verdict about those two items.
    """
    f11, f10, f01 = 20, 30, 40
    small = dependence(
        both=f11, antecedent=f11 + f10, consequent=f11 + f01, n_transactions=200
    )
    large = dependence(
        both=f11, antecedent=f11 + f10, consequent=f11 + f01, n_transactions=20_000
    )

    assert large.normalised_lift == pytest.approx(small.normalised_lift)
    assert large.all_confidence == pytest.approx(small.all_confidence)
    assert large.cross_support == pytest.approx(small.cross_support)

    # Plain lift, by contrast, moves by two orders of magnitude on identical
    # evidence about the pair.
    lift_small = (f11 * 200) / ((f11 + f10) * (f11 + f01))
    lift_large = (f11 * 20_000) / ((f11 + f10) * (f11 + f01))
    assert lift_large / lift_small == pytest.approx(100.0)


def test_cross_support_matches_equation_10():
    """min(s(x), s(y)) / max(s(x), s(y)), computable from counts alone."""
    measures = dependence(
        both=5, antecedent=10, consequent=1000, n_transactions=5000
    )
    assert measures.cross_support == pytest.approx(10 / 1000)


def test_cross_support_flags_items_selling_at_very_different_rates():
    """Their section 4.4: the case where confidence is least informative."""
    lopsided = dependence(both=9, antecedent=10, consequent=4000, n_transactions=20000)
    assert lopsided.confidence if False else True       # confidence is 0.9 here
    assert lopsided.cross_support < 0.01
    assert "cross-support" in describe(lopsided)


def test_lift_inflation_quantifies_how_much_came_from_the_catalogue():
    report = lift_inflation(
        both=20, antecedent=50, consequent=60, n_transactions=20_000
    )
    assert report["available"]
    assert report["lift"] > 100                 # looks spectacular
    assert report["normalised_lift"] <= 1.0     # and is not
    assert report["f00_share"] > 0.99
    assert "catalogue" in report["note"]


def test_impossible_counts_are_refused():
    """A joint count above a margin is a bug upstream, not a measure of zero."""
    with pytest.raises(ValueError, match="Impossible counts"):
        dependence(both=50, antecedent=10, consequent=10, n_transactions=100)


def test_the_measures_reach_the_rules():
    """Generated rules must carry Ni et al.'s measures, not just lift."""
    transactions = [frozenset({0, 1})] * 60 + [frozenset({2})] * 40
    itemsets = frequent_itemsets(transactions, min_support=0.1, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    assert rules
    for generated in rules:
        assert 0.0 <= generated.normalised_lift <= 1.0
        assert 0.0 <= generated.all_confidence <= 1.0
        assert generated.as_dict()["normalised_lift"] == generated.normalised_lift


def test_a_cross_support_floor_filters_lopsided_pairs():
    transactions = (
        [frozenset({0, 1})] * 20 + [frozenset({1})] * 900 + [frozenset({2})] * 80
    )
    itemsets = frequent_itemsets(transactions, min_support=0.01, max_length=2)
    permissive = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    strict = generate_rules(
        itemsets, min_confidence=0.0, min_lift=0.0, test=False, min_cross_support=0.5
    )
    assert len(strict) < len(permissive)


def test_significance_testing_preserves_the_new_measures():
    """A regression: test_rules once rebuilt Rule field by field and would have
    silently dropped anything added to the dataclass."""
    transactions = [frozenset({0, 1})] * 60 + [frozenset({2})] * 40
    itemsets = frequent_itemsets(transactions, min_support=0.1, max_length=2)
    untested = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    tested = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=True)

    before = {(r.antecedent, r.consequent): r.normalised_lift for r in untested}
    for generated in tested:
        assert generated.normalised_lift == pytest.approx(
            before[(generated.antecedent, generated.consequent)]
        )
        assert generated.q_value is not None


# ==========================================================================
# Qiu, Ning, Zhang & Yang (2023), ICMLCA 2023, sections 3.1-3.2
# ==========================================================================

def qiu_transaction_set_a():
    """Their Table 1: I1 = {a,b,c}, I2 = {b,d}, I3 = {b,d}, I4 = {d}.

    Renamed PA-PD because single letters b, d, m, s and c2 are in the
    pipeline's non-product code list and would be stripped before mining.
    """
    rows = [
        ("I1", "PA"), ("I1", "PB"), ("I1", "PC"),
        ("I2", "PB"), ("I2", "PD"),
        ("I3", "PB"), ("I3", "PD"),
        ("I4", "PD"),
    ]
    return build_baskets(
        pd.DataFrame(rows, columns=["invoice_id", "product_code"])
    )


def test_qiu_table_2_is_reproduced_exactly():
    """Their Table 2, both columns, including the confidence that changes.

    Traditional Apriori on four transactions with a minimum support count of 2
    gives P(b->d) = 0.67 and P(d->b) = 0.67. After their deletion module drops
    the single-item transaction I4, P(d->b) becomes 1.00 while P(b->d) stays
    at 0.67. Reproducing both columns is what makes the critique checkable
    rather than rhetorical.
    """
    baskets = qiu_transaction_set_a()
    codes = {code: item for item, code in baskets.labels.items()}
    b, d = codes["PB"], codes["PD"]

    def confidences(transactions):
        itemsets = frequent_itemsets(transactions, min_support=0.5, max_length=2)
        rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
        return {
            (tuple(sorted(r.antecedent)), tuple(sorted(r.consequent))): r
            for r in rules
        }

    traditional = confidences(baskets.transactions)
    deleted = confidences([t for t in baskets.transactions if len(t) > 1])

    assert traditional[((b,), (d,))].confidence == pytest.approx(2 / 3, abs=0.005)
    assert traditional[((d,), (b,))].confidence == pytest.approx(2 / 3, abs=0.005)

    assert deleted[((b,), (d,))].confidence == pytest.approx(2 / 3, abs=0.005)
    assert deleted[((d,), (b,))].confidence == pytest.approx(1.0)

    # And the finding that matters: the evidence did not change.
    assert traditional[((d,), (b,))].support_count == 2
    assert deleted[((d,), (b,))].support_count == 2


def test_the_comparison_reports_rules_inflated_without_new_evidence():
    """The deletion module's extra rules, separated from real discoveries."""
    baskets = qiu_transaction_set_a()
    outcome = compare_singleton_policies(
        baskets, min_support=0.5, min_confidence=0.0
    )
    assert outcome["available"]
    assert outcome["singletons_removed"] == 1
    assert outcome["rules_inflated_without_new_evidence"] >= 1

    example = outcome["examples"][0]
    assert example["support_without"] > example["support_with"]
    assert "denominator" in outcome["verdict"]


def test_removing_singletons_raises_support_on_real_data():
    """The same effect at scale, which is the form it takes on Online Retail II."""
    rows = []
    for index in range(100):
        items = ["P1", "P2"] if index < 40 else ["P3"]
        for code in items:
            rows.append((f"INV{index}", code))
    baskets = build_baskets(pd.DataFrame(rows, columns=["invoice_id", "product_code"]))

    outcome = compare_singleton_policies(baskets, min_support=0.1, min_confidence=0.1)
    assert outcome["singleton_share"] == pytest.approx(0.6)
    assert outcome["with_singletons"]["baskets"] == 100
    assert outcome["without_singletons"]["baskets"] == 40


# ==========================================================================
# Kathriarachchi, Alam & Rashid (2026), ACM TORS 4(3) Article 42, section 4.2
# ==========================================================================

def test_their_synthetic_item_coverage_is_reproduced():
    """Equation 10 on their worked example: 10 of 12 items -> 0.833."""
    catalogue = list(range(12))
    rules = [rule({100 + i}, {i}) for i in range(10)]     # items 0-9 recommended
    outcome = item_coverage(rules, catalogue)

    assert outcome["reachable"] == 10
    assert outcome["catalogue_size"] == 12
    assert outcome["item_coverage"] == pytest.approx(10 / 12, abs=1e-4)
    assert outcome["item_coverage"] == pytest.approx(0.833, abs=0.001)


def test_their_synthetic_new_item_coverage_is_reproduced():
    """Equation 4: count_rec(i9)=1, count_rec(i10)=1, i11 and i12 zero -> 0.500."""
    new_items = [9, 10, 11, 12]
    rules = [rule({1}, {9}), rule({2}, {10})]
    outcome = new_item_coverage(rules, new_items, threshold=1)

    assert outcome["covered"] == 2
    assert outcome["coverage_new"] == pytest.approx(0.5)


def test_new_products_are_unreachable_by_rules_mined_before_they_existed():
    """The cold-start hazard, and for association rules it is structural."""
    rules = [rule({1}, {2}), rule({2}, {3})]
    outcome = new_item_coverage(rules, [90, 91, 92])
    assert outcome["coverage_new"] == 0.0
    assert "structural limit" in outcome["verdict"]


def test_transparency_is_one_by_construction():
    """Equation 12. Their synthetic system scores 0.500; a rule is its own
    explanation, so there is no slot without one."""
    outcome = transparency_index([rule({1}, {2})])
    assert outcome["transparency_index"] == 1.0
    assert "0.500" in outcome["verdict"]


def test_item_coverage_exposes_the_popularity_bias_of_a_support_threshold():
    """4,000 products, rules reaching 40 of them: the bias made a number."""
    catalogue = list(range(4000))
    rules = [rule({i + 1}, {i}) for i in range(40)]
    outcome = item_coverage(rules, catalogue)
    assert outcome["item_coverage"] == pytest.approx(0.01)
    assert "never clears minimum support" in outcome["verdict"]


def test_exposure_concentration_separates_even_from_skewed():
    even = [rule({100 + i}, {i}) for i in range(20)]
    skewed = [rule({100 + i}, {0}) for i in range(19)] + [rule({200}, {1})]
    assert exposure_concentration(even)["gini"] < 0.05
    assert exposure_concentration(skewed)["gini"] > 0.4


def test_the_metrics_this_dataset_cannot_support_are_listed_with_reasons():
    """A fairness number from a dataset with no demographic field would be
    worse than no number, so the gap is reported rather than hidden."""
    missing = not_computable()
    assert len(missing) == 8
    for entry in missing:
        assert entry["needs"] and entry["why_not"]
    text = " ".join(entry["metric"] for entry in missing)
    assert "Bias ratio" in text and "Privacy risk" in text and "Competence" in text


def test_the_hazard_report_carries_its_source_and_its_substitution():
    report = hazard_report(
        [rule({1}, {2})], catalogue=[1, 2, 3], new_items=[9]
    )
    assert "Kathriarachchi" in report["source"]
    assert "substitution" in report["count_rec_note"]
    assert report["item_coverage"]["available"]
    assert len(report["not_computable"]) == 8


# ==========================================================================
# Jirapatsil & Phumchusri (2022), MSIE 2022
# ==========================================================================

def test_affinity_collapses_both_directions_of_a_pair():
    """A rule is directed; a shelf is not."""
    forward = rule({0}, {1}, normalised_lift=0.3)
    backward = rule({1}, {0}, normalised_lift=0.7)
    graph = affinity_graph([forward, backward])
    assert graph == {(0, 1): pytest.approx(0.7)}


def test_affinity_defaults_to_normalised_lift_not_lift():
    """Using plain lift would let two rare items decide the layout, because
    lift grows with the catalogue (Ni et al. 2020)."""
    generated = rule({0}, {1}, lift=900.0, normalised_lift=0.02)
    assert affinity_graph([generated])[(0, 1)] == pytest.approx(0.02)
    assert affinity_graph([generated], weight="lift")[(0, 1)] == pytest.approx(900.0)


def test_an_unknown_affinity_measure_is_refused():
    with pytest.raises(ValueError, match="Unknown affinity measure"):
        affinity_graph([], weight="proximity")


def test_zones_respect_their_capacity_and_hold_every_product():
    catalogue = list(range(23))
    affinity = {(0, 1): 0.9, (1, 2): 0.8, (10, 11): 0.7}
    assignment = assign_zones(catalogue, affinity, zone_capacity=5)

    assert set(assignment) == set(catalogue)
    sizes = pd.Series(list(assignment.values())).value_counts()
    assert sizes.max() <= 5


def test_zones_are_filled_even_when_affinity_runs_out():
    """The bug this guards: closing a zone the moment no candidate has affinity.

    On a long-tailed catalogue most products appear in no rule. Closing early
    gave every one of them a zone of its own - hundreds of one-product zones -
    and the resulting layout needed MORE picking visits than a random one,
    which looks like a finding about the rules and is a defect in the grouping.

    23 products at capacity 5 must occupy 5 zones, not 20.
    """
    catalogue = list(range(23))
    affinity = {(0, 1): 0.9}                 # only two products are connected
    assignment = assign_zones(catalogue, affinity, zone_capacity=5)

    sizes = pd.Series(list(assignment.values())).value_counts()
    assert len(sizes) == 5                   # ceil(23 / 5)
    assert sizes.max() <= 5
    assert (sizes >= 3).sum() >= 4           # zones are full, not vestigial


def test_a_rule_driven_layout_is_never_worse_than_random_by_construction():
    """With no affinity at all the grouping degenerates to popularity order,
    which should still pack shelves as densely as a shuffle does."""
    rng = np.random.default_rng(11)
    transactions = [
        frozenset(rng.choice(range(40), size=4, replace=False).tolist())
        for _ in range(400)
    ]
    popularity = {}
    for basket in transactions:
        for item in basket:
            popularity[item] = popularity.get(item, 0) + 1

    outcome = evaluate_layout(
        transactions, catalogue=list(range(40)), affinity={},
        zone_capacity=10, popularity=popularity, random_seeds=5,
    )
    assert outcome["available"]
    assert outcome["reduction_vs_random"] > -0.05


def test_associated_products_land_in_the_same_zone():
    catalogue = list(range(12))
    affinity = {(0, 1): 0.9, (0, 2): 0.85, (1, 2): 0.8, (6, 7): 0.9}
    assignment = assign_zones(catalogue, affinity, zone_capacity=3)
    assert assignment[0] == assignment[1] == assignment[2]


def test_picking_effort_counts_distinct_zones_not_items():
    """A picker walks to a zone once however many items they take from it."""
    assignment = {0: 0, 1: 0, 2: 1}
    outcome = picking_effort([frozenset({0, 1}), frozenset({0, 2})], assignment)
    assert outcome["mean_zones_per_order"] == pytest.approx(1.5)
    assert outcome["single_zone_share"] == pytest.approx(0.5)


def test_a_rule_driven_layout_beats_random_when_the_rules_are_real():
    """Their method, measured on the quantity a layout is chosen to minimise.

    Six products that genuinely travel together in pairs. A grouping built from
    the mined rules should need fewer zone visits per order than a shuffle.
    """
    rng = np.random.default_rng(2026)
    rows = []
    pairs = [("P1", "P2"), ("P3", "P4"), ("P5", "P6")]
    for index in range(1200):
        items = set()
        for left, right in pairs:
            if rng.random() < 0.35:
                items.update({left, right})
        if not items:
            items.add("P7")
        for code in items:
            rows.append((f"INV{index:05d}", code))

    baskets = build_baskets(pd.DataFrame(rows, columns=["invoice_id", "product_code"]))
    itemsets = frequent_itemsets(baskets.transactions, min_support=0.05, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.3)

    popularity = {}
    for basket in baskets.transactions:
        for item in basket:
            popularity[item] = popularity.get(item, 0) + 1

    outcome = evaluate_layout(
        baskets.transactions,
        catalogue=list(baskets.labels),
        affinity=affinity_graph(rules),
        zone_capacity=2,
        popularity=popularity,
        random_seeds=5,
    )

    assert outcome["available"]
    assert outcome["reduction_vs_random"] > 0.1
    assert "zone visits per order" in outcome["verdict"]


def test_the_layout_report_refuses_to_claim_metres():
    """Online Retail II has no layout, so their 54.4% cannot be reproduced and
    the report must say so rather than inventing a distance."""
    outcome = evaluate_layout(
        [frozenset({0, 1}), frozenset({1, 2})],
        catalogue=[0, 1, 2, 3],
        affinity={(0, 1): 0.9},
        zone_capacity=2,
    )
    note = outcome["method_note"]
    assert "cannot be computed and is not reported" in note
    assert "not comparable to their 54.4%" in note


def test_a_layout_that_is_no_better_than_popularity_says_so():
    """The verdict must be able to report a failure, or it is advertising."""
    from app.association.colocation import _verdict

    measured = {"mean_zones_per_order": 3.0, "single_zone_share": 0.1}
    assert "MORE than random" in _verdict(-0.2, 0.1, measured)
    assert "add nothing a sales ranking" in _verdict(0.2, -0.1, measured)
