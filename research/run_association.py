"""Run the RQ3 association rule experiment and export its results.

    python research/run_association.py research/configs/rq3_association.toml

Same shape and same discipline as `run_experiment.py` and `run_segmentation.py`:
the protocol comes from a committed TOML file, the file's SHA-256 travels with
the results, the library versions are recorded, and `--dry-run` validates
everything and reports the basket profile without mining.

What it does, in order:

1. Pull invoice lines and build baskets, recording every construction decision.
2. Split chronologically - earlier baskets to mine on, later ones to test on.
3. Mine frequent itemsets on the earlier baskets with the declared thresholds.
4. Generate rules, test each one, correct for false discovery rate, and drop
   rules that restate a more general rule.
5. **Measure those rules, unchanged, on the hold-out.** This is RQ3.
6. Optionally mine the hold-out independently and compare the top-N lists,
   which asks a different question from survival.

**The thresholds are declared in the config, not tuned to the output.** Mining
with min_support lowered until interesting rules appear is choosing the answer.
If the declared thresholds return nothing, that is a finding about long-tail
retail and it is reported as one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.association.baskets import (  # noqa: E402
    build_baskets,
    compare_singleton_policies,
    split_by_date,
)
from app.association.colocation import affinity_graph, evaluate_layout  # noqa: E402
from app.association.hazards import hazard_report  # noqa: E402
from app.association.itemsets import frequent_itemsets, top_itemsets  # noqa: E402
from app.association.pruning import drop_redundant, drop_trivial  # noqa: E402
from app.association.rules import generate_rules, summarise, top_rules  # noqa: E402
from app.association.validation import (  # noqa: E402
    mine_period,
    rule_set_overlap,
    validate_rules,
)


class ConfigError(ValueError):
    """The config is wrong. Raised before anything expensive happens."""


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        config = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error
    validate_config(config)
    return config, hashlib.sha256(raw).hexdigest()


def validate_config(config: dict[str, Any]) -> None:
    """Report every problem at once; one per run wastes a cycle each time."""
    problems: list[str] = []

    for section in ("meta", "data", "mining", "validation"):
        if section not in config:
            problems.append(f"Missing [{section}] section.")
    if problems:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(problems))

    if config["data"].get("source") not in ("database",):
        problems.append(
            "data.source must be 'database'. Baskets depend on the pipeline's "
            "cleaning rules - which codes are products, which lines are returns "
            "- so there is no CSV shortcut that would give the same answer."
        )

    mining = config["mining"]
    support = float(mining.get("min_support", 0))
    if not 0 < support <= 1:
        problems.append(f"mining.min_support must be in (0, 1]; got {support}.")
    elif support > 0.2:
        problems.append(
            f"mining.min_support is {support:.0%}. On long-tail retail data "
            f"nothing will reach that, and the run will report no rules. If "
            f"that is the intended experiment, say so in meta.description."
        )

    confidence = float(mining.get("min_confidence", 0))
    if not 0 <= confidence <= 1:
        problems.append(f"mining.min_confidence must be in [0, 1]; got {confidence}.")

    if int(mining.get("max_length", 0)) < 2:
        problems.append(
            "mining.max_length must be at least 2; a rule needs an antecedent "
            "and a consequent."
        )

    fraction = float(config["validation"].get("holdout_fraction", 0))
    if not 0 < fraction < 1:
        problems.append(
            f"validation.holdout_fraction must be between 0 and 1; got {fraction}."
        )
    elif fraction > 0.5:
        problems.append(
            f"validation.holdout_fraction is {fraction:.0%}, leaving less data to "
            f"mine on than to test on. The rules would be weak for reasons that "
            f"have nothing to do with whether they generalise."
        )

    if problems:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(problems))


def environment() -> dict[str, str]:
    import platform

    import numpy
    import scipy

    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
    }


def load_dataset(config: dict[str, Any]):
    """The dataset to mine, and a warning if it was not named explicitly."""
    from sqlalchemy import select

    from app.db.models.dataset import Dataset
    from app.db.session import SessionFactory

    session = SessionFactory()
    try:
        declared = (config["data"].get("dataset_id") or "").strip()
        if declared:
            dataset = session.get(Dataset, uuid.UUID(declared))
            if dataset is None:
                raise ConfigError(f"No dataset with id {declared}.")
        else:
            dataset = session.execute(
                select(Dataset).where(Dataset.status == "ready")
                .order_by(Dataset.processed_at.desc()).limit(1)
            ).scalar_one_or_none()
            if dataset is None:
                raise ConfigError("No processed dataset found. Set data.dataset_id.")
            print(
                "  WARNING: data.dataset_id is empty, so the most recently processed\n"
                f"           dataset was used ({dataset.id}). Set it explicitly before\n"
                "           the run whose numbers you cite."
            )
        return dataset, session
    except Exception:
        session.close()
        raise


def fetch_lines(session, dataset, config: dict[str, Any]) -> pd.DataFrame:
    """Invoice lines for the whole dataset.

    One row per sale line - the heaviest query in the project, which is why the
    count is printed first and only five columns are selected.
    """
    from app.db.repositories.analytics import Filters
    from app.db.repositories.baskets import basket_line_count, basket_lines

    filters = Filters()
    count = basket_line_count(session, dataset.id, filters)
    print(f"\nlines to fetch: {count:,}")
    if count == 0:
        raise ConfigError(
            "No sale lines have both an invoice and a product. Basket analysis "
            "needs invoice_id and product_code, which the field guide lists as "
            "the two requirements for the association_rules capability."
        )
    return basket_lines(
        session, dataset.id, filters,
        include_returns=not bool(config.get("baskets", {}).get("drop_returns", True)),
    )


def run(config: dict[str, Any], digest: str, dry_run: bool) -> dict[str, Any] | int:
    meta = config.get("meta", {})
    print(f"\n{meta.get('name', 'association')}  ({meta.get('research_question', '?')})")
    print(f"config sha256: {digest}\n")
    print("environment:")
    for key, value in environment().items():
        print(f"  {key:<14} {value}")

    dataset, session = load_dataset(config)
    try:
        lines = fetch_lines(session, dataset, config)
        print(f"dataset: {dataset.name}")
    finally:
        session.close()

    settings = config.get("baskets", {})
    cap = int(settings.get("max_basket_size", 0) or 0)
    baskets = build_baskets(
        lines,
        item_key=settings.get("item_key", "product_code"),
        drop_returns=bool(settings.get("drop_returns", True)),
        exclude_non_product=bool(settings.get("exclude_non_product_codes", True)),
        min_basket_size=int(settings.get("min_basket_size", 1)),
        max_basket_size=cap or None,
    )

    profile = baskets.size_profile()
    if not profile.get("available"):
        print(f"\n{profile.get('reason')}")
        return 1

    print(f"\nbaskets: {profile['baskets']:,}   items: {profile['items']:,}")
    print(f"  median size {profile['median_size']:.0f}, "
          f"mean {profile['mean_size']:.1f}, max {profile['max_size']:,}")
    print(f"  single-item baskets: {profile['singletons']:,} "
          f"({profile['singleton_share']:.1%})")
    print(f"  baskets of {200:,}+ items: {profile['large_baskets']:,}")
    print(f"  pairs implied by all baskets: {profile['pairs_implied']:,}")
    for key, value in baskets.excluded.items():
        print(f"  excluded {key}: {value:,}")

    mining = config["mining"]
    minimum = int(round(float(mining["min_support"]) * baskets.n_transactions))
    print(f"\nmin_support {float(mining['min_support']):.1%} "
          f"= {minimum:,} baskets")

    if dry_run:
        print("\nDry run: nothing was mined and nothing was written.")
        for note in baskets.notes:
            print(f"  note: {note}")
        return 0

    return _analyse(config, baskets, dataset)


def _analyse(config: dict[str, Any], baskets, dataset) -> dict[str, Any]:
    mining = config["mining"]
    significance = config.get("significance", {})
    validation = config.get("validation", {})
    pruning = config.get("pruning", {})

    earlier, later = split_by_date(
        baskets, holdout_fraction=float(validation.get("holdout_fraction", 0.25))
    )
    print(f"\nsplit at {max(earlier.dates).date()}:")
    print(f"  mine on  {earlier.n_transactions:,} baskets "
          f"({min(earlier.dates).date()} to {max(earlier.dates).date()})")
    print(f"  test on  {later.n_transactions:,} baskets "
          f"({min(later.dates).date()} to {max(later.dates).date()})")

    itemsets = frequent_itemsets(
        earlier.transactions,
        min_support=float(mining["min_support"]),
        max_length=int(mining.get("max_length", 3)),
    )
    print(f"\nfrequent itemsets: {itemsets.total:,} "
          f"{ {k: len(v) for k, v in sorted(itemsets.by_length.items())} }")
    print(f"  candidates counted {itemsets.candidates_evaluated:,}, "
          f"pruned by closure {itemsets.pruned_by_closure:,}")
    if itemsets.stopped_early:
        print(f"  {itemsets.stopped_early}")
    for note in itemsets.notes:
        print(f"  {note}")

    if itemsets.total == 0:
        return _no_rules(config, baskets, earlier, later, itemsets, dataset)

    rules = generate_rules(
        itemsets,
        min_confidence=float(mining.get("min_confidence", 0.2)),
        min_lift=float(mining.get("min_lift", 1.0)),
        min_cross_support=float(mining.get("min_cross_support", 0.0)),
        max_consequent_length=int(mining.get("max_consequent_length", 1)),
        test=bool(significance.get("enabled", True)),
        fdr_alpha=float(significance.get("alpha", 0.05)),
    )
    report = summarise(rules, alpha=float(significance.get("alpha", 0.05)))
    generated = len(rules)
    print(f"\nrules generated: {generated:,}")
    if report.get("available"):
        print(f"  {report['note']}")
        print(f"  associations (lift > 1 and significant): {report['associations']:,}")

    # Everything from here on works with the associations, not with every rule
    # that cleared the thresholds. A rule at lift 1.02 that failed its own
    # significance test is not something anyone would act on, and leaving such
    # rules in the denominator would make the survival rate a statement about
    # how much noise the thresholds admitted rather than about whether the
    # findings generalise. The full count is reported above either way.
    rules = [rule for rule in rules if rule.is_association]
    print(f"  carried forward for validation: {len(rules):,}")

    removals: dict[str, Any] = {}
    if pruning.get("drop_redundant", True) and rules:
        outcome = drop_redundant(
            rules, tolerance=float(pruning.get("redundancy_tolerance", 0.0))
        )
        removals["redundant"] = {k: v for k, v in outcome.items() if k != "rules"}
        rules = outcome["rules"]
        print(f"  {outcome['note']}")

    if pruning.get("drop_trivial", False) and rules:
        outcome = drop_trivial(
            rules, max_consequent_support=float(pruning.get("max_consequent_support", 0.5))
        )
        removals["trivial"] = {k: v for k, v in outcome.items() if k != "rules"}
        rules = outcome["rules"]
        print(f"  {outcome['note']}")

    # --- RQ3: do they hold on baskets they were not mined on? --------------
    held = validate_rules(
        rules, later,
        min_lift=float(mining.get("min_lift", 1.0)),
        min_support_count=int(validation.get("min_support_count", 5)),
        alpha=float(significance.get("alpha", 0.05)),
    )
    print("\nhold-out validation:")
    if held.get("available"):
        print(f"  judged {held['judged']:,} rules "
              f"({held['unobservable']:,} unobservable, {held['too_thin']:,} too thin)")
        print(f"  survived {held['survived']:,}, failed {held['failed']:,} "
              f"-> {held['survival_rate']:.1%}")
        print(f"  median lift {held['median_lift_mined']:.2f} mined "
              f"-> {held['median_lift_holdout']:.2f} held out")
        print(f"\n  {held['verdict']}")
    else:
        print(f"  {held.get('reason')}")

    overlap: dict[str, Any] = {"available": False, "reason": "not requested"}
    if validation.get("compare_rule_sets", True):
        _, independent = mine_period(
            later,
            min_support=float(mining["min_support"]),
            min_confidence=float(mining.get("min_confidence", 0.2)),
            max_length=int(mining.get("max_length", 3)),
            min_lift=float(mining.get("min_lift", 1.0)),
            fdr_alpha=float(significance.get("alpha", 0.05)),
        )
        overlap = rule_set_overlap(
            rules, independent, n=int(validation.get("top_n", 50))
        )
        if overlap.get("available"):
            print(f"\n  {overlap['note']}")

    strongest = top_rules(rules, by="normalised_lift", n=20)
    if strongest:
        print("\nstrongest associations (mining window, ranked by normalised lift):")
        for rule in strongest[:10]:
            left = " + ".join(baskets.describe(rule.antecedent))
            right = " + ".join(baskets.describe(rule.consequent))
            print(f"  Nlift {rule.normalised_lift:5.3f}  lift {rule.lift:7.2f}  "
                  f"conf {rule.confidence:5.1%}  n={rule.support_count:>5,}  "
                  f"{left[:30]:<30} -> {right[:30]}")

    # --- the four papers' own analyses -------------------------------------
    catalogue = sorted(baskets.labels)
    mined_items = set().union(*earlier.transactions) if earlier.transactions else set()
    holdout_items = set().union(*later.transactions) if later.transactions else set()
    new_in_holdout = sorted(holdout_items - mined_items)

    hazards = hazard_report(rules, catalogue, new_items=new_in_holdout)
    print("\nrecommender hazards (Kathriarachchi et al. 2026, section 4.2):")
    if hazards["item_coverage"].get("available"):
        print(f"  {hazards['item_coverage']['verdict']}")
    if hazards["new_item_coverage"].get("available"):
        print(f"  {hazards['new_item_coverage']['verdict']}")
    if hazards["exposure_concentration"].get("available"):
        print(f"  {hazards['exposure_concentration']['note']}")
    print(f"  transparency index 1.0 by construction; "
          f"{len(hazards['not_computable'])} of their metrics need data this "
          f"dataset does not carry (listed in run.json).")

    singletons: dict[str, Any] = {"available": False, "reason": "not requested"}
    if config.get("baskets", {}).get("compare_singleton_policies", True):
        singletons = compare_singleton_policies(
            baskets,
            min_support=float(mining["min_support"]),
            min_confidence=float(mining.get("min_confidence", 0.2)),
            max_length=2,
        )
        if singletons.get("available"):
            print("\nsingle-item basket policy (Qiu et al. 2023, sections 3.1-3.2):")
            print(f"  {singletons['verdict']}")

    layout: dict[str, Any] = {"available": False, "reason": "not requested"}
    settings = config.get("colocation", {})
    if settings.get("enabled", True) and rules:
        popularity: dict[int, int] = {}
        for basket in baskets.transactions:
            for item in basket:
                popularity[item] = popularity.get(item, 0) + 1
        layout = evaluate_layout(
            baskets.transactions,
            catalogue=catalogue,
            affinity=affinity_graph(
                rules, weight=settings.get("affinity", "normalised_lift")
            ),
            zone_capacity=int(settings.get("zone_capacity", 20)),
            popularity=popularity,
            random_seeds=int(settings.get("random_seeds", 5)),
            seed=int(config.get("reproducibility", {}).get("random_seed", 20260101)),
        )
        if layout.get("available"):
            print("\nstorage co-location (Jirapatsil & Phumchusri 2022):")
            print(f"  {layout['verdict']}")

    export_cap = int(config.get("output", {}).get("max_rules_exported", 500))
    return {
        "dataset": {"id": str(dataset.id), "name": dataset.name,
                    "pipeline_version": getattr(dataset, "pipeline_version", None)},
        "baskets": baskets.as_dict(),
        "split": {
            "mine_baskets": earlier.n_transactions,
            "holdout_baskets": later.n_transactions,
            "mine_from": str(min(earlier.dates)),
            "mine_to": str(max(earlier.dates)),
            "holdout_from": str(min(later.dates)),
            "holdout_to": str(max(later.dates)),
            "method": (
                "Chronological. A random split would put baskets from the same "
                "week on both sides, confirming a seasonal pairing with data a "
                "few days from the baskets that produced it."
            ),
        },
        "itemsets": itemsets.as_dict(),
        "top_itemsets": [
            {**row, "labels": baskets.describe(row["items"])}
            for row in top_itemsets(itemsets, n=20)
        ],
        "rules_summary": report,
        "pruning": removals,
        "rules": [r.as_dict(labels=baskets.label) for r in rules[:export_cap]],
        "rules_exported": min(len(rules), export_cap),
        "rules_generated": generated,
        "rules_total": len(rules),
        "validated_set": (
            "Associations only - rules with lift above 1 that survived the "
            "false-discovery-rate correction, with restatements of more general "
            "rules removed. Rules that cleared the support and confidence "
            "thresholds but failed their own significance test are counted in "
            "rules_generated and excluded here, because nobody would act on them "
            "and their presence would turn the survival rate into a measure of "
            "how much noise the thresholds admitted."
        ),
        "holdout_validation": held,
        "rule_set_overlap": overlap,
        "recommender_hazards": hazards,
        "singleton_policy": singletons,
        "colocation": layout,
        "new_products_in_holdout": len(new_in_holdout),
        "sources": {
            "support_confidence_lift": (
                "Jirapatsil & Phumchusri (2022), MSIE 2022, Equations 1-5; the "
                "lift > 1 decision rule is their section 3.1."
            ),
            "dependence_measures": (
                "Ni, Luo, Lu & Zhu (2020), ACM TMIS 11(1) Article 3, "
                "Equations 3, 4, 8 and 10."
            ),
            "singleton_deletion": (
                "Qiu, Ning, Zhang & Yang (2023), ICMLCA 2023, sections 3.1-3.2, "
                "replicated and examined rather than adopted."
            ),
            "hazard_metrics": (
                "Kathriarachchi, Alam & Rashid (2026), ACM TORS 4(3) Article 42, "
                "Equations 4, 10 and 12."
            ),
            "colocation": (
                "Jirapatsil & Phumchusri (2022), MSIE 2022, section 3.2. Their "
                "distance reduction is not reproduced; see colocation.method_note."
            ),
            "not_from_the_supplied_papers": (
                "Leverage, conviction and Zhang's metric; the chronological "
                "hold-out validation; and the Benjamini-Hochberg correction. "
                "The Fisher exact test itself follows the chi-square dependence "
                "testing of Silverstein et al. (1998) as described in Ni et al. "
                "(2020) section 2.4."
            ),
        },
    }


def _no_rules(config, baskets, earlier, later, itemsets, dataset) -> dict[str, Any]:
    """A run that found nothing is still a run, and still gets written out."""
    print(
        "\nNo itemset reached the declared support threshold.\n"
        "  That is a result, not a failure: it says no product combination in\n"
        "  this data is common enough at the threshold declared before the run.\n"
        "  Lowering min_support now and re-running would be choosing the answer.\n"
        "  Report this, then if you want a lower threshold, change the config,\n"
        "  say that you changed it, and let the hash show it."
    )
    return {
        "dataset": {"id": str(dataset.id), "name": dataset.name},
        "baskets": baskets.as_dict(),
        "split": {
            "mine_baskets": earlier.n_transactions,
            "holdout_baskets": later.n_transactions,
        },
        "itemsets": itemsets.as_dict(),
        "rules_summary": summarise([]),
        "rules": [],
        "rules_total": 0,
        "holdout_validation": {"available": False, "reason": "No rules to validate."},
    }


def export(record, config, config_path: Path, digest: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, destination / "config.toml")
    output = config.get("output", {})

    record = {
        "meta": config.get("meta", {}),
        "config_hash": digest,
        "run_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        **record,
    }
    if output.get("write_json", True):
        (destination / "run.json").write_text(json.dumps(record, indent=2, default=str))

    if not output.get("write_csv", True):
        return

    if record.get("rules"):
        frame = pd.DataFrame([
            {
                "antecedent": " + ".join(rule["antecedent"]),
                "consequent": " + ".join(rule["consequent"]),
                "support": rule["support"],
                "support_count": rule["support_count"],
                "confidence": rule["confidence"],
                "lift": rule["lift"],
                "leverage": rule["leverage"],
                "zhang": rule["zhang"],
                "p_value": rule["p_value"],
                "q_value": rule["q_value"],
                "significant": rule["significant"],
                "is_association": rule["is_association"],
            }
            for rule in record["rules"]
        ])
        frame.to_csv(destination / "rules.csv", index=False)

    held = record.get("holdout_validation", {})
    if held.get("available"):
        rows = (
            [{"outcome": "survived", **row} for row in held["strongest_survivors"]]
            + [{"outcome": "failed", **row} for row in held["largest_falls"]]
        )
        pd.DataFrame(rows).to_csv(destination / "holdout.csv", index=False)

    if record.get("top_itemsets"):
        pd.DataFrame([
            {
                "items": " + ".join(row["labels"]),
                "length": row["length"],
                "count": row["count"],
                "support": row["support"],
            }
            for row in record["top_itemsets"]
        ]).to_csv(destination / "top_itemsets.csv", index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and profile the baskets without mining")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.config.exists():
        print(f"No such config: {args.config}")
        return 2

    try:
        config, digest = load_config(args.config)
        outcome = run(config, digest, args.dry_run)
    except ConfigError as error:
        print(f"\n{error}")
        return 2

    if isinstance(outcome, int):
        return outcome

    root = args.out or Path(config.get("output", {}).get("directory", "research/results"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = root / f"{stamp}-{config['meta'].get('name', args.config.stem)}"
    export(outcome, config, args.config, digest, destination)
    print(f"\nwritten to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
