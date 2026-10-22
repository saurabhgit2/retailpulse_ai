"""Procedural fairness of the recommendations, after Wang et al. (2026).

Wang, Z., Huang, C., Tang, K., & Yao, X. (2026). Procedural fairness in machine
learning. *Journal of Artificial Intelligence Research*, 85, Article 20.

**This module exists because reading that paper showed an earlier claim in this
project to be wrong.** The proposal stated that the platform addresses
procedural fairness by surfacing which features drive each assignment. Wang et
al. examine exactly that position, attribute it to Grgić-Hlača et al. (2018),
and reject it: that definition "solely perceives the procedural fairness of the
ML model based on the fairness of the features actually used", and they argue
it "does not accurately capture the key essence of procedural fairness"
(§1, §2.2). Listing the features behind a decision is a transparency property.
It is not what they mean by procedural fairness.

What they mean is stated in their Definitions 1 to 3:

> Definition 1. The procedural fairness of the ML model is defined as the
> internal decision process or logic of the model without any prejudice or
> preference for individuals or groups due to their inherent or acquired
> characteristics.

> Definition 2 (individual). Two similar data points should have similar
> decision processes: d_Phi(Phi(x_i), Phi(x_j)) ~ 0 subject to
> d_x(x_i, x_j) ~ 0.

> Definition 3 (group). Similar data points in two groups should have similar
> decision processes or logic.

Their measurement, GPF_FAE in their Equation 7, portrays decision logic as a
feature attribution explanation and compares the distribution of explanations
between matched pairs from two groups, using maximum mean discrepancy with an
exponential kernel and a permutation test. Their Equation 9 then identifies the
*unfair features* responsible, as those whose per-feature explanation
distributions differ beyond a threshold.

**How this module departs from them, and why.** GPF_FAE compares distributions
of attribution values over hundreds or thousands of matched individuals. This
layer emits on the order of ten recommendations, so a permutation test over
attribution values has nothing to work with and would return a p-value that
means nothing. Implemented here instead is their *definition* at the level this
artefact operates on: for decisions of the same kind, does the decision logic
differ, measured as the distance between the sets of features actually driving
each one? Their Equation 9 becomes the identification of which features appear
in some decisions of a kind and not others.

Report it as an instantiation of their Definition 3 with a set-based distance
substituted for MMD on the grounds of sample size, not as GPF_FAE itself. The
substitution is a weakening and the chapter should say so.

**Where the distributive half lives.** Wang et al. separate procedural fairness
from distributive fairness, which concerns outcomes rather than process. The
distributive question for this platform - whether segmentation sends better
offers to some customers than others - is answered by the segment profiles and
the hazard metrics in `app.association.hazards`, not here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from app.insights.explanation import drivers
from app.insights.recommendations import Recommendation

# Wang et al. set their threshold beta to 0.05 for a p-value (§4.1). A set
# distance is not a p-value, so a value cannot be borrowed from them. This
# threshold is declared here before the first run: decisions of the same kind
# whose driver sets differ by more than a third are treated as inconsistent.
DIVERGENCE_THRESHOLD = 0.34

# Comparing one decision against itself says nothing, so a kind needs at least
# this many instances before consistency can be assessed.
MIN_INSTANCES = 2


@dataclass(frozen=True)
class Consistency:
    """How alike the decision logic is across decisions of one kind."""

    template: str
    instances: int
    mean_distance: float
    consistent: bool
    shared_features: list[str]
    divergent_features: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "instances": self.instances,
            "mean_driver_distance": round(self.mean_distance, 3),
            "consistent": self.consistent,
            "shared_features": self.shared_features,
            "divergent_features": self.divergent_features,
        }


def _driver_features(recommendation: Recommendation) -> set[str]:
    """The decision logic of one recommendation, as the features behind it."""
    return {f"{d['source']}.{d['feature']}" for d in drivers(recommendation)}


def _jaccard_distance(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return 1.0 - len(left & right) / len(union)


def consistency_by_template(
    recommendations: list[Recommendation],
    *,
    threshold: float = DIVERGENCE_THRESHOLD,
) -> list[Consistency]:
    """Wang et al.'s Definition 3, applied within each kind of decision.

    Two recommendations produced by the same template are the closest thing
    this artefact has to "similar data points": they concern the same kind of
    subject and answer the same question. If one is driven by revenue share and
    recency while another of the same kind is driven by something else, the
    decision logic is not consistent across them.

    Their Equation 9 identifies the features responsible, and the same idea
    applies here: a feature present in some instances of a kind and absent from
    others is where the inconsistency sits.
    """
    grouped: dict[str, list[Recommendation]] = {}
    for rec in recommendations:
        grouped.setdefault(rec.template, []).append(rec)

    out: list[Consistency] = []
    for template, members in sorted(grouped.items()):
        if len(members) < MIN_INSTANCES:
            continue
        feature_sets = [_driver_features(m) for m in members]
        distances = [
            _jaccard_distance(a, b) for a, b in combinations(feature_sets, 2)
        ]
        mean_distance = sum(distances) / len(distances) if distances else 0.0

        counts = Counter(f for fs in feature_sets for f in fs)
        shared = sorted(f for f, n in counts.items() if n == len(members))
        divergent = sorted(f for f, n in counts.items() if n < len(members))

        out.append(Consistency(
            template=template,
            instances=len(members),
            mean_distance=mean_distance,
            consistent=mean_distance <= threshold,
            shared_features=shared,
            divergent_features=divergent,
        ))
    return out


def assess(
    recommendations: list[Recommendation],
    *,
    threshold: float = DIVERGENCE_THRESHOLD,
) -> dict[str, Any]:
    """The procedural fairness report that accompanies a recommendation set."""
    scored = consistency_by_template(recommendations, threshold=threshold)
    if not scored:
        return {
            "available": False,
            "reason": (
                "No kind of decision occurred more than once, so there is no pair "
                "of comparable decisions whose logic could be compared."
            ),
            "source": "Wang, Huang, Tang & Yao (2026), Definitions 1-3.",
        }

    inconsistent = [c for c in scored if not c.consistent]
    worst = max(scored, key=lambda c: c.mean_distance)

    return {
        "available": True,
        "source": (
            "Wang, Huang, Tang & Yao (2026), Journal of Artificial Intelligence "
            "Research 85, Article 20, Definitions 1-3 and Equation 9."
        ),
        "threshold": threshold,
        "templates_assessed": len(scored),
        "templates_inconsistent": len(inconsistent),
        "rows": [c.as_dict() for c in scored],
        "worst_template": worst.template,
        "verdict": (
            f"Decisions of the same kind are driven by consistent evidence "
            f"across all {len(scored)} templates assessed; the widest divergence "
            f"is {worst.mean_distance:.2f} on {worst.template}, within the "
            f"declared threshold of {threshold}."
            if not inconsistent else
            f"{len(inconsistent)} of {len(scored)} templates give decisions of "
            f"the same kind materially different reasoning. The widest is "
            f"{worst.template} at {worst.mean_distance:.2f}, where "
            f"{', '.join(worst.divergent_features) or 'no feature'} appears in "
            f"some instances and not others."
        ),
        "method_note": (
            "An instantiation of their Definition 3 at the level of decision "
            "kinds, using the distance between driving-feature sets in place of "
            "maximum mean discrepancy over attribution values with a permutation "
            "test. Their measurement compares hundreds of matched individuals; "
            "this layer emits on the order of ten decisions, where a permutation "
            "test would return a p-value with nothing behind it. The substitution "
            "is a weakening and should be reported as one."
        ),
        "scope_note": (
            "Procedural fairness concerns the decision process. The distributive "
            "question, whether some customers receive materially better offers "
            "than others, is answered by the segment profiles and by the "
            "recommender hazard metrics, not here."
        ),
    }


def correction_note() -> str:
    """The claim this module corrects, kept with the code that corrects it."""
    return (
        "Assessment One stated that the platform addresses procedural fairness "
        "by exposing which features drive each assignment. Wang et al. (2026) "
        "attribute that position to Grgic-Hlaca et al. (2018) and argue it does "
        "not capture the essence of procedural fairness, which they define over "
        "the consistency of the decision process between similar cases rather "
        "than over the identity of the features used. Exposing the drivers is a "
        "transparency property and is reported as one; procedural fairness is "
        "assessed separately here."
    )
