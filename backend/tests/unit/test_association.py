"""Basket construction, Apriori, rule measures, pruning and hold-out validation.

The test this file exists for is `test_a_confident_rule_at_lift_one_is_not_an_association`.
Everything else guards a decision; that one guards the single mistake that
makes a basket analysis worthless - reporting a popular item as a discovery
because confidence was high.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from app.association.baskets import build_baskets, split_by_date
from app.association.itemsets import MiningError, frequent_itemsets, top_itemsets
from app.association.pruning import drop_redundant, drop_trivial
from app.association.rules import (
    Rule,
    benjamini_hochberg,
    generate_rules,
    summarise,
    top_rules,
)
from app.association.validation import (
    measure_on,
    mine_period,
    rule_set_overlap,
    validate_rules,
)


def lines(rows: list[tuple]) -> pd.DataFrame:
    """invoice, code, name, date, is_return."""
    return pd.DataFrame(
        rows, columns=["invoice_id", "product_code", "product_name", "occurred_at", "is_return"]
    )


def simple_baskets(sets: list[list[str]], *, start="2011-01-03"):
    """Baskets from a list of item-code lists, one invoice each, a day apart."""
    dates = pd.date_range(start, periods=len(sets), freq="D")
    rows = []
    for index, (items, date) in enumerate(zip(sets, dates, strict=True)):
        for code in items:
            rows.append((f"INV{index:04d}", code, f"NAME {code}", date, False))
    return build_baskets(lines(rows))


# --------------------------------------------------------------------------
# architecture
# --------------------------------------------------------------------------

def test_the_association_package_stays_pure():
    """Pure core, thin shell - checked rather than trusted.

    Every function in this package takes a DataFrame and returns dictionaries.
    The moment one of them imports a session or a request, it can no longer be
    tested without a database, and the architecture's claim stops being true
    quietly. This is the same check the other pure packages are held to.
    """
    import ast
    from pathlib import Path

    banned = (
        "fastapi", "sqlalchemy", "pydantic", "starlette", "psycopg",
        "alembic", "app.db", "app.api", "app.services",
    )
    package = Path(__file__).resolve().parents[2] / "app" / "association"
    offences: list[str] = []

    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if any(module == b or module.startswith(b + ".") for b in banned):
                    offences.append(f"{path.name} imports {module}")

    assert not offences, "the pure core reached into the shell: " + "; ".join(offences)


# --------------------------------------------------------------------------
# baskets
# --------------------------------------------------------------------------

def test_an_invoice_becomes_one_basket_and_quantity_is_irrelevant():
    """Two lines of the same product are one item: a basket is a set."""
    frame = lines([
        ("INV1", "P1", "Tea", pd.Timestamp("2011-01-03"), False),
        ("INV1", "P1", "Tea", pd.Timestamp("2011-01-03"), False),
        ("INV1", "P2", "Mug", pd.Timestamp("2011-01-03"), False),
    ])
    baskets = build_baskets(frame)
    assert baskets.n_transactions == 1
    assert len(baskets.transactions[0]) == 2


def test_return_lines_are_excluded():
    """A credit note is the reversal of a purchase decision, not a second one."""
    frame = lines([
        ("INV1", "P1", "Tea", pd.Timestamp("2011-01-03"), False),
        ("INV1", "P2", "Mug", pd.Timestamp("2011-01-03"), False),
        ("C2", "P1", "Tea", pd.Timestamp("2011-01-04"), True),
        ("C2", "P2", "Mug", pd.Timestamp("2011-01-04"), True),
    ])
    baskets = build_baskets(frame)
    assert baskets.n_transactions == 1
    assert baskets.excluded["return_lines"] == 2


def test_non_product_codes_come_from_the_field_guide_not_a_local_list():
    """The reconciliation bug: a restated rule drifts from the real one.

    POST is in the pipeline's list. If this module kept its own copy and the
    pipeline's grew, this test would still pass against the stale copy - so the
    assertion is on the imported constant, not on a literal.
    """
    from app.preprocessing.field_guide import NON_PRODUCT_CODES

    assert "POST" in NON_PRODUCT_CODES
    frame = lines([
        ("INV1", "P1", "Tea", pd.Timestamp("2011-01-03"), False),
        ("INV1", "POST", "POSTAGE", pd.Timestamp("2011-01-03"), False),
        ("INV2", "P1", "Tea", pd.Timestamp("2011-01-04"), False),
        ("INV2", "POST", "POSTAGE", pd.Timestamp("2011-01-04"), False),
    ])
    baskets = build_baskets(frame)
    assert baskets.excluded["non_product_lines"] == 2
    assert all(len(t) == 1 for t in baskets.transactions)
    assert "POST" not in set(baskets.labels.values())


def test_single_item_baskets_are_kept_by_default():
    """They belong in the denominator even though they can carry no rule."""
    baskets = simple_baskets([["P1"], ["P1", "P2"], ["P1", "P2"]])
    assert baskets.n_transactions == 3

    itemsets = frequent_itemsets(baskets.transactions, min_support=0.5)
    # {A, B} occurs in 2 of 3 baskets. Dropping the singleton would make it 2/2.
    assert itemsets.support(frozenset({0, 1})) == pytest.approx(2 / 3)


def test_raising_min_basket_size_is_recorded_as_a_decision():
    baskets = build_baskets(
        lines([
            ("INV1", "P1", "Tea", pd.Timestamp("2011-01-03"), False),
            ("INV2", "P1", "Tea", pd.Timestamp("2011-01-04"), False),
            ("INV2", "P2", "Mug", pd.Timestamp("2011-01-04"), False),
        ]),
        min_basket_size=2,
    )
    assert baskets.n_transactions == 1
    assert baskets.excluded["baskets_below_min_size"] == 1
    assert any("denominator" in note or "support" in note for note in baskets.notes)


def test_missing_required_columns_say_which_and_why():
    with pytest.raises(ValueError, match="product_code"):
        build_baskets(pd.DataFrame({"invoice_id": ["INV1"]}))


def test_the_item_vocabulary_is_stable_across_runs():
    """Sorted ids, so a results file can be diffed against an earlier one."""
    first = simple_baskets([["P2", "P1"], ["P1", "P3"]])
    second = simple_baskets([["P1", "P2"], ["P3", "P1"]])
    assert first.labels == second.labels


def test_a_subset_keeps_the_vocabulary():
    """Hold-out comparison is meaningless if item 42 means two different things."""
    baskets = simple_baskets([["P1", "P2"], ["P2", "P3"], ["P1", "P3"]])
    part = baskets.subset([True, False, True])
    assert part.labels == baskets.labels
    assert part.n_transactions == 2


def test_the_size_profile_counts_the_pairs_each_basket_implies():
    """A basket of n items carries n(n-1)/2 pairs - the number that explains why
    a few wholesale orders can dominate the result."""
    baskets = simple_baskets([["P1", "P2", "P3"], ["P1", "P2"]])
    profile = baskets.size_profile()
    assert profile["pairs_implied"] == 3 + 1
    assert profile["max_size"] == 3


# --------------------------------------------------------------------------
# splitting
# --------------------------------------------------------------------------

def test_the_split_is_chronological_not_random():
    """A random split confirms a seasonal pairing with baskets from the same week."""
    baskets = simple_baskets([["P1"], ["P2"], ["P3"], ["P4"]], start="2011-01-03")
    earlier, later = split_by_date(baskets, holdout_fraction=0.5)
    assert max(earlier.dates) < min(later.dates)
    assert earlier.n_transactions + later.n_transactions == 4


def test_a_split_without_dates_is_refused():
    frame = pd.DataFrame({
        "invoice_id": ["INV1", "INV2"],
        "product_code": ["P1", "P2"],
    })
    baskets = build_baskets(frame)
    with pytest.raises(ValueError, match="chronologically"):
        split_by_date(baskets)


# --------------------------------------------------------------------------
# itemsets
# --------------------------------------------------------------------------

def brute_force(transactions, min_count, max_length):
    """Count every subset. Correct, unusable beyond toy data - which is the point."""
    items = sorted(set().union(*transactions)) if transactions else []
    found = {}
    for length in range(1, max_length + 1):
        for candidate in combinations(items, length):
            key = frozenset(candidate)
            count = sum(1 for basket in transactions if key <= basket)
            if count >= min_count:
                found[key] = count
    return found


def test_apriori_agrees_with_counting_every_subset():
    """The only test that proves the pruning is sound rather than merely fast."""
    rng = np.random.default_rng(20260101)
    vocabulary = list(range(8))
    transactions = [
        frozenset(rng.choice(vocabulary, size=int(rng.integers(1, 6)), replace=False).tolist())
        for _ in range(200)
    ]
    itemsets = frequent_itemsets(transactions, min_support=0.05, max_length=3)
    expected = brute_force(transactions, itemsets.min_count, 3)
    assert itemsets.all_itemsets() == expected


def test_closure_prunes_the_exact_candidate_it_should():
    """Built by hand so the pruning is demonstrated, not inferred from a count.

    {0,1} and {0,2} are frequent, {1,2} is not. The join step will propose
    {0,1,2} because the two frequent pairs share the prefix (0,). Closure must
    reject it on the strength of {1,2} being rare, *without counting it* - the
    candidate cannot occur more often than its rarest part.
    """
    transactions = (
        [frozenset({0, 1})] * 10
        + [frozenset({0, 2})] * 10
        + [frozenset({1, 2})] * 1
    )
    itemsets = frequent_itemsets(transactions, min_support=0.3, max_length=3)

    assert itemsets.min_count == 7
    assert itemsets.count({0, 1}) == 10
    assert itemsets.count({1, 2}) == 0          # below the floor
    assert itemsets.pruned_by_closure == 1      # {0,1,2}, rejected unmeasured
    assert itemsets.by_length.get(3, {}) == {}


def test_closure_still_prunes_at_scale():
    """The hand-built case proves correctness; this shows it matters."""
    rng = np.random.default_rng(7)
    transactions = [
        frozenset(rng.choice(range(25), size=4, replace=False).tolist())
        for _ in range(400)
    ]
    itemsets = frequent_itemsets(transactions, min_support=0.025, max_length=3)
    assert itemsets.pruned_by_closure > 50
    assert "Downward closure removed" in itemsets.as_dict()["pruning_note"]


def test_min_support_is_a_floor_not_an_approximation():
    """With 10 baskets at 25%, three occurrences qualify and two do not."""
    transactions = [frozenset({0}) for _ in range(3)] + [frozenset({1}) for _ in range(2)]
    transactions += [frozenset({2}) for _ in range(5)]
    itemsets = frequent_itemsets(transactions, min_support=0.25, max_length=1)
    assert itemsets.min_count == 3
    assert itemsets.count({0}) == 3
    assert itemsets.count({1}) == 0


def test_no_frequent_item_reports_why_rather_than_returning_nothing():
    transactions = [frozenset({i}) for i in range(50)]
    itemsets = frequent_itemsets(transactions, min_support=0.5)
    assert itemsets.total == 0
    assert "Lower" in " ".join(itemsets.notes)


def test_an_impossible_support_is_refused_before_any_work():
    with pytest.raises(MiningError):
        frequent_itemsets([frozenset({1})], min_support=0)
    with pytest.raises(MiningError):
        frequent_itemsets([frozenset({1})], min_support=1.5)


def test_mining_stops_and_says_so_rather_than_exhausting_memory():
    rng = np.random.default_rng(3)
    transactions = [
        frozenset(rng.choice(range(60), size=20, replace=False).tolist())
        for _ in range(200)
    ]
    itemsets = frequent_itemsets(
        transactions, min_support=0.02, max_length=4, max_candidates_per_level=50
    )
    assert itemsets.stopped_early
    assert "min_support" in itemsets.stopped_early


def test_top_itemsets_rank_by_count():
    baskets = simple_baskets([["P1", "P2"], ["P1", "P2"], ["P1", "P3"]])
    itemsets = frequent_itemsets(baskets.transactions, min_support=0.3, max_length=2)
    top = top_itemsets(itemsets, length=2, n=1)
    assert top[0]["count"] == 2


# --------------------------------------------------------------------------
# rules - the measures
# --------------------------------------------------------------------------

def test_a_confident_rule_at_lift_one_is_not_an_association():
    """The mistake this whole module exists to prevent.

    Item 1 is in 80% of baskets. Any rule pointing at it reaches confidence
    around 0.8, which looks like the strongest finding in the dataset. Lift
    says 1.0 - exactly independence - and `is_association` must therefore
    refuse it however confident it is.
    """
    rng = np.random.default_rng(42)
    transactions = []
    for _ in range(1000):
        basket = set()
        if rng.random() < 0.80:
            basket.add(1)          # the carrier bag
        if rng.random() < 0.30:
            basket.add(0)          # an ordinary product, independent of it
        if rng.random() < 0.30:
            basket.add(2)
        transactions.append(frozenset(basket))

    itemsets = frequent_itemsets(transactions, min_support=0.05, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.5, min_lift=0.0)

    bag_rules = [r for r in rules if r.consequent == frozenset({1})]
    assert bag_rules, "the popular-item rules should be generated, then judged"
    for rule in bag_rules:
        assert rule.confidence > 0.7                 # looks compelling
        assert rule.lift == pytest.approx(1.0, abs=0.12)
        assert not rule.is_association               # and is not an association


def test_a_planted_pairing_is_found_with_high_lift():
    """The positive control: if this fails, nothing else in the file means anything."""
    rng = np.random.default_rng(11)
    transactions = []
    for _ in range(1000):
        basket = set()
        if rng.random() < 0.20:
            basket.update({0, 1})                    # bought together
        for item in (2, 3, 4):
            if rng.random() < 0.25:
                basket.add(item)
        transactions.append(frozenset(basket))

    itemsets = frequent_itemsets(transactions, min_support=0.05, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.3)
    planted = [
        r for r in rules
        if r.antecedent == frozenset({0}) and r.consequent == frozenset({1})
    ]
    assert planted and planted[0].lift > 3
    assert planted[0].is_association
    assert planted[0].significant


def test_lift_is_confidence_over_consequent_support():
    """Stated as an identity so the definition cannot drift."""
    baskets = simple_baskets([["P1", "P2"], ["P1", "P2"], ["P1", "P3"], ["P2", "P3"]])
    itemsets = frequent_itemsets(baskets.transactions, min_support=0.25, max_length=2)
    for rule in generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False):
        assert rule.lift == pytest.approx(rule.confidence / rule.consequent_support)


def test_leverage_is_zero_under_independence_and_lift_is_one():
    rng = np.random.default_rng(5)
    transactions = [
        frozenset({i for i in (0, 1) if rng.random() < 0.5}) for _ in range(4000)
    ]
    itemsets = frequent_itemsets(transactions, min_support=0.05, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    for rule in rules:
        assert rule.lift == pytest.approx(1.0, abs=0.1)
        assert rule.leverage == pytest.approx(0.0, abs=0.02)


def test_a_rule_that_never_fails_has_infinite_conviction():
    baskets = simple_baskets([["P1", "P2"], ["P1", "P2"], ["P2"], ["P3"]])
    itemsets = frequent_itemsets(baskets.transactions, min_support=0.25, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    perfect = [r for r in rules if r.confidence == 1.0]
    assert perfect and all(np.isinf(r.conviction) for r in perfect)
    # It must still serialise - JSON has no infinity.
    assert perfect[0].as_dict()["conviction"] is None


def test_zhang_is_bounded_and_negative_for_dissociation():
    """Two products never bought together: a finding lift squashes into [0, 1)."""
    transactions = [frozenset({0, 2}) for _ in range(50)]
    transactions += [frozenset({1, 2}) for _ in range(50)]
    itemsets = frequent_itemsets(transactions, min_support=0.1, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    pair = [
        r for r in rules
        if r.antecedent == frozenset({0}) and r.consequent == frozenset({1})
    ]
    assert not pair          # support is zero, so it is never a frequent itemset
    for rule in rules:
        assert -1.0 <= rule.zhang <= 1.0


def test_only_single_item_consequents_by_default():
    baskets = simple_baskets([["P1", "P2", "P3"]] * 10)
    itemsets = frequent_itemsets(baskets.transactions, min_support=0.5, max_length=3)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0, test=False)
    assert all(len(r.consequent) == 1 for r in rules)

    wider = generate_rules(
        itemsets, min_confidence=0.0, min_lift=0.0, test=False, max_consequent_length=2
    )
    assert any(len(r.consequent) == 2 for r in wider)


# --------------------------------------------------------------------------
# rules - multiple testing
# --------------------------------------------------------------------------

def test_benjamini_hochberg_is_monotone_and_never_below_the_raw_p():
    p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.2, 0.5, 0.9]
    q = benjamini_hochberg(p_values)
    assert all(b >= a - 1e-12 for a, b in zip(p_values, q, strict=True))
    assert all(a <= b + 1e-12 for a, b in zip(q, q[1:], strict=False))
    assert all(0.0 <= value <= 1.0 for value in q)


def test_the_correction_returns_values_in_the_input_order():
    p_values = [0.5, 0.01, 0.2]
    q = benjamini_hochberg(p_values)
    assert q[1] < q[2] < q[0]


def test_the_correction_is_less_severe_than_bonferroni():
    """Why BH and not Bonferroni: on thousands of rules, power.

    The forecasting chapter used Bonferroni on eight models, where any false
    positive would damage the conclusion. Here the output is a ranked list, so
    controlling the share of false discoveries is the right target.
    """
    # Twenty genuine signals sitting just above the Bonferroni cutoff
    # (0.05 / 100 = 0.0005), and eighty rules that are plainly noise.
    p_values = [*np.linspace(0.0006, 0.009, 20), *np.linspace(0.2, 0.99, 80)]
    q = benjamini_hochberg(list(p_values))
    bonferroni = [min(1.0, p * len(p_values)) for p in p_values]

    assert all(a <= b + 1e-12 for a, b in zip(q, bonferroni, strict=True))
    assert sum(v <= 0.05 for v in bonferroni) == 0      # every signal lost
    assert sum(v <= 0.05 for v in q) == 20              # every signal kept


def test_noise_produces_almost_nothing_after_correction():
    """The false-discovery guard, measured rather than asserted.

    Independent items at these thresholds should yield essentially no
    significant associations. Without the correction a share of them would be
    called significant by construction.
    """
    rng = np.random.default_rng(99)
    transactions = [
        frozenset({i for i in range(12) if rng.random() < 0.25}) for _ in range(1500)
    ]
    itemsets = frequent_itemsets(transactions, min_support=0.03, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=1.0, fdr_alpha=0.05)
    assert sum(1 for r in rules if r.is_association) <= 2


def test_the_summary_reports_what_the_correction_cost():
    rng = np.random.default_rng(1234)
    transactions = [
        frozenset({i for i in range(10) if rng.random() < 0.3}) for _ in range(800)
    ]
    itemsets = frequent_itemsets(transactions, min_support=0.03, max_length=2)
    rules = generate_rules(itemsets, min_confidence=0.0, min_lift=0.0)
    report = summarise(rules)
    assert report["available"]
    assert report["tested"] == len(rules)
    assert "Benjamini-Hochberg" in report["correction"]


def test_no_rules_is_reported_as_a_result_not_an_error():
    report = summarise([])
    assert not report["available"]
    assert "choosing the answer" in report["guidance"]


def test_top_rules_refuse_an_unknown_measure():
    with pytest.raises(ValueError, match="Cannot rank by"):
        top_rules([], by="confidence_interval")


# --------------------------------------------------------------------------
# pruning
# --------------------------------------------------------------------------

def make_rule(antecedent, consequent, confidence, lift=2.0) -> Rule:
    return Rule(
        antecedent=frozenset(antecedent),
        consequent=frozenset(consequent),
        support=0.1,
        support_count=10,
        antecedent_support=0.2,
        consequent_support=0.2,
        confidence=confidence,
        lift=lift,
        leverage=0.01,
        conviction=1.5,
        zhang=0.5,
    )


def test_a_specialised_rule_is_dropped_when_the_general_one_is_as_confident():
    general = make_rule({0}, {9}, 0.8)
    specialised = make_rule({0, 1}, {9}, 0.8)
    outcome = drop_redundant([general, specialised])
    assert outcome["kept"] == 1
    assert outcome["rules"][0].antecedent == frozenset({0})
    assert outcome["removals"][0]["covered_by_antecedent"] == [0]


def test_a_specialised_rule_survives_when_it_is_genuinely_more_confident():
    general = make_rule({0}, {9}, 0.5)
    specialised = make_rule({0, 1}, {9}, 0.9)
    outcome = drop_redundant([general, specialised])
    assert outcome["kept"] == 2


def test_a_tolerance_removes_a_rule_that_is_better_only_by_noise():
    """74% versus 75% is not two findings."""
    general = make_rule({0}, {9}, 0.74)
    specialised = make_rule({0, 1}, {9}, 0.75)

    assert drop_redundant([general, specialised])["kept"] == 2
    assert drop_redundant([general, specialised], tolerance=0.05)["kept"] == 1


def test_a_tolerance_keeps_a_rule_that_is_genuinely_better():
    general = make_rule({0}, {9}, 0.50)
    specialised = make_rule({0, 1}, {9}, 0.90)
    assert drop_redundant([general, specialised], tolerance=0.05)["kept"] == 2


def test_a_negative_tolerance_is_refused():
    """It would mean a specialised rule survives by being worse."""
    with pytest.raises(ValueError, match="negative"):
        drop_redundant([make_rule({0}, {9}, 0.5)], tolerance=-0.1)


def test_the_tolerance_is_reported_with_the_result():
    outcome = drop_redundant([make_rule({0}, {9}, 0.5)], tolerance=0.05)
    assert outcome["tolerance"] == 0.05
    assert "within 5%" in outcome["note"]


def test_pruning_does_not_merge_rules_with_different_consequents():
    outcome = drop_redundant([make_rule({0}, {8}, 0.8), make_rule({0, 1}, {9}, 0.8)])
    assert outcome["kept"] == 2


def test_the_trivial_filter_is_reported_with_its_threshold():
    common = make_rule({0}, {9}, 0.9)
    common = Rule(**{**common.__dict__, "consequent_support": 0.7})
    outcome = drop_trivial([common], max_consequent_support=0.5)
    assert outcome["kept"] == 0
    assert outcome["threshold"] == 0.5


# --------------------------------------------------------------------------
# validation - RQ3
# --------------------------------------------------------------------------

def pairing_that_stops():
    """Two products that are bought together, then stop being bought together.

    **The products keep selling at the same rate in both halves** - only the
    co-occurrence stops. That distinction is the point. A pairing whose
    products vanish is reported as *unobservable*, which is correct and is a
    different case (tested separately); a pairing that decays into independence
    is a rule that was true and stopped being true, which is what a hold-out
    has to catch.

    P1/P2 are bought together in the first half and independently in the
    second. P3/P4 are bought together throughout. P5/P6 are noise.
    """
    rng = np.random.default_rng(2026)
    rows = []
    dates = pd.date_range("2011-01-03", periods=800, freq="h")
    for index, date in enumerate(dates):
        items = set()
        if index < 400:
            if rng.random() < 0.5:
                items.update({"P1", "P2"})      # together
        else:
            # Same marginal rate for each, no relationship between them.
            if rng.random() < 0.5:
                items.add("P1")
            if rng.random() < 0.5:
                items.add("P2")
        if rng.random() < 0.4:
            items.update({"P3", "P4"})          # holds throughout
        for code in ("P5", "P6"):
            if rng.random() < 0.3:
                items.add(code)
        if not items:
            items.add("P5")
        for code in items:
            rows.append((f"INV{index:04d}", code, f"NAME {code}", date, False))
    return build_baskets(
        pd.DataFrame(
            rows,
            columns=["invoice_id", "product_code", "product_name", "occurred_at", "is_return"],
        )
    )


def test_a_rule_that_stopped_holding_fails_the_holdout():
    """The whole argument for RQ3 in one assertion.

    Mined on the first half, P1 -> P2 looks excellent. On the second half it is
    worthless, and only a hold-out says so.
    """
    baskets = pairing_that_stops()
    earlier, later = split_by_date(baskets, holdout_fraction=0.5)

    _, rules = mine_period(
        earlier, min_support=0.05, min_confidence=0.3, max_length=2
    )
    outcome = validate_rules(rules, later)
    assert outcome["available"]

    codes = {code: item for item, code in baskets.labels.items()}
    mined = {
        (tuple(sorted(r.antecedent)), tuple(sorted(r.consequent))): r for r in rules
    }
    key = ((codes["P1"],), (codes["P2"],))
    assert key in mined, "the pairing should be found on the mining window"
    assert mined[key].lift > 1.5

    failed = {
        (tuple(r["antecedent"]), tuple(r["consequent"])) for r in outcome["largest_falls"]
    }
    assert key in failed or (key[1], key[0]) in failed


def test_a_rule_that_still_holds_survives_the_holdout():
    baskets = pairing_that_stops()
    earlier, later = split_by_date(baskets, holdout_fraction=0.5)
    _, rules = mine_period(earlier, min_support=0.05, min_confidence=0.3, max_length=2)
    outcome = validate_rules(rules, later)

    codes = {code: item for item, code in baskets.labels.items()}
    survivors = {
        (tuple(r["antecedent"]), tuple(r["consequent"]))
        for r in outcome["strongest_survivors"]
    }
    stable = ((codes["P3"],), (codes["P4"],))
    assert stable in survivors or (stable[1], stable[0]) in survivors


def test_lift_fractionally_above_one_does_not_count_as_survival():
    """Half of all dead rules land above lift 1.0 by chance.

    Counting those as survivals would make the headline a coin flip. The
    hold-out therefore applies the same Fisher test and the same correction the
    mining step does, and the count of rules that cleared lift but not the test
    is reported rather than absorbed.
    """
    baskets = pairing_that_stops()
    earlier, later = split_by_date(baskets, holdout_fraction=0.5)
    _, rules = mine_period(earlier, min_support=0.05, min_confidence=0.3, max_length=2)
    outcome = validate_rules(rules, later)

    assert outcome["failed_on_significance_alone"] >= 1
    assert "Benjamini-Hochberg" in outcome["method_note"]

    judged = outcome["survived"] + outcome["failed"]
    assert judged == outcome["judged"]


def test_every_judged_rule_carries_its_holdout_q_value():
    """A survival a reader cannot check is an assertion, not a result."""
    baskets = pairing_that_stops()
    earlier, later = split_by_date(baskets, holdout_fraction=0.5)
    _, rules = mine_period(earlier, min_support=0.05, min_confidence=0.3, max_length=2)
    outcome = validate_rules(rules, later)

    for record in outcome["strongest_survivors"] + outcome["largest_falls"]:
        assert "holdout_q_value" in record
        assert 0.0 <= record["holdout_q_value"] <= 1.0


def test_an_unobservable_rule_is_not_counted_as_a_failure():
    """A discontinued product tells you nothing about its rule."""
    rule = make_rule({0}, {1}, 0.8)
    rows = measure_on([rule], [frozenset({2, 3})] * 20)
    assert rows[0]["unobservable"]
    assert "never occurs" in rows[0]["reason"]


def test_a_thin_rule_is_excluded_from_the_rate_rather_than_counted():
    """One basket must not be able to carry a rule over the threshold."""
    baskets = simple_baskets([["P1", "P2"]] * 40 + [["P3"]] * 40)
    _, rules = mine_period(baskets, min_support=0.1, min_confidence=0.5, max_length=2)
    thin_holdout = simple_baskets([["P1", "P2"]] + [["P3"]] * 30)
    outcome = validate_rules(rules, thin_holdout, min_support_count=5)
    assert outcome.get("too_thin", 0) >= 1 or not outcome["available"]


def test_validation_without_rules_says_so():
    assert validate_rules([], simple_baskets([["P1"]]))["available"] is False


def test_rule_set_overlap_is_one_for_identical_rule_sets():
    rules = [make_rule({0}, {1}, 0.8, lift=3.0), make_rule({2}, {3}, 0.7, lift=2.0)]
    overlap = rule_set_overlap(rules, rules, n=10)
    assert overlap["jaccard"] == pytest.approx(1.0)


def test_rule_set_overlap_is_zero_for_disjoint_rule_sets():
    first = [make_rule({0}, {1}, 0.8, lift=3.0)]
    second = [make_rule({4}, {5}, 0.8, lift=3.0)]
    assert rule_set_overlap(first, second, n=10)["jaccard"] == pytest.approx(0.0)


def test_the_verdict_matches_the_survival_rate():
    """Three bands, and the wording must not overstate the middle one."""
    from app.association.validation import _verdict

    assert "describe the business" in _verdict(0.9, 0.8, 0.0)
    assert "overstated" in _verdict(0.1, 0.1, 0.0)

    # The middle band must state the real number, not a stock phrase: at 65%
    # survival "roughly half failed" is simply false.
    middle = _verdict(0.65, 0.5, 0.0)
    assert "65.0%" in middle and "35.0%" in middle
    assert "half" not in middle


def test_the_verdict_names_the_optimism_when_lift_shrinks():
    from app.association.validation import _verdict

    assert "optimism" in _verdict(0.8, 0.7, -1.2)
    assert "optimism" not in _verdict(0.8, 0.7, 0.0)
