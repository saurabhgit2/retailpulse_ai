"""The whole journey: upload -> confirm mapping -> process -> report.

This is the test that proves the pieces fit together. It uses the real
pipeline and a real database; only the background task is run inline (FastAPI's
TestClient does that automatically) so the test is deterministic.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

pytestmark = pytest.mark.db

DATASETS = "/api/v1/datasets"


def build_csv(days: int = 90) -> str:
    """A small but realistic file: enough weeks to pass the minimum, with the
    same problems the pipeline is meant to handle."""
    rows = []
    for index, day in enumerate(pd.date_range("2024-01-01", periods=days).strftime("%Y-%m-%d")):
        for item in range(3):
            rows.append(
                f"{2000 + index}{item},SYN-00{item + 1},SYNTHETIC ITEM {item + 1},"
                f"{2 + item},{day} 09:0{item}:00,{3 + item}.00,"
                f"{500 + (index % 20)},United Kingdom"
            )
    rows.append(rows[0])                                   # exact duplicate
    rows.append("C9999,SYN-001,SYNTHETIC ITEM 1,-2,2024-02-01 09:00:00,3.00,501,United Kingdom")
    rows.append("9998,POST,POSTAGE,1,2024-02-01 09:00:00,18.00,502,United Kingdom")
    rows.append("9997,SYN-002,SYNTHETIC ITEM 2,1,2024-02-02 09:00:00,0.00,,United Kingdom")
    # A guest sale that is otherwise valid. It has to be its own row: the
    # zero-price row above also has no customer, but it is excluded at step 5,
    # before step 7 ever sees it - so on its own it can never produce a guest.
    rows.append("9995,SYN-003,SYNTHETIC ITEM 3,2,2024-02-03 09:00:00,5.00,,United Kingdom")
    rows.append("9996,SYN-002,SYNTHETIC ITEM 2,1,not a date,4.00,503,United Kingdom")

    header = "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country"
    return header + "\n" + "\n".join(rows) + "\n"


def test_upload_to_quality_report(registered_client):
    client, _, _ = registered_client
    csv_text = build_csv()

    # 1. Upload: the file is stored and profiled, nothing is cleaned yet.
    created = client.post(
        DATASETS,
        files={"file": ("synthetic.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        data={"is_synthetic": "true"},
    )
    assert created.status_code == 201
    dataset = created.json()
    assert dataset["status"] == "awaiting_mapping"

    # 2. Confirm the suggested mapping and start processing.
    accepted = client.post(
        f"{DATASETS}/{dataset['id']}/process",
        json={"mapping": dataset["profile"]["suggested_mapping"], "options": {}},
    )
    assert accepted.status_code == 202

    # 3. The background task has run by now (TestClient runs it before returning).
    detail = client.get(f"{DATASETS}/{dataset['id']}").json()
    assert detail["status"] == "ready", detail.get("status_message")
    assert detail["row_count_clean"] < detail["row_count_raw"]
    # The reproducibility fingerprint is a SHA-256 of the cleaned data, so a
    # later run on the same file can be shown to have produced the same result.
    fingerprint = detail["clean_data_sha256"]
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert int(fingerprint, 16) >= 0  # hexadecimal

    # 4. The report explains every change, and the numbers add up.
    report = client.get(f"{DATASETS}/{dataset['id']}/quality-report").json()
    assert report["conservation"]["ok"] is True
    assert (
        report["summary"]["rows_clean"] + report["summary"]["rows_excluded"]
        == report["summary"]["rows_raw"]
    )
    assert report["excluded_by_reason"]["exact_duplicate"] == 1
    assert report["excluded_by_reason"]["non_product_code"] == 1
    assert report["excluded_by_reason"]["non_positive_price"] == 1
    assert report["excluded_by_reason"]["invalid_value"] == 1
    assert report["summary"]["rows_returns_flagged"] == 1
    assert report["summary"]["rows_guest"] == 1

    # 5. Capabilities follow from the mapping: no category column, no category analysis.
    capabilities = {c["key"]: c["enabled"] for c in report["capabilities"]}
    assert capabilities["sales_analytics"] is True
    assert capabilities["segmentation"] is True
    assert capabilities["category_analysis"] is False


def test_processing_a_file_with_too_little_data_fails_with_a_reason(registered_client):
    client, _, _ = registered_client
    csv_text = (
        "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country\n"
        "1,SYN-001,ITEM,1,2024-01-01 09:00:00,3.00,501,United Kingdom\n"
        "2,SYN-001,ITEM,1,2024-01-02 09:00:00,3.00,501,United Kingdom\n"
    )
    created = client.post(
        DATASETS,
        files={"file": ("tiny.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        data={"is_synthetic": "true"},
    ).json()

    client.post(
        f"{DATASETS}/{created['id']}/process",
        json={"mapping": created["profile"]["suggested_mapping"], "options": {}},
    )

    detail = client.get(f"{DATASETS}/{created['id']}").json()
    assert detail["status"] == "failed"
    assert "usable rows" in detail["status_message"] or "weeks" in detail["status_message"]