"""The outlook endpoint, against a real database: HTTP in, SQL, the pure core, JSON out."""

from __future__ import annotations

import pandas as pd
import pytest

from tests.api.test_forecast import DATASETS, ready_dataset  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def test_the_outlook_forecasts_past_the_last_complete_week(ready_dataset):  # noqa: F811
    client, dataset_id = ready_dataset
    response = client.get(f"{DATASETS}/{dataset_id}/forecast/outlook", params={"products": 3})
    assert response.status_code == 200
    body = response.json()

    assert body["available"] is True
    revenue = body["measures"]["net_revenue"]
    assert revenue["available"] is True
    last = pd.Timestamp(body["series"]["last_period"])
    first_forecast = pd.Timestamp(revenue["forecast"]["periods"][0])
    assert first_forecast == last + pd.Timedelta(weeks=1)
    assert len(revenue["forecast"]["point"]) == 12

    chosen = [c for c in revenue["candidates"] if c["chosen"]]
    assert len(chosen) == 1 and chosen[0]["name"] == revenue["model"]["name"]
    assert body["measures"]["net_units"]["available"] is True


def test_the_outlook_includes_top_products_with_descriptions(ready_dataset):  # noqa: F811
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/forecast/outlook", params={"products": 3}
    ).json()
    rows = body["products"]["rows"]
    assert 1 <= len(rows) <= 3
    assert all(r["description"] and r["description"].startswith("SYNTHETIC") for r in rows)
    assert all(r["next_horizon_units"] >= 0 for r in rows)


def test_a_second_request_is_served_from_the_cache(ready_dataset):  # noqa: F811
    client, dataset_id = ready_dataset
    url = f"{DATASETS}/{dataset_id}/forecast/outlook"
    first = client.get(url).json()
    second = client.get(url).json()
    assert first["_cache"]["hit"] is False
    assert second["_cache"]["hit"] is True
    revenue = "net_revenue"
    assert second["measures"][revenue]["forecast"] == first["measures"][revenue]["forecast"]


def test_an_out_of_range_horizon_is_refused(ready_dataset):  # noqa: F811
    client, dataset_id = ready_dataset
    response = client.get(f"{DATASETS}/{dataset_id}/forecast/outlook", params={"horizon": 99})
    assert response.status_code == 422


def test_the_outlook_needs_a_login(client):
    response = client.get(
        f"{DATASETS}/00000000-0000-0000-0000-000000000000/forecast/outlook"
    )
    assert response.status_code == 401
