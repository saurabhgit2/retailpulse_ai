"""Measure warm API response latency against the NFR-01 target.

Assessment 1 Table 10 states an evaluation criterion of "interactive response
under 3 seconds", and the architecture document restates it as a p95. Neither
is satisfied by a stopwatch: this script produces the number.

What it measures, and what it does not
--------------------------------------
It measures the **warm round trip** — request sent to last byte of the
response body read — which is what a browser experiences once an analysis has
been computed and cached. That is the quantity the 3-second target is about.

It does not measure cold computation. Those figures already exist, recorded
by the application itself in `analysis_results.computed_ms`, and they are an
order of magnitude larger. Both numbers belong in the report, and conflating
them would overstate the problem: a user meets the cold path once.

Each endpoint is called once to warm it and that call is discarded, then
called `--repeats` times. The discard matters. Including a cold first call in
a sample of ten would move the median for a cost almost no request pays.

Why percentiles rather than a mean
----------------------------------
A mean over ten samples is moved by one outlier, and an outlier here is
usually the machine doing something else. The target is stated as a p95, so
p95 is what is reported, with p50 beside it to show the typical case.

With ten repeats the p95 *is* the slowest sample — by nearest rank, ceil(0.95
x 10) = 10. So at this sample size p95 reports the worst observation rather
than a tail estimate, and the output says so rather than implying more
precision than ten observations can carry. Raise `--repeats` to 50 where the
result lands near the boundary and the answer matters.

Usage
-----
    python measure_latency.py --dataset-id <uuid> --repeats 10

Credentials come from RETAILPULSE_EMAIL and RETAILPULSE_PASSWORD, or are
prompted for. They are never written to the output.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover - the backend venv has it via Starlette
    sys.exit("httpx is required. Run this inside the backend virtual environment.")


TARGET_SECONDS = 3.0

# Everything the dashboard calls, in the order the pages call them. The
# forecast endpoints are excluded: a run is started asynchronously and polled,
# so its latency is not a page-load figure and measuring it here would mix two
# different claims.
ENDPOINTS = [
    ("filter-options", "/filter-options"),
    ("kpis", "/analytics/kpis"),
    ("trends", "/analytics/trends"),
    ("products", "/analytics/products"),
    ("customers", "/analytics/customers"),
    ("rfm", "/analytics/rfm"),
    ("baskets", "/analytics/baskets"),
    ("distributions", "/analytics/distributions"),
    ("seasonality", "/analytics/seasonality"),
    ("statistics", "/analytics/statistics"),
    ("features", "/analytics/features"),
    ("series-profile", "/analytics/series-profile"),
    ("relationships", "/analytics/relationships"),
    ("anomalies", "/analytics/anomalies"),
]


def percentile(values: list[float], p: float) -> float:
    """The p-th percentile by nearest rank.

    Nearest rank rather than interpolation: with ten samples an interpolated
    p95 invents a value that was never observed, and every figure here should
    be one the machine actually produced.
    """
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[index]


def login(client: httpx.Client, base: str, email: str, password: str) -> str:
    response = client.post(
        f"{base}/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        sys.exit("Login succeeded but returned no access_token.")
    return token


def time_one(client: httpx.Client, url: str, headers: dict) -> tuple[float, int, int]:
    """One request, timed to the last byte of the body.

    `client.get` reads the whole body, which is deliberate: a response is not
    useful to a page until it has arrived, and the RFM payload is 1.5 MB.
    Timing only the headers would report a number no user experiences.
    """
    started = time.perf_counter()
    response = client.get(url, headers=headers)
    body = response.content
    elapsed = time.perf_counter() - started
    return elapsed, response.status_code, len(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--out", default="artifacts/performance")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    email = os.environ.get("RETAILPULSE_EMAIL") or input("Email: ").strip()
    password = os.environ.get("RETAILPULSE_PASSWORD") or getpass.getpass("Password: ")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    base = args.base_url.rstrip("/")
    dataset_path = f"{base}/api/v1/datasets/{args.dataset_id}"

    rows = []
    with httpx.Client(timeout=args.timeout) as client:
        token = login(client, base, email, password)
        headers = {"Authorization": f"Bearer {token}"}

        for name, path in ENDPOINTS:
            url = f"{dataset_path}{path}"

            warm_elapsed, status, size = time_one(client, url, headers)
            if status != 200:
                print(f"{name:16} SKIPPED  HTTP {status}")
                rows.append(
                    {"endpoint": name, "status": status, "samples": 0, "note": "non-200 response"}
                )
                continue

            samples = []
            for _ in range(args.repeats):
                elapsed, status, size = time_one(client, url, headers)
                if status != 200:
                    break
                samples.append(elapsed)

            if not samples:
                rows.append({"endpoint": name, "status": status, "samples": 0})
                continue

            p50 = percentile(samples, 50)
            p95 = percentile(samples, 95)
            row = {
                "endpoint": name,
                "status": 200,
                "samples": len(samples),
                "bytes": size,
                "discarded_first_call_s": round(warm_elapsed, 4),
                "min_s": round(min(samples), 4),
                "p50_s": round(p50, 4),
                "p95_s": round(p95, 4),
                "max_s": round(max(samples), 4),
                "mean_s": round(statistics.fmean(samples), 4),
                "meets_target": bool(p95 <= TARGET_SECONDS),
            }
            rows.append(row)
            verdict = "ok " if row["meets_target"] else "OVER"
            print(
                f"{name:16} {verdict}  p50 {p50:6.3f}s  p95 {p95:6.3f}s  "
                f"{size / 1024:8.1f} KB"
            )

    measured = [r for r in rows if r.get("samples")]
    failing = [r for r in measured if not r["meets_target"]]

    report = {
        "measured_at": stamp,
        "target_seconds": TARGET_SECONDS,
        "target_source": "Assessment 1 Table 10; architecture TO3 (p95)",
        "measures": "warm round trip, request to last byte of response body",
        "excludes": (
            "cold computation, which the application records separately in "
            "analysis_results.computed_ms"
        ),
        "base_url": base,
        "dataset_id": args.dataset_id,
        "repeats_per_endpoint": args.repeats,
        "first_call_per_endpoint_discarded": True,
        "percentile_method": "nearest rank, no interpolation",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "httpx": httpx.__version__,
        },
        "caveat": (
            f"p95 by nearest rank over {args.repeats} samples; at ten repeats this is "
            "the slowest observation rather than a tail estimate. Raise --repeats where "
            "the result sits near the target."
        ),
        "endpoints_measured": len(measured),
        "endpoints_over_target": len(failing),
        "over_target": [r["endpoint"] for r in failing],
        "results": rows,
    }

    (out_dir / "latency.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    columns = [
        "endpoint", "status", "samples", "bytes",
        "min_s", "p50_s", "p95_s", "max_s", "mean_s", "meets_target",
    ]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(str(row.get(c, "")) for c in columns))
    (out_dir / "latency.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    print(f"{len(measured)} endpoints measured, {len(failing)} over the {TARGET_SECONDS:.0f}s target.")
    if failing:
        print("Over target: " + ", ".join(r["endpoint"] for r in failing))
    print(f"Written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
