"""Reliability propagation, reconciliation, ranking and the RQ4 control condition.

The test this file exists for is `test_the_baseline_withholds_nothing_from_the_reader`.
RQ4 compares an integrated presentation against an isolated one, and the result
is worthless if the control was quietly made worse than the thing it stands
for. That test asserts every statement in the integrated condition is also
available in the baseline.

The second most important is `test_weak_evidence_reaches_the_recommendation`.
The project measured segment instability and interval under-coverage; if those
measurements do not survive into the advice, the insight layer is presenting
unreliable findings with the same authority as reliable ones, which is the
failure it was built to prevent.
"""

from __future__ import annotations

import pytest

from app.insights import baseline as baseline_module
from app.insights import explanation, ranking, reconcile, reliability, signals
from app.insights.recommendations import build, deduplicate
from app.insights.signals import Scope


# --------------------------------------------------------------------------
# fixtures shaped like the real runner output
# --------------------------------------------------------------------------

def forecast_run(*, wape=14.8, nominal=0.8, observed=0.25, scored=True):
    return {
        "selection": {"selected_model": "seasonal_naive" if scored else "combination_median"},
        "holdout": [
            {"model": "seasonal_naive", "mean_wape": wape},
            {"model": "fourier", "mean_wape": wape + 9},
        ],
        "intervals": {
            "available": True,
            "model": "seasonal_naive",
            "level": 0.8,
            "point": [1000.0, 1100.0, 1200.0],
            "actual": [900.0, 950.0, 1000.0],
            "coverage": {"nominal": nominal, "observed": observed, "points": 12},
        },
    }


def segmentation_run(*, ari=0.221, retention=0.608):
    return {
        "stability": {
            "kmeans": {"mean_adjusted_rand": 0.392, "mean_retention_share": 0.718},
            "hierarchical": {"mean_adjusted_rand": 0.263, "mean_retention_share": 0.632},
            "gaussian": {"mean_adjusted_rand": ari, "mean_retention_share": retention},
        },
        "profiles": {
            "rows": [
                {"cluster": 0, "name": "recent, frequent, high value", "customers": 1650,
                 "customer_share": 0.28, "revenue_share": 0.817,
                 "median_recency_days": 21.0, "median_frequency": 8.0,
                 "median_monetary": 2400.0},
                {"cluster": 1, "name": "lapsed occasional", "customers": 1831,
                 "customer_share": 0.31, "revenue_share": 0.04,
                 "median_recency_days": 290.0, "median_frequency": 1.0,
                 "median_monetary": 180.0},
            ]
        },
        "migrations": {
            "w1 -> w2": {
                "available": True,
                "largest_flows": [
                    {"from": 0, "to": 1, "customers": 300, "share_of_source": 0.22},
                    {"from": 1, "to": 0, "customers": 40, "share_of_source": 0.02},
                ],
            }
        },
    }


def association_run(*, survival=1.0, correlation=0.95):
    return {
        "rules": [
            {"antecedent": ["POPPY'S PLAYHOUSE KITCHEN"],
             "consequent": ["POPPY'S PLAYHOUSE BEDROOM"],
             "antecedent_ids": [1], "consequent_ids": [2],
             "support": 0.01, "support_count": 414, "confidence": 0.777,
             "lift": 45.6, "normalised_lift": 0.960, "q_value": 1e-20,
             "is_association": True},
            {"antecedent": ["PINK REGENCY TEACUP AND SAUCER"],
             "consequent": ["GREEN REGENCY TEACUP AND SAUCER"],
             "antecedent_ids": [3], "consequent_ids": [4],
             "support": 0.012, "support_count": 478, "confidence": 0.916,
             "lift": 29.19, "normalised_lift": 0.959, "q_value": 1e-18,
             "is_association": True},
            {"antecedent": ["WEAK ITEM"], "consequent": ["OTHER"],
             "antecedent_ids": [5], "consequent_ids": [6],
             "support": 0.01, "support_count": 400, "confidence": 0.3,
             "lift": 1.2, "normalised_lift": 0.1, "q_value": 0.01,
             "is_association": True},
        ],
        "holdout_validation": {
            "available": True, "survival_rate": survival, "judged": 1100,
            "survived": int(1100 * survival), "failed": 1100 - int(1100 * survival),
            "lift_rank_correlation": correlation,
            "strongest_survivors": [
                {"antecedent": [1], "consequent": [2], "holdout_lift": 44.0},
            ],
        },
        "recommender_hazards": {
            "item_coverage": {"available": True, "catalogue_size": 4734,
                              "reachable": 187, "item_coverage": 0.0395},
            "new_item_coverage": {"available": True, "new_items": 319,
                                  "covered": 0, "coverage_new": 0.0},
        },
    }


def pipeline(fc=None, seg=None, assoc=None, *, total_revenue=1_000_000.0):
    fc = forecast_run() if fc is None else fc
    seg = segmentation_run() if seg is None else seg
    assoc = association_run() if assoc is None else assoc
    rels = reliability.assess(fc, seg, assoc)
    sigs = signals.collect(
        forecast=fc, segmentation=seg, association=assoc, reliabilities=rels
    )
    findings = reconcile.reconcile(sigs)
    recs = ranking.rank(deduplicate(build(findings, total_revenue=total_revenue)))
    return rels, sigs, findings, recs


# --------------------------------------------------------------------------
# architecture
# --------------------------------------------------------------------------

def test_the_insights_package_stays_pure():
    """Same contract the other three analytical packages are held to."""
    import ast
    from pathlib import Path

    banned = ("fastapi", "sqlalchemy", "pydantic", "starlette", "psycopg",
              "alembic", "app.db", "app.api", "app.services")
    package = Path(__file__).resolve().parents[2] / "app" / "insights"
    offences = []
    for path in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if any(module == b or module.startswith(b + ".") for b in banned):
                    offences.append(f"{path.name} imports {module}")
    assert not offences, "the pure core reached into the shell: " + "; ".join(offences)


# --------------------------------------------------------------------------
# reliability
# --------------------------------------------------------------------------

def test_interval_under_coverage_drags_forecast_reliability_down():
    """A good point forecast with dishonest intervals is not reliable evidence.

    The two components multiply. Averaging would let accuracy hide the fact
    that the stated range covered a quarter of what it promised.
    """
    honest = reliability.forecast_reliability(forecast_run(wape=14.8, observed=0.80))
    dishonest = reliability.forecast_reliability(forecast_run(wape=14.8, observed=0.25))

    assert honest.score > dishonest.score
    assert dishonest.score == 0.0           # shortfall exceeds the tolerance
    assert dishonest.band == "weak"
    assert "25%" in dishonest.basis


def test_a_wide_interval_is_not_penalised():
    """Conservative intervals cost money; narrow ones hide risk. Only the
    second is a reliability problem."""
    wide = reliability.forecast_reliability(forecast_run(observed=0.92))
    assert wide.evidence["interval_component"] == 1.0


def test_segmentation_reliability_takes_the_weakest_family():
    """Where k-means and a Gaussian mixture disagree, the higher number is not
    the safer one to carry into advice."""
    assessed = reliability.segmentation_reliability(segmentation_run())
    assert assessed.evidence["weakest_algorithm"] == "gaussian"
    assert assessed.score == pytest.approx(0.221)
    assert assessed.band == "weak"


def test_association_reliability_follows_holdout_survival():
    strong = reliability.association_reliability(association_run(survival=1.0))
    weak = reliability.association_reliability(association_run(survival=0.1))
    assert strong.score > weak.score
    assert strong.band == "strong"
    assert "100.0%" in strong.basis


def test_a_source_with_no_validation_scores_zero_not_a_neutral_default():
    """Assigning an unvalidated engine a middling score would let it borrow the
    authority of the validated ones."""
    unknown = reliability.unavailable("forecast", "nothing ran")
    assert unknown.score == 0.0
    assert unknown.band == "unknown"
    assert reliability.assess(None, None, None)["forecast"].score == 0.0


def test_the_three_scores_are_never_averaged_into_one():
    """They answer different questions, so a combined figure would describe
    nothing. The summary must report them separately."""
    summary = reliability.summarise(reliability.assess(
        forecast_run(), segmentation_run(), association_run()))
    assert len(summary["rows"]) == 3
    assert "deliberately not averaged" in summary["note"]
    assert "overall" not in summary


# --------------------------------------------------------------------------
# signals
# --------------------------------------------------------------------------

def test_the_forecast_speaks_at_business_scope_only():
    """The experiment targets __TOTAL__, so there is no product-level forecast
    and none is invented."""
    rels = reliability.assess(forecast_run(), None, None)
    produced = signals.from_forecast(forecast_run(), rels["forecast"])
    assert produced
    assert all(s.subject.scope is Scope.BUSINESS for s in produced)


def test_interval_under_coverage_becomes_its_own_adverse_signal():
    rels = reliability.assess(forecast_run(observed=0.25), None, None)
    produced = signals.from_forecast(forecast_run(observed=0.25), rels["forecast"])
    kinds = {s.kind for s in produced}
    assert "interval_understates_risk" in kinds
    assert next(s for s in produced if s.kind == "interval_understates_risk").direction == -1


def test_immaterial_segment_flows_are_not_signals():
    """A 2% boundary movement is ordinary churn, not an event."""
    rels = reliability.assess(None, segmentation_run(), None)
    produced = signals.from_segmentation(segmentation_run(), rels["segmentation"])
    flows = [s for s in produced if s.kind == "segment_outflow"]
    assert len(flows) == 1
    assert flows[0].magnitude == pytest.approx(0.22)


def test_weak_rules_produce_no_signal():
    rels = reliability.assess(None, None, association_run())
    produced = signals.from_association(association_run(), rels["association"])
    keys = {s.subject.key for s in produced}
    assert not any("WEAK ITEM" in k for k in keys)


def test_a_rule_confirmed_on_the_holdout_is_marked_as_such():
    rels = reliability.assess(None, None, association_run())
    produced = signals.from_association(association_run(), rels["association"])
    durable = [s for s in produced if s.kind == "durable_pairing"]
    assert durable and durable[0].evidence["held_on_holdout"] is True


def test_catalogue_blind_spots_are_reported_as_signals():
    rels = reliability.assess(None, None, association_run())
    kinds = {s.kind for s in signals.from_association(association_run(), rels["association"])}
    assert "catalogue_blind_spot" in kinds
    assert "new_product_blind_spot" in kinds


# --------------------------------------------------------------------------
# reconciliation
# --------------------------------------------------------------------------

def test_context_does_not_count_as_corroboration():
    """A business forecast attached to a segment finding is background, not a
    second engine agreeing about that segment. Conflating them would overstate
    the integration this project claims."""
    _, _, findings, _ = pipeline()
    segment = next(f for f in findings if f.subject.scope is Scope.SEGMENT)
    assert segment.context                      # context is attached
    assert segment.sources == ["segmentation"]  # and is not counted
    assert not segment.corroborated


def test_conflicting_directions_are_reported_rather_than_resolved():
    _, _, findings, _ = pipeline()
    concentrated = next(
        f for f in findings
        if f.subject.scope is Scope.SEGMENT and f.subject.key == "0"
    )
    # Cluster 0 is both revenue-concentrated (favourable) and draining (adverse).
    assert concentrated.conflicts
    assert concentrated.conflicts[0]["kind"] == "within_source"


def test_the_integration_report_states_how_much_corroboration_was_possible():
    """The number RQ4 turns on, reported rather than asserted."""
    _, sigs, findings, _ = pipeline()
    report = reconcile.integration_report(findings, sigs)
    assert report["findings"] == len(findings)
    assert "business" in report["scopes_with_multiple_sources"]
    assert "cannot corroborate a product pairing" in report["limitation"]


def test_evidence_weight_takes_the_strongest_source_not_the_mean():
    """Extra information from a weaker engine must not lower a finding's
    standing below what the stronger engine alone would give it."""
    _, _, findings, _ = pipeline()
    business = next(
        f for f in findings
        if f.subject.key == "__TOTAL__"
    )
    weights = [s.weight for s in business.signals]
    assert business.evidence_weight == pytest.approx(max(weights))


# --------------------------------------------------------------------------
# recommendations
# --------------------------------------------------------------------------

def test_weak_evidence_reaches_the_recommendation():
    """The point of the layer. Segment instability was measured at 0.221, and
    any recommendation resting on segments must say so before its action."""
    *_, recs = pipeline()
    segment_recs = [r for r in recs if r.subject["scope"] == "segment"]
    assert segment_recs
    for rec in segment_recs:
        assert any("segmentation is weak" in c for c in rec.caveats)


def test_every_recommendation_names_the_engines_that_were_silent():
    """A reader who cannot distinguish agreement from absence is being given
    false assurance."""
    *_, recs = pipeline()
    for rec in recs:
        assert set(rec.sources).isdisjoint(rec.silent_sources)
        assert set(rec.sources) | set(rec.silent_sources) == {
            "forecast", "segmentation", "association"
        }


def test_every_recommendation_carries_an_action_and_evidence():
    *_, recs = pipeline()
    assert recs
    for rec in recs:
        assert rec.action.strip()
        assert rec.rationale.strip()
        assert rec.has_evidence


def test_a_thinly_concentrated_segment_produces_no_recommendation():
    """Advice about a segment holding revenue in proportion to its size would
    tell a manager nothing."""
    run = segmentation_run()
    run["profiles"]["rows"][0]["revenue_share"] = 0.29   # against 0.28 of customers
    rels = reliability.assess(None, run, None)
    sigs = signals.collect(forecast=None, segmentation=run, association=None,
                           reliabilities=rels)
    recs = build(reconcile.reconcile(sigs))
    assert not [r for r in recs if r.template == "protect_concentrated_revenue"]


def test_duplicate_recommendations_collapse_to_the_best_evidenced():
    *_, recs = pipeline()
    keys = [r.key for r in recs]
    assert len(keys) == len(set(keys))


def test_both_directions_of_a_pairing_make_one_shelving_recommendation():
    """A rule is directed; a shelf is not.

    Mining emits A -> B and B -> A separately, and both describe the same
    physical arrangement. A smoke run filled six of the top ten slots with the
    same three actions stated twice before this was keyed on the unordered set.
    """
    run = association_run()
    run["rules"].append({
        "antecedent": ["POPPY'S PLAYHOUSE BEDROOM"],
        "consequent": ["POPPY'S PLAYHOUSE KITCHEN"],
        "antecedent_ids": [2], "consequent_ids": [1],
        "support": 0.01, "support_count": 414, "confidence": 0.82,
        "lift": 45.6, "normalised_lift": 0.960, "q_value": 1e-20,
        "is_association": True,
    })
    rels = reliability.assess(None, None, run)
    sigs = signals.collect(forecast=None, segmentation=None, association=run,
                           reliabilities=rels)
    recs = deduplicate(build(reconcile.reconcile(sigs)))

    pairings = [r for r in recs if r.template == "stock_and_display_together"]
    playhouse = [r for r in pairings if "PLAYHOUSE" in r.key]
    assert len(playhouse) == 1


def test_an_unconfirmed_rule_says_so():
    run = association_run()
    run["holdout_validation"]["strongest_survivors"] = []
    rels = reliability.assess(None, None, run)
    sigs = signals.collect(forecast=None, segmentation=None, association=run,
                           reliabilities=rels)
    recs = build(reconcile.reconcile(sigs))
    pairings = [r for r in recs if r.template == "stock_and_display_together"]
    assert pairings
    assert any("not among those confirmed" in c for c in pairings[0].caveats)


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

def test_a_missing_weight_is_refused_rather_than_defaulted():
    """Omitting a component must be a visible decision in the configuration."""
    with pytest.raises(ranking.RankingError, match="Missing weight"):
        ranking.validate_weights({"revenue_at_stake": 1.0, "evidence_weight": 1.0})


def test_unknown_or_negative_weights_are_refused():
    with pytest.raises(ranking.RankingError, match="Unknown"):
        ranking.validate_weights({**ranking.DEFAULT_WEIGHTS, "margin": 0.5})
    with pytest.raises(ranking.RankingError, match="negative"):
        ranking.validate_weights({**ranking.DEFAULT_WEIGHTS, "evidence_weight": -1})


def test_weights_are_normalised_so_they_need_not_sum_to_one():
    normalised = ranking.validate_weights(
        {"revenue_at_stake": 2, "evidence_weight": 2, "corroboration": 1}
    )
    assert sum(normalised.values()) == pytest.approx(1.0)
    assert normalised["revenue_at_stake"] == pytest.approx(0.4)


def test_better_evidence_outranks_weaker_evidence_all_else_equal():
    *_, recs = pipeline()
    by_template = {r.template: r for r in recs}
    pairing = by_template["stock_and_display_together"]
    segment = by_template["protect_concentrated_revenue"]
    # Association validated at 100% survival; segmentation at ARI 0.221.
    assert pairing.evidence_weight > segment.evidence_weight


def test_the_ranking_records_its_own_components():
    """A priority a reader cannot decompose is a score, not an explanation."""
    *_, recs = pipeline()
    components = [
        item for item in recs[0].evidence if item.get("kind") == "priority_components"
    ]
    assert components
    assert set(components[0]["evidence"]["components"]) == set(ranking.DEFAULT_WEIGHTS)


def test_the_excluded_components_are_named():
    """Margin and inventory were proposed in Assessment One and are absent."""
    assert "neither product cost nor stock level" in ranking.explain_weights()["excluded"]


# --------------------------------------------------------------------------
# explanation
# --------------------------------------------------------------------------

def test_every_recommendation_names_at_least_one_driving_figure():
    """FR7, measured. The evaluation plan expects a transparency index of 1.0."""
    *_, recs = pipeline()
    index = explanation.transparency_index(recs)
    assert index["transparency_index"] == 1.0
    assert index["templates_without_drivers"] == []


def test_drivers_are_labelled_rather_than_raw_keys():
    *_, recs = pipeline()
    named = explanation.drivers(recs[0])
    assert named
    assert all(d["label"] and d["label"] != d["feature"] for d in named)


def test_caveats_are_rendered_before_the_reasoning():
    """A reader who has already decided will not revise on reaching a footnote."""
    *_, recs = pipeline()
    weak = next(r for r in recs if r.caveats)
    text = explanation.render(weak)
    assert text.index("Before acting:") < text.index("Why:")


def test_the_transparency_index_reports_a_shortfall_rather_than_rounding_it_away():
    *_, recs = pipeline()
    recs[0].evidence = [{"source": "x", "kind": "y", "evidence": {}}]
    index = explanation.transparency_index(recs)
    assert index["transparency_index"] < 1.0
    assert index["templates_without_drivers"]


# --------------------------------------------------------------------------
# baseline - the RQ4 control
# --------------------------------------------------------------------------

def test_the_baseline_withholds_nothing_from_the_reader():
    """The control must be fair or RQ4 measures nothing.

    Every statement the integrated condition makes about an engine's output
    must also appear in that engine's own list. The difference between the two
    conditions is the join, not the content.
    """
    rels, sigs, _, recs = pipeline()
    control = baseline_module.isolated_presentation(sigs, rels, per_list=50)

    baseline_statements = {
        row["statement"] for rows in control["lists"].values() for row in rows
    }
    integrated_statements = {
        item["summary"]
        for rec in recs for item in rec.evidence if item.get("summary")
        and item.get("source") in {"forecast", "segmentation", "association"}
    }
    missing = integrated_statements - baseline_statements
    assert not missing, f"the control was starved of: {missing}"


def test_the_baseline_carries_the_same_reliability_evidence():
    """Withholding the reliability assessment from the control would make the
    integrated condition win on information rather than on presentation."""
    rels, sigs, _, _ = pipeline()
    control = baseline_module.isolated_presentation(sigs, rels)
    for source in ("forecast", "segmentation", "association"):
        assert control["reliability"][source]["basis"]


def test_the_baseline_states_what_it_structurally_cannot_do():
    rels, sigs, _, _ = pipeline()
    control = baseline_module.isolated_presentation(sigs, rels)
    limits = " ".join(control["structural_limits"])
    assert "cannot be ordered against one another" in limits
    assert "corroborated" in limits


def test_the_reconciliation_burden_is_counted_not_asserted():
    """How hard the reconciliation feels is what the sessions measure; the code
    reports counts and stops there."""
    rels, sigs, _, recs = pipeline()
    control = baseline_module.isolated_presentation(sigs, rels)
    burden = baseline_module.reconciliation_burden(recs, control)
    assert burden["cross_list_comparisons_required"] > 0
    assert "what the RQ4 sessions measure" in burden["note"]


# --------------------------------------------------------------------------
# the three decision-support papers
# --------------------------------------------------------------------------

def test_the_demand_action_states_a_range_not_a_point():
    """Eshov et al. (2025) Table 9 reports pessimistic, central and optimistic
    lending forecasts and recommends against the spread.

    A single central figure reads as settled, which is the wrong impression
    when the hold-out showed the intervals understate risk. The bounds come
    from the forecast's own interval output, so nothing is invented.
    """
    run = forecast_run()
    run["intervals"]["lower"] = [800.0, 850.0, 900.0]
    run["intervals"]["upper"] = [1200.0, 1350.0, 1500.0]
    rels = reliability.assess(run, None, None)
    sigs = signals.collect(forecast=run, segmentation=None, association=None,
                           reliabilities=rels)
    demand = next(s for s in sigs if s.kind == "demand_direction")
    assert set(demand.evidence["scenarios"]) == {"pessimistic", "central", "optimistic"}

    recs = build(reconcile.reconcile(sigs))
    action = next(r for r in recs if r.template == "plan_for_demand_direction").action
    assert "Plan against a range" in action


def test_a_forecast_without_bounds_still_produces_an_action():
    """The scenario triple is used where the bounds exist and the single-figure
    wording survives where they do not."""
    run = forecast_run()
    run["intervals"].pop("lower", None)
    rels = reliability.assess(run, None, None)
    sigs = signals.collect(forecast=run, segmentation=None, association=None,
                           reliabilities=rels)
    assert next(s for s in sigs if s.kind == "demand_direction").evidence["scenarios"] is None
    recs = build(reconcile.reconcile(sigs))
    assert next(r for r in recs if r.template == "plan_for_demand_direction").action


def test_procedural_fairness_compares_decision_logic_not_feature_identity():
    """Wang et al. (2026) Definition 3, instantiated per decision kind.

    Two recommendations of the same kind driven by different evidence have
    inconsistent decision logic. Exposing the features is transparency; this is
    the separate property, and the earlier project claim conflated them.
    """
    from app.insights import fairness

    *_, recs = pipeline()
    report = fairness.assess(recs)
    assert report["available"]
    assert "Wang, Huang, Tang & Yao (2026)" in report["source"]

    pairings = [c for c in report["rows"] if c["template"] == "stock_and_display_together"]
    assert pairings and pairings[0]["consistent"]
    assert "support_count" in " ".join(pairings[0]["shared_features"])


def test_divergent_features_are_named_as_in_their_equation_nine():
    """A feature present in some decisions of a kind and absent from others is
    where the inconsistency sits."""
    from app.insights import fairness

    run = association_run()
    # A rule with no adjusted p-value: same kind of decision, different evidence.
    run["rules"][1].pop("q_value")
    rels = reliability.assess(None, None, run)
    sigs = signals.collect(forecast=None, segmentation=None, association=run,
                           reliabilities=rels)
    recs = deduplicate(build(reconcile.reconcile(sigs)))
    report = fairness.assess(recs)

    pairing = next(c for c in report["rows"] if c["template"] == "stock_and_display_together")
    assert any("q_value" in f for f in pairing["divergent_features"])


def test_unlike_decisions_are_not_grouped_under_one_template():
    """A regression from the first run of the fairness check.

    A catalogue blind spot and a new-product blind spot shared one template
    name, and Wang et al.'s Definition 3 reported maximum divergence between
    them - correctly, because it was comparing decisions that were never
    alike. The check found a modelling error rather than a fairness problem,
    and the template was split.
    """
    from app.insights import fairness

    *_, recs = pipeline()
    templates = {r.template for r in recs}
    assert "cover_catalogue_blind_spot" in templates
    assert "cover_new_product_blind_spot" in templates
    assert "cover_the_blind_spot" not in templates

    report = fairness.assess(recs)
    assert report["templates_inconsistent"] == 0


def test_a_single_instance_cannot_be_assessed_for_consistency():
    """Comparing one decision against itself says nothing."""
    from app.insights import fairness

    rels = reliability.assess(forecast_run(), None, None)
    sigs = signals.collect(forecast=forecast_run(), segmentation=None,
                           association=None, reliabilities=rels)
    report = fairness.assess(build(reconcile.reconcile(sigs)))
    assert report["available"] is False
    assert "more than once" in report["reason"]


def test_the_module_records_the_claim_it_corrects():
    """The correction travels with the code that makes it, so the chapter
    cannot quietly keep the original wording."""
    from app.insights import fairness

    note = fairness.correction_note()
    assert "Grgic-Hlaca" in note
    assert "transparency property" in note


def test_the_method_note_admits_the_substitution_for_mmd():
    """Reporting a set distance as though it were GPF_FAE would overstate what
    was implemented."""
    from app.insights import fairness

    *_, recs = pipeline()
    note = fairness.assess(recs)["method_note"]
    assert "maximum mean discrepancy" in note
    assert "weakening" in note


def test_the_ranking_declares_itself_symmetric():
    """Jordan and Mitchell (2015) treat the performance measure as a choice that
    may penalise one error direction more than the other. Priority does not,
    and says so rather than implying a cost model it is not."""
    assert "asymmetric" in ranking.__doc__
    assert "attention-ordering measure, not a cost model" in ranking.__doc__


def test_both_session_packs_render():
    rels, sigs, _, recs = pipeline()
    control = baseline_module.isolated_presentation(sigs, rels)
    integrated_text = explanation.session_pack(recs, title="Condition A")
    control_text = baseline_module.session_pack(control, title="Condition B")
    assert "Condition A" in integrated_text and "Priority:" in integrated_text
    assert "Condition B" in control_text
    assert "Customer segmentation report" in control_text
