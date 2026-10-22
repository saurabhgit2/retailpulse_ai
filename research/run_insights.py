"""Build the two RQ4 conditions from executed RQ1, RQ2 and RQ3 runs.

    python research/run_insights.py research/configs/rq4_insights.toml

Same discipline as the other three runners: the protocol comes from a committed
TOML file, the file's SHA-256 travels with the results, and `--dry-run`
validates the inputs without building anything.

**This runner needs no database.** It reads the `run.json` files the earlier
experiments already wrote, so it is fast, repeatable, and cannot drift from the
figures reported for RQ1 to RQ3. If a recommendation quotes a number, that
number came from a committed result directory with its own configuration hash.

What it produces, in order:

1. A reliability assessment of each engine from its own out-of-sample evidence.
2. Signals, reconciled into findings by subject.
3. **Condition A**, the integrated condition: ranked recommendations with
   evidence, caveats, driving figures and corroboration.
4. **Condition B**, the isolated condition: the same signals as three separate
   reports, which is the RQ4 control.
5. The transparency index, the integration report and the reconciliation
   burden.

Conditions A and B are written as plain-text session packs so the RQ4 sessions
can run without waiting for the dashboard. Assign participants to one condition
first, then the other, counterbalancing the order across participants so that
practice effects do not land on one condition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.insights import baseline as baseline_module  # noqa: E402
from app.insights import (  # noqa: E402
    explanation,
    fairness,
    ranking,
    reconcile,
    reliability,
    signals,
)
from app.insights.recommendations import build, deduplicate  # noqa: E402


class ConfigError(ValueError):
    """The configuration or its inputs are unusable."""


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        config = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error
    validate_config(config)
    return config, hashlib.sha256(raw).hexdigest()


def validate_config(config: dict[str, Any]) -> None:
    problems: list[str] = []
    for section in ("meta", "inputs", "ranking"):
        if section not in config:
            problems.append(f"Missing [{section}] section.")
    if problems:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(problems))

    inputs = config["inputs"]
    named = [k for k in ("forecast", "segmentation", "association") if inputs.get(k)]
    if not named:
        problems.append(
            "No input runs named. Set at least one of inputs.forecast, "
            "inputs.segmentation or inputs.association to a results directory."
        )
    if len(named) < 2:
        problems.append(
            "Fewer than two engines supplied. RQ4 compares an integrated view "
            "against isolated components, and neither condition means anything "
            "with one engine."
        )

    try:
        ranking.validate_weights(dict(config["ranking"].get("weights", {})))
    except ranking.RankingError as error:
        problems.append(f"ranking.weights: {error}")

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


def _resolve(root: Path, value: str) -> Path:
    """A results directory, either named explicitly or the latest of a kind.

    `latest:rq2-segmentation-stability` picks the most recent directory whose
    name ends with that suffix. Convenient while iterating, and the resolved
    path is recorded in the output so the run stays traceable.
    """
    if value.startswith("latest:"):
        suffix = value.split(":", 1)[1]
        candidates = sorted(
            (p for p in root.iterdir() if p.is_dir() and p.name.endswith(suffix)),
            key=lambda p: p.name,
        )
        if not candidates:
            raise ConfigError(f"No results directory ending in {suffix!r} under {root}.")
        return candidates[-1]
    path = Path(value)
    return path if path.is_absolute() else root / value


def load_runs(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Path]]:
    """The three result files, with the directory each came from."""
    root = Path(config["inputs"].get("results_directory", "research/results"))
    if not root.exists():
        raise ConfigError(f"No results directory at {root}.")

    runs: dict[str, Any] = {}
    sources: dict[str, Path] = {}
    for key in ("forecast", "segmentation", "association"):
        declared = (config["inputs"].get(key) or "").strip()
        if not declared:
            runs[key] = None
            continue
        directory = _resolve(root, declared)
        record = directory / "run.json"
        if not record.exists():
            raise ConfigError(f"{record} does not exist.")
        runs[key] = json.loads(record.read_text())
        sources[key] = directory
    return runs, sources


def total_revenue_from(segmentation: dict[str, Any] | None) -> float | None:
    """Total revenue, taken from the segmentation profiles rather than the database.

    Keeping the runner database-free means the monetary figures in a
    recommendation come from the same committed result file as everything else.
    """
    if not segmentation:
        return None
    rows = (segmentation.get("profiles") or {}).get("rows") or []
    values = [float(r["total_monetary"]) for r in rows if r.get("total_monetary")]
    return sum(values) if values else None


def run(config: dict[str, Any], digest: str, dry_run: bool) -> dict[str, Any] | int:
    meta = config.get("meta", {})
    print(f"\n{meta.get('name', 'insights')}  ({meta.get('research_question', '?')})")
    print(f"config sha256: {digest}\n")
    print("environment:")
    for key, value in environment().items():
        print(f"  {key:<10} {value}")

    runs, sources = load_runs(config)
    print("\ninput runs:")
    for key in ("forecast", "segmentation", "association"):
        if runs.get(key):
            hashes = runs[key].get("config_hash", "")
            print(f"  {key:<14} {sources[key].name}  (config {hashes[:8]})")
        else:
            print(f"  {key:<14} not supplied")

    assessed = reliability.assess(
        runs.get("forecast"), runs.get("segmentation"), runs.get("association")
    )
    print("\nengine reliability, from each engine's own out-of-sample evidence:")
    for source, item in assessed.items():
        print(f"  {source:<14} {item.score:.3f}  {item.band:<9} {item.basis}")

    presentation = config.get("presentation", {})
    collected = signals.collect(
        forecast=runs.get("forecast"),
        segmentation=runs.get("segmentation"),
        association=runs.get("association"),
        reliabilities=assessed,
        rule_limit=int(presentation.get("rule_limit", 25)),
    )
    print(f"\nsignals: {len(collected)}")
    for source, scopes in signals.scopes_present(collected).items():
        print(f"  {source:<14} speaks at {', '.join(scopes)} scope")

    if dry_run:
        print("\nDry run: nothing was reconciled and nothing was written.")
        return 0

    findings = reconcile.reconcile(collected)
    integration = reconcile.integration_report(findings, collected)
    print(f"\nfindings: {integration['findings']}  "
          f"corroborated by more than one engine: {integration['corroborated']}")
    print(f"  {integration['note']}")

    recommendations = ranking.rank(
        deduplicate(build(findings, total_revenue=total_revenue_from(runs.get("segmentation")))),
        weights=dict(config["ranking"]["weights"]),
    )
    top = int(presentation.get("top_n", 10))
    shortlist = recommendations[:top]

    transparency = explanation.transparency_index(shortlist)
    print(f"\ncondition A - integrated: {len(shortlist)} recommendations "
          f"(of {len(recommendations)} generated)")
    print(f"  {transparency['verdict']}")
    for position, rec in enumerate(shortlist, start=1):
        marker = "++" if rec.corroborated else "  "
        print(f"  {marker} {position}. [{rec.priority:.3f}] {rec.action[:88]}")

    procedural = fairness.assess(shortlist)
    print("\nprocedural fairness (Wang et al. 2026, Definitions 1-3):")
    print(f"  {procedural.get('verdict', procedural.get('reason'))}")

    control = baseline_module.isolated_presentation(
        collected, assessed, per_list=int(presentation.get("per_list", 10))
    )
    burden = baseline_module.reconciliation_burden(shortlist, control)
    print(f"\ncondition B - isolated: {control['items']} items across "
          f"{len(control['lists'])} unordered lists")
    print(f"  {burden['note']}")

    return {
        "inputs": {
            key: {
                "directory": str(path),
                "config_hash": runs[key].get("config_hash"),
                "meta": runs[key].get("meta"),
            }
            for key, path in sources.items()
        },
        "reliability": reliability.summarise(assessed),
        "procedural_fairness_correction": fairness.correction_note(),
        "signals": [s.as_dict() for s in collected],
        "scopes": signals.scopes_present(collected),
        "integration": integration,
        "ranking": ranking.explain_weights(dict(config["ranking"]["weights"])),
        "condition_a_integrated": {
            "recommendations": [r.as_dict() for r in shortlist],
            "generated": len(recommendations),
            "shown": len(shortlist),
            "transparency": transparency,
            "procedural_fairness": procedural,
        },
        "condition_b_isolated": control,
        "reconciliation_burden": burden,
        "session_protocol": {
            "design": (
                "Within-participant. Each participant sees both conditions, with "
                "the order counterbalanced across participants so practice "
                "effects do not accumulate on one condition."
            ),
            "measures": [
                "Time to reach a stated stock or promotion decision",
                "Recommendations accepted that the evidence does not support",
                "Recommendations rejected that the evidence does support",
                "Self-rated explanation sufficiency on a five-point scale",
                "Self-rated trust in the presented analysis",
            ],
            "measure_note": (
                "Acceptance is recorded as two separate counts rather than one "
                "rate. Jordan and Mitchell (2015) observe that a performance "
                "measure is a choice and may penalise one error direction more "
                "than the other; in retail, acting on a poor recommendation and "
                "ignoring a sound one carry different costs, and a single "
                "acceptance rate would average them away."
            ),
            "caveat": (
                "Both packs are text. Any difference observed is a difference of "
                "structure and content, not of visual design, which the "
                "dissertation should state when reporting the result."
            ),
        },
    }


def export(record, config, config_path: Path, digest: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, destination / "config.toml")

    full = {
        "meta": config.get("meta", {}),
        "config_hash": digest,
        "run_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        **record,
    }
    output = config.get("output", {})
    if output.get("write_json", True):
        (destination / "run.json").write_text(json.dumps(full, indent=2, default=str))

    # The two session packs, which are what the RQ4 sessions actually use.
    from app.insights.recommendations import Recommendation

    rebuilt = [
        Recommendation(**{
            k: v for k, v in row.items()
            if k in Recommendation.__dataclass_fields__
        })
        for row in record["condition_a_integrated"]["recommendations"]
    ]
    (destination / "condition_a_integrated.txt").write_text(
        explanation.session_pack(
            rebuilt, title="Condition A - integrated decision support"
        )
    )
    (destination / "condition_b_isolated.txt").write_text(
        baseline_module.session_pack(
            record["condition_b_isolated"], title="Condition B - separate reports"
        )
    )

    if not output.get("write_csv", True):
        return

    pd.DataFrame([
        {
            "priority": r["priority"],
            "template": r["template"],
            "subject": r["subject"]["label"],
            "scope": r["subject"]["scope"],
            "action": r["action"],
            "corroborated": r["corroborated"],
            "sources": " + ".join(r["sources"]),
            "silent": " + ".join(r["silent_sources"]),
            "evidence_weight": r["evidence_weight"],
            "caveats": " | ".join(r["caveats"]),
        }
        for r in record["condition_a_integrated"]["recommendations"]
    ]).to_csv(destination / "recommendations.csv", index=False)

    pd.DataFrame(record["reliability"]["rows"]).to_csv(
        destination / "reliability.csv", index=False
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and report scopes without building")
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
    print("  condition_a_integrated.txt and condition_b_isolated.txt are the "
          "session packs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
