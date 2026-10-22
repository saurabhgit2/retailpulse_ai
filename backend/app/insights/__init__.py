"""The insight layer: three engines' output reconciled into ranked advice.

Assessment One called this layer the substantive novelty of the project, and
RQ4 asks whether it earns that description. The pipeline, in the order the
modules run:

    reliability     how far each engine's output deserves to be believed,
                    computed from that engine's own out-of-sample evidence
    signals         three result files reduced to one comparable record type
    reconcile       signals grouped by subject; corroboration and conflict
    recommendations typed actions with evidence and caveats attached
    ranking         priority from revenue, evidence weight and corroboration
    explanation     plain-language rendering and the transparency index
    fairness        procedural fairness of the decisions, after Wang et al.
    baseline        the same analyses presented separately - the RQ4 control

Like `app.forecasting`, `app.segmentation` and `app.association`, this package
is pure: pandas, numpy and scipy only, no FastAPI, no SQLAlchemy, no session.
It is given the result dictionaries the three research runners produce and
returns dictionaries. The purity check in the test suite enforces that.

**Two honest constraints are built into the design rather than papered over.**

The forecasting experiment currently targets total weekly revenue, so it emits
no product-level signal and cannot corroborate a product pairing. Signals carry
their scope, business-scope signals attach to other findings as context, and
every recommendation records which engines were silent about its subject.

Margin and inventory data do not exist in Online Retail II, so the ranking uses
revenue at stake, measured engine reliability and corroboration in place of the
composite actionability score Assessment One proposed.

**This file imports nothing**, for the reason given in `app.association`: a
package whose `__init__` imports its own modules cannot be committed until the
last of them exists. Import from the module you need.
"""
