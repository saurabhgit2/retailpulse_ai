"""Dataset endpoints: upload, mapping validation, ownership, deletion."""

from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.db

DATASETS = "/api/v1/datasets"

CSV = (
    "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country\n"
    "1001,85123A,WHITE MUG,2,2024-01-01 09:00:00,3.00,501,United Kingdom\n"
    "1002,22423,CAKE STAND,1,2024-01-02 09:00:00,12.75,502,France\n"
)


def upload(client, content: str = CSV, filename: str = "sales.csv", synthetic: bool = True):
    return client.post(
        DATASETS,
        files={"file": (filename, io.BytesIO(content.encode()), "text/csv")},
        data={"is_synthetic": str(synthetic).lower()},
    )


def test_upload_profiles_the_columns(registered_client):
    client, _, _ = registered_client
    response = upload(client)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "awaiting_mapping"
    assert body["is_synthetic"] is True
    assert body["file_sha256"]  # provenance: the stored file is hashed
    assert body["profile"]["suggested_mapping"]["occurred_at"] == "InvoiceDate"
    assert body["profile"]["preview"]["rows_examined"] == 2


def test_non_csv_uploads_are_refused(registered_client):
    client, _, _ = registered_client
    response = upload(client, content="not a csv", filename="notes.txt")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE"


def test_a_file_with_only_a_header_is_refused(registered_client):
    client, _, _ = registered_client
    response = upload(client, content="Invoice,InvoiceDate\n")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_processing_rejects_a_mapping_that_cannot_produce_revenue(registered_client):
    client, _, _ = registered_client
    dataset_id = upload(client).json()["id"]

    response = client.post(
        f"{DATASETS}/{dataset_id}/process",
        json={"mapping": {"occurred_at": "InvoiceDate", "quantity": "Quantity"}, "options": {}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_FIELD"


def test_processing_rejects_one_column_mapped_twice(registered_client):
    client, _, _ = registered_client
    dataset_id = upload(client).json()["id"]

    response = client.post(
        f"{DATASETS}/{dataset_id}/process",
        json={
            "mapping": {"occurred_at": "InvoiceDate", "quantity": "Quantity",
                        "unit_price": "Quantity"},
            "options": {},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DUPLICATE_MAPPING"


def test_the_report_is_a_conflict_until_the_dataset_is_ready(registered_client):
    client, _, _ = registered_client
    dataset_id = upload(client).json()["id"]

    response = client.get(f"{DATASETS}/{dataset_id}/quality-report")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_NOT_READY"


def test_another_users_dataset_looks_missing_not_forbidden(registered_client, client):
    owner_client, _, _ = registered_client
    dataset_id = upload(owner_client).json()["id"]

    # A second account, on the same TestClient app.
    client.post("/api/v1/auth/register",
                json={"email": "other@example.com", "password": "a long test passphrase"})
    token = client.post("/api/v1/auth/login",
                        data={"username": "other@example.com",
                              "password": "a long test passphrase"}).json()["access_token"]

    response = client.get(f"{DATASETS}/{dataset_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404  # not 403: the API does not confirm it exists


def test_list_and_delete(registered_client):
    client, _, _ = registered_client
    dataset_id = upload(client).json()["id"]

    listing = client.get(DATASETS).json()
    assert listing["total"] == 1
    assert "profile" not in listing["items"][0]  # the list stays small

    assert client.delete(f"{DATASETS}/{dataset_id}").status_code == 204
    assert client.get(f"{DATASETS}/{dataset_id}").status_code == 404


def test_field_guide_and_template_are_served(registered_client):
    client, _, _ = registered_client

    guide = client.get(f"{DATASETS}/field-guide").json()
    assert {"fields", "capabilities"} <= guide.keys()
    assert any(field["key"] == "occurred_at" for field in guide["fields"])

    template = client.get(f"{DATASETS}/template")
    assert template.status_code == 200
    assert template.text.startswith("invoice_id,occurred_at")
