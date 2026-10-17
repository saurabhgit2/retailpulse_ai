"""Run the RQ2 segmentation experiment and export its results.

    python research/run_segmentation.py research/configs/rq2_segmentation.toml

Same shape and same discipline as `run_experiment.py`: the protocol comes from
a committed TOML file, the file's SHA-256 travels with the results, the library
versions are recorded, and `--dry-run` validates everything without fitting.

What it does, in order:

1. Build the as-of windows from the declared rule.
2. For each window, query the RFM table **as it stood at that date** and build
   the feature matrix with the declared transforms.
3. For each clustering family, fit every k in the range and compute the quality
   indices - so the choice of k is evidenced rather than asserted.
4. At the declared k, measure stability across the windows: Adjusted Rand Index
   and the share of customers who stayed put.
5. Profile the clusters in original units, and optionally compare them against
   the conventional RFM score bands.

**The k is declared in the config, not chosen from the stability results.**
Picking the k that gives the best stability would be choosing the answer. The
quality indices are reported for the whole range so a reader can see whether
the declared k was a reasonable choice, which is a different and honest thing.
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

from app.analytics.rfm import build_rfm  # noqa: E402
from app.segmentation.clustering import CLUSTERERS, cluster, fit_range  # noqa: E402
from app.segmentation.profiles import compare_with_rfm_bands, describe_clusters  # noqa: E402
from app.segmentation.quality import compare_k, gap_statistic  # noqa: E402
from app.segmentation.scaling import build_matrix  # noqa: E402
from app.segmentation.stability import migration_matrix, stability_across_windows  # noqa: E402
from app.segmentation.windows import (  # noqa: E402
    WindowError,
    Window,
    describe_windows,
    make_windows,
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

    for section in ("meta", "data", "windows", "clustering"):
        if section not in config:
            problems.append(f"Missing [{section}] section.")
    if problems:
        raise ConfigError("\n".join(problems))

    if config["data"].get("source") not in ("database",):
        problems.append(
            "data.source must be 'database'. Segmentation needs the cleaned, "
            "stored dataset; there is no CSV shortcut because customer "
            "identity depends on the pipeline's cleaning rules."
        )

    windows = config["windows"]
    if int(windows.get("count", 0)) < 2:
        problems.append("windows.count must be at least 2; stability needs a comparison.")
    if windows.get("style") not in ("expanding", "rolling"):
        problems.append("windows.style must be 'expanding' or 'rolling'.")

    clustering = config["clustering"]
    unknown = [a for a in clustering.get("algorithms", []) if a not in CLUSTERERS]
    if unknown:
        problems.append(
            f"Unknown algorithm(s) {unknown}. Available: {', '.join(sorted(CLUSTERERS))}."
        )
    if not clustering.get("algorithms"):
        problems.append("clustering.algorithms is empty - there is nothing to run.")

    k = int(clustering.get("k", 0))
    k_min, k_max = int(clustering.get("k_min", 2)), int(clustering.get("k_max", 8))
    if k_max < k_min:
        problems.append(f"clustering.k_max ({k_max}) is below k_min ({k_min}).")
    if not k_min <= k <= k_max:
        problems.append(
            f"clustering.k ({k}) is outside the fitted range {k_min}-{k_max}, so "
            f"the quality indices would say nothing about the k actually used."
        )

    if problems:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(problems))


def environment() -> dict[str, str]:
    import platform

    import numpy
    import scipy
    import sklearn

    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
    }


def load_dataset(config: dict[str, Any]):
    """The dataset to segment, and a warning if it was not named explicitly."""
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


def snapshot(session, dataset, window: Window) -> dict[str, Any]:
    """The RFM table as it stood at this window's as-of date."""
    from app.db.repositories import analytics as repo
    from app.db.repositories.analytics import Filters

    filters = Filters(date_from=window.start, date_to=window.end)
    customers = repo.customer_rfm(session, dataset.id, filters)
    if customers.empty:
        return {"available": False, "reason": "No identified customers in this window."}

    # as_of is the window's end, not today: recency must be measured from the
    # point the snapshot represents, or every window would report the same
    # customer as more lapsed than the last.
    rfm = build_rfm(customers, as_of=window.end)
    if not rfm.get("available"):
        return {"available": False, "reason": rfm.get("reason")}

    table = pd.DataFrame(rfm["table"])
    guests = repo.guest_summary(session, dataset.id, filters)
    return {
        "available": True,
        "table": table,
        "as_of": rfm["as_of"],
        "customers": int(len(table)),
        "guest_revenue": guests.get("guest_revenue"),
        "segments": rfm["segments"],
        "bands": {
            str(row["customer"]): str(row["segment"])
            for row in rfm["table"] if row.get("segment")
        },
    }


def run(config: dict[str, Any], digest: str, dry_run: bool) -> dict[str, Any] | int:
    meta = config.get("meta", {})
    print(f"\n{meta.get('name', 'segmentation')}  ({meta.get('research_question', '?')})")
    print(f"config sha256: {digest}\n")
    print("environment:")
    for key, value in environment().items():
        print(f"  {key:<14} {value}")

    dataset, session = load_dataset(config)
    try:
        if not dataset.date_min or not dataset.date_max:
            raise ConfigError(
                "The dataset has no recorded date range; it may not have finished "
                "processing."
            )

        settings = config["windows"]
        try:
            windows = make_windows(
                dataset.date_min, dataset.date_max,
                count=int(settings.get("count", 4)),
                style=settings.get("style", "expanding"),
                window_days=settings.get("window_days"),
                min_history_days=int(settings.get("min_history_days", 365)),
            )
        except WindowError as error:
            print(f"\nThe windows do not fit this dataset:\n  {error}")
            return 1

        print(f"\ndataset: {dataset.name}  "
              f"({dataset.date_min.date()} to {dataset.date_max.date()})")
        print("windows:")
        for window in windows:
            start = "start of data" if window.start is None else str(window.start.date())
            print(f"  {window.index}: {start} -> {window.end.date()}")

        if dry_run:
            print("\nDry run: nothing was fitted and nothing was written.")
            return 0

        snapshots: dict[str, dict[str, Any]] = {}
        for window in windows:
            taken = snapshot(session, dataset, window)
            if not taken.get("available"):
                print(f"  window {window.index}: {taken.get('reason')}")
                continue
            snapshots[window.label] = taken
            print(f"  window {window.index} ({window.label}): "
                  f"{taken['customers']:,} identified customers")

        if len(snapshots) < 2:
            print("\nFewer than two usable windows; stability cannot be measured.")
            return 1

        return _analyse(config, snapshots, windows, dataset)
    finally:
        session.close()


def _analyse(config, snapshots, windows, dataset) -> dict[str, Any]:
    clustering = config["clustering"]
    seed = int(config.get("reproducibility", {}).get("random_seed", 20260101))
    k = int(clustering["k"])
    features = config.get("features", {})

    matrices = {}
    for label, taken in snapshots.items():
        matrices[label] = build_matrix(
            taken["table"],
            scaler=features.get("scaler", "standard"),
            negative_monetary=features.get("negative_monetary", "signed_log"),
            invert_recency=bool(features.get("invert_recency", True)),
        )

    last_label = sorted(matrices)[-1]
    reference = matrices[last_label]
    print(f"\nfeature matrix ({last_label}): {reference.shape[0]:,} customers x "
          f"{reference.shape[1]} features, scaler={reference.scaler}")
    for note in reference.notes:
        print(f"  note: {note}")

    # --- choosing k: evidence across the range, on the latest window --------
    quality: dict[str, Any] = {}
    print(f"\nquality indices on the latest window ({last_label}):")
    for algorithm in clustering["algorithms"]:
        fitted = fit_range(
            reference.matrix, algorithm,
            k_min=int(clustering.get("k_min", 2)),
            k_max=int(clustering.get("k_max", 8)),
            seed=seed,
        )
        comparison = compare_k(reference.matrix, fitted, seed=seed)
        quality[algorithm] = comparison
        preferred = comparison["preferred_k"]
        print(f"  {algorithm:<13} preferred k: " + ", ".join(
            f"{name}={value}" for name, value in preferred.items() if value
        ))

    gap: dict[str, Any] = {"available": False, "reason": "not requested"}
    if config.get("quality", {}).get("gap_statistic", True):
        gap = gap_statistic(
            reference.matrix,
            list(range(int(clustering.get("k_min", 2)), int(clustering.get("k_max", 8)) + 1)),
            references=int(config.get("quality", {}).get("gap_references", 10)),
            seed=seed,
        )
        print(f"\ngap statistic: {gap.get('note')}")

    # --- stability at the declared k ---------------------------------------
    results: dict[str, Any] = {}
    for algorithm in clustering["algorithms"]:
        partitions: dict[str, dict[str, int]] = {}
        for label, matrix in matrices.items():
            fitted = cluster(matrix.matrix, k, algorithm, seed=seed)
            partitions[label] = {
                customer: int(group)
                for customer, group in zip(matrix.customers, fitted.labels, strict=True)
            }
        stability = stability_across_windows(
            partitions,
            consecutive_only=bool(config.get("stability", {}).get("consecutive_only", False)),
        )
        results[algorithm] = {"partitions": partitions, "stability": stability}

        print(f"\n{algorithm} at k={k}:")
        if stability.get("available"):
            print(f"  mean ARI {stability['mean_adjusted_rand']:.3f}, "
                  f"retention {stability['mean_retention_share']:.1%}")
            print(f"  {stability['verdict']}")
        else:
            print(f"  {stability.get('reason')}")

    # --- profiles and the band comparison, on the latest window ------------
    primary = clustering["algorithms"][0]
    final = cluster(reference.matrix, k, primary, seed=seed)
    usable = snapshots[last_label]["table"]
    usable = usable[usable["customer"].astype(str).isin(reference.customers)]
    profile = describe_clusters(usable, final.labels)

    print(f"\nclusters ({primary}, k={k}, window {last_label}):")
    for row in profile["rows"]:
        print(f"  {row['cluster']}: {row['name']:<34} "
              f"{row['customers']:>6,} customers  "
              f"{row['revenue_share']:>6.1%} of revenue")

    bands: dict[str, Any] = {"available": False, "reason": "not requested"}
    if config.get("stability", {}).get("compare_with_rfm_bands", True):
        labels = {c: int(l) for c, l in zip(reference.customers, final.labels, strict=True)}
        bands = compare_with_rfm_bands(labels, snapshots[last_label]["bands"])
        if bands.get("available"):
            print(f"\nvs conventional RFM bands: {bands['verdict']}")

    migrations = {}
    labels_sorted = sorted(results[primary]["partitions"])
    for earlier, later in zip(labels_sorted, labels_sorted[1:], strict=False):
        migrations[f"{earlier} -> {later}"] = migration_matrix(
            results[primary]["partitions"][earlier],
            results[primary]["partitions"][later],
        )

    return {
        "dataset": {"id": str(dataset.id), "name": dataset.name,
                    "pipeline_version": dataset.pipeline_version},
        "windows": describe_windows(windows),
        "snapshots": {
            label: {"customers": taken["customers"], "as_of": taken["as_of"],
                    "guest_revenue": taken["guest_revenue"]}
            for label, taken in snapshots.items()
        },
        "matrix": reference.as_dict(),
        "quality": quality,
        "gap_statistic": gap,
        "k": k,
        "stability": {a: r["stability"] for a, r in results.items()},
        "profiles": profile,
        "rfm_band_comparison": bands,
        "migrations": migrations,
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

    if output.get("write_csv", True):
        pd.DataFrame(record["profiles"]["rows"]).to_csv(
            destination / "cluster_profiles.csv", index=False
        )
        rows = []
        for algorithm, stability in record["stability"].items():
            for pair in stability.get("pairs", []):
                rows.append({"algorithm": algorithm, **pair})
        if rows:
            pd.DataFrame(rows).to_csv(destination / "stability.csv", index=False)
        quality_rows = []
        for algorithm, comparison in record["quality"].items():
            for row in comparison["rows"]:
                quality_rows.append({"algorithm": algorithm, **row})
        if quality_rows:
            pd.DataFrame(quality_rows).to_csv(destination / "quality_by_k.csv", index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and print the windows without clustering")
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
