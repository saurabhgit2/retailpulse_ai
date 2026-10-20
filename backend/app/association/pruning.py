"""Most mined rules are restatements of other mined rules. This removes them.

Mining is generous. If "tea -> mug" holds, then "tea + sugar -> mug",
"tea + spoon -> mug" and "tea + sugar + spoon -> mug" will usually hold too,
at similar confidence, because the extra conditions are doing no work. All four
appear in the output, three of them say nothing the first does not, and a
results table full of them looks like forty findings when there is one.

**The rule used here.** A rule is redundant when a *more general* rule - same
consequent, a subset of the antecedent - is at least as confident. The general
rule applies to more baskets and asks for less, so if it is as reliable, the
extra conditions are decoration. This is the standard notion of a minimal
non-redundant rule set.

**What this is not.** It is not a quality filter and it does not touch lift,
support or significance. A redundant rule is a true statement; it is simply
one already made. Every removal is returned with the rule that displaced it,
so the pruning can be checked rather than trusted.

**A caveat worth stating in the chapter.** Equal confidence is treated as
redundant, so where a specialised rule exactly ties its general form, the
general one wins. That is the conservative direction - it reports the weaker
claim - but it does mean the count of distinct rules is a lower bound.
"""

from __future__ import annotations

from typing import Any

from app.association.rules import Rule

# Confidence is a ratio of integer counts, so exact ties are common and
# meaningful; this tolerance only absorbs floating-point representation error.
TIE = 1e-9


def drop_redundant(rules: list[Rule], *, tolerance: float = 0.0) -> dict[str, Any]:
    """Keep only rules no more general rule already covers.

    `tolerance` is how much *better* a specialised rule must be to earn its
    place. At the default 0.0 a specialised rule survives on any improvement at
    all, including one percentage point of sampling noise - which is how a
    results table ends up with "A -> C" at 74% and "A + B -> C" at 75% side by
    side, reported as two findings when the second item is doing nothing.

    Set it to, say, 0.05 and a specialised rule must beat its general form by
    five points of confidence. That is a real methodological choice and it
    belongs in the config, declared before the run, not adjusted afterwards
    until the table looks tidy.

    Returns the kept rules and, for each removal, the rule that displaced it -
    the audit trail that makes this checkable.
    """
    if tolerance < 0:
        raise ValueError(f"tolerance cannot be negative; got {tolerance}.")
    by_consequent: dict[frozenset[int], list[Rule]] = {}
    for rule in rules:
        by_consequent.setdefault(rule.consequent, []).append(rule)

    kept: list[Rule] = []
    removed: list[dict[str, Any]] = []

    for consequent, group in by_consequent.items():
        # Shortest antecedents first: a rule can only be displaced by a more
        # general one, so generality is decided before it is needed.
        group.sort(key=lambda rule: (len(rule.antecedent), -rule.confidence))
        survivors: list[Rule] = []

        for rule in group:
            dominator = next(
                (
                    other for other in survivors
                    if other.antecedent < rule.antecedent
                    and other.confidence >= rule.confidence - tolerance - TIE
                ),
                None,
            )
            if dominator is None:
                survivors.append(rule)
                continue
            removed.append({
                "antecedent": sorted(rule.antecedent),
                "consequent": sorted(consequent),
                "confidence": rule.confidence,
                "covered_by_antecedent": sorted(dominator.antecedent),
                "covered_by_confidence": dominator.confidence,
            })

        kept.extend(survivors)

    kept.sort(key=lambda rule: (-rule.lift, -rule.support))
    margin = (
        f"no less confidence" if tolerance == 0
        else f"within {tolerance:.0%} of the same confidence"
    )
    return {
        "rules": kept,
        "kept": len(kept),
        "removed": len(removed),
        "tolerance": tolerance,
        "removals": removed[:200],
        "note": (
            f"{len(removed):,} of {len(rules):,} rules were restatements of a more "
            f"general rule with the same consequent and {margin}. They are true "
            f"but add nothing, and leaving them in would make one finding look "
            f"like several."
        ),
    }


def drop_trivial(rules: list[Rule], *, max_consequent_support: float = 0.5) -> dict[str, Any]:
    """Remove rules whose consequent is so common the rule says little.

    An item in more than half of all baskets will reach high confidence behind
    almost any antecedent. Lift already corrects for this - such a rule lands
    near 1.0 and `is_association` rejects it - so this is a second, blunter
    guard, and it is **off by default in the runner**.

    It is here because the opposite mistake is common enough to be worth a
    named function: a reader who sees a rule with a near-universal consequent
    in a results table assumes it was overlooked. Using it means saying so;
    leaving it off and relying on lift is equally defensible and keeps the
    output honest about what mining produced.
    """
    kept = [r for r in rules if r.consequent_support <= max_consequent_support]
    return {
        "rules": kept,
        "kept": len(kept),
        "removed": len(rules) - len(kept),
        "threshold": max_consequent_support,
        "note": (
            f"Removed {len(rules) - len(kept):,} rules whose consequent appears in "
            f"more than {max_consequent_support:.0%} of baskets. Lift already "
            f"places such rules near independence; this is a blunter second guard "
            f"and using it is a reportable choice."
        ),
    }
