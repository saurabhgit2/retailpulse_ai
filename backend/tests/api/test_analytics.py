"""The analytics endpoints, against a real database.

These drive the whole stack: HTTP in, SQL aggregation, pure analytics, JSON out.
They are the tests that would catch a mismatch between what PostgreSQL buckets
and what pandas expects - the week-alignment trap in particular.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

pytestmark = pytest.mark.db

DATASETS = "/api/v1/datasets"


def build_csv(days: int = 400) -> str:
    """Enough history for weekly analysis, with returns, guests and postage."""
    rows = []
    for index, day in enumerate(pd.date_range("2024-01-01", periods=days).strftime("%Y-%m-%d")):
        for item in range(3):
            rows.append(
                f"{3000 + index}{item},SYN-00{item + 1},SYNTHETIC ITEM {item + 1},"
                f"{2 + item},{day} 09:0{item}:00,{3 + item}.00,"
                f"{500 + (index % 25)},{'France' if index % 7 == 0 else 'United Kingdom'}"
            )
    rows.append("C9999,SYN-001,SYNTHETIC ITEM 1,-2,2024-02-01 09:00:00,3.00,501,United Kingdom")
    rows.append("9998,POST,POSTAGE,1,2024-02-01 09:00:00,18.00,502,United Kingdom")
    rows.append("9995,SYN-003,SYNTHETIC ITEM 3,2,2024-02-03 09:00:00,5.00,,United Kingdom")

    header = "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country"
    return header + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def ready_dataset(registered_client):
    """Upload, map and process a dataset so analytics have something to read."""
    client, _, _ = registered_client
    created = client.post(
        DATASETS,
        files={"file": ("synthetic.csv", io.BytesIO(build_csv().encode()), "text/csv")},
        data={"is_synthetic": "true"},
    ).json()

    accepted = client.post(
        f"{DATASETS}/{created['id']}/process",
        json={"mapping": created["profile"]["suggested_mapping"], "options": {}},
    )
    assert accepted.status_code == 202

    detail = client.get(f"{DATASETS}/{created['id']}").json()
    assert detail["status"] == "ready", detail.get("status_message")
    return client, created["id"]


def test_filter_options_describe_the_data(ready_dataset):
    client, dataset_id = ready_dataset
    options = client.get(f"{DATASETS}/{dataset_id}/filter-options").json()

    assert options["rows"] > 0
    assert options["date_min"] and options["date_max"]
    assert {region["value"] for region in options["regions"]} >= {"United Kingdom", "France"}
    assert options["top_products"]
    assert options["customer_types"] == ["all", "registered", "guest"]


def test_kpis_follow_the_definitions(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/kpis").json()
    values = body["values"]

    assert values["gross_revenue"] > 0
    assert values["net_revenue"] == pytest.approx(
        values["gross_revenue"] - values["returns_value"]
    )
    assert values["average_order_value"] == pytest.approx(
        values["gross_revenue"] / values["orders"]
    )
    # No date range was given, so there is nothing to compare against.
    assert body["comparison"]["comparable"] is False
    assert body["comparison"]["note"]


def test_filters_narrow_the_result(ready_dataset):
    client, dataset_id = ready_dataset
    everything = client.get(f"{DATASETS}/{dataset_id}/analytics/kpis").json()
    france = client.get(
        f"{DATASETS}/{dataset_id}/analytics/kpis", params={"regions": "France"}
    ).json()

    assert 0 < france["values"]["gross_revenue"] < everything["values"]["gross_revenue"]


def test_guest_and_registered_split_adds_up(ready_dataset):
    client, dataset_id = ready_dataset
    url = f"{DATASETS}/{dataset_id}/analytics/kpis"
    everything = client.get(url).json()["values"]["gross_revenue"]
    guests = client.get(url, params={"customer_type": "guest"}).json()["values"]["gross_revenue"]
    registered = client.get(
        url, params={"customer_type": "registered"}
    ).json()["values"]["gross_revenue"]

    assert guests + registered == pytest.approx(everything)


def test_weekly_trends_line_up_with_the_database_buckets(ready_dataset):
    """PostgreSQL's date_trunc('week') starts weeks on Monday. If the pandas
    side disagreed, the reindex would replace every value with a zero."""
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/analytics/trends", params={"granularity": "week"}
    ).json()

    assert body["points"]
    assert any(point["gross_revenue"] > 0 for point in body["points"])
    assert all(
        pd.Timestamp(point["period"]).day_name() == "Monday" for point in body["points"]
    )


def test_a_moving_average_appears_once_the_window_is_full(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/analytics/trends", params={"ma_window": 4}
    ).json()

    assert body["points"][0]["moving_average"] is None
    assert any(point["moving_average"] is not None for point in body["points"])


def test_product_ranking_shares_sum_with_the_remainder(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/analytics/products", params={"limit": 2}
    ).json()

    assert body["items"]
    assert body["items"][0]["share"] >= body["items"][-1]["share"]
    if body["others"]:
        assert body["items"][-1]["cumulative_share"] + body["others"]["share"] == pytest.approx(1.0)


def test_categories_are_refused_when_the_dataset_has_none(ready_dataset):
    """Online Retail II has no category column, so this must be a clear 409
    rather than an empty chart."""
    client, dataset_id = ready_dataset
    response = client.get(f"{DATASETS}/{dataset_id}/analytics/categories")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAPABILITY_UNAVAILABLE"


def test_distributions_report_shape_and_outliers(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/analytics/distributions",
        params={"field": "order_value", "bins": 20},
    ).json()

    assert body["count"] > 0
    assert len(body["histogram"]["counts"]) == 20
    assert body["summary"]["median"] > 0
    assert "never removed" in body["outliers"]["note"]


def test_an_unknown_distribution_field_is_rejected(ready_dataset):
    client, dataset_id = ready_dataset
    response = client.get(
        f"{DATASETS}/{dataset_id}/analytics/distributions", params={"field": "profit"}
    )
    assert response.status_code == 422


def test_seasonality_returns_calendar_indices(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/seasonality").json()

    assert len(body["calendar"]["day_of_week"]) == 7
    assert "decomposition" in body


def test_statistics_compare_groups_without_assuming_normality(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/analytics/statistics",
        params={"group": "customer_type", "value": "order_value"},
    ).json()

    assert body["descriptive"]["n"] > 0
    if body["comparison"]["test"]:
        assert body["comparison"]["test"]["name"] in {"Mann-Whitney U", "Kruskal-Wallis H"}
        assert "effect_size" in body["comparison"]["test"]
    # ADF/KPSS belong with the forecasting work, and say so.
    assert body["stationarity"]["available"] is False


def test_relationships_never_report_a_bare_elasticity(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/relationships").json()

    assert "correlations" in body
    assert "not causation" in body["correlations"]["note"]
    if body["price_quantity"].get("available"):
        assert body["price_quantity"]["caveats"]


def test_feature_analysis_reports_bin_sensitivity_and_limitations(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/features").json()

    if body.get("available"):
        assert body["features"]
        assert "mi_by_bins" in body["features"][0]
        assert body["model_importance"] is None
        assert len(body["limitations"]) >= 4
    else:
        assert body["reason"]


def test_series_profiles_classify_demand_patterns(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(
        f"{DATASETS}/{dataset_id}/analytics/series-profile", params={"min_periods": 26}
    ).json()

    if body.get("series"):
        first = body["series"][0]
        assert first["intermittency_class"] in {"smooth", "erratic", "intermittent", "lumpy"}
        assert "adi" in first and "spectral_entropy" in first


def test_anomalies_explain_themselves(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/anomalies").json()

    assert "basis" in body
    for anomaly in body.get("anomalies", []):
        assert "robust standard deviations" in anomaly["explanation"]


def test_an_expensive_analysis_is_served_from_the_cache_the_second_time(ready_dataset):
    client, dataset_id = ready_dataset
    url = f"{DATASETS}/{dataset_id}/analytics/distributions"

    first = client.get(url).json()
    second = client.get(url).json()

    assert first["_cache"]["hit"] is False
    assert second["_cache"]["hit"] is True
    assert second["count"] == first["count"]


def test_different_filters_do_not_share_a_cache_entry(ready_dataset):
    client, dataset_id = ready_dataset
    url = f"{DATASETS}/{dataset_id}/analytics/distributions"

    client.get(url)
    narrowed = client.get(url, params={"regions": "France"}).json()

    assert narrowed["_cache"]["hit"] is False


def test_analytics_are_refused_until_the_dataset_is_ready(registered_client):
    client, _, _ = registered_client
    created = client.post(
        DATASETS,
        files={"file": ("synthetic.csv", io.BytesIO(build_csv(30).encode()), "text/csv")},
        data={"is_synthetic": "true"},
    ).json()

    response = client.get(f"{DATASETS}/{created['id']}/analytics/kpis")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_NOT_READY"


def test_another_users_dataset_is_not_found_rather_than_forbidden(ready_dataset, client):
    """404 not 403: a 403 would confirm the dataset exists."""
    _, dataset_id = ready_dataset

    client.post(
        "/api/v1/auth/register",
        json={"email": "someone-else@example.com", "password": "a long test passphrase",
              "full_name": "Other"},
    )
    token = client.post(
        "/api/v1/auth/login",
        data={"username": "someone-else@example.com", "password": "a long test passphrase"},
    ).json()["access_token"]

    response = client.get(
        f"{DATASETS}/{dataset_id}/analytics/kpis",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_analytics_require_authentication(ready_dataset, client):
    _, dataset_id = ready_dataset
    assert client.get(f"{DATASETS}/{dataset_id}/analytics/kpis").status_code == 401


def test_rfm_aggregates_the_three_variables_per_customer(ready_dataset):
    """Chen, Sain & Guo (2012) aggregate Recency, Frequency and Monetary per
    customer as the input to clustering. This is that aggregation."""
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/rfm").json()

    assert body["available"] is True
    assert body["customers"] > 0
    assert set(body["distributions"]) == {"recency_days", "frequency", "monetary"}
    assert body["frequency_definition"] == "distinct invoices"
    assert sum(group["customers"] for group in body["segments"]) == body["customers"]


def test_rfm_reports_how_much_revenue_it_cannot_see(ready_dataset):
    """Guest sales have no customer ID, so RFM excludes them. The share is
    reported next to the segments rather than quietly dropped."""
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/rfm").json()

    assert "coverage" in body
    assert body["coverage"]["guest_revenue"] >= 0
    assert body["coverage"]["guest_revenue_share"] is not None


def test_rfm_carries_the_clustering_caveats_into_phase_5b(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/rfm").json()

    assert any("standardised" in note for note in body["clustering_notes"])
    assert any("RQ2" in caveat for caveat in body["caveats"])


def test_basket_size_is_reported_with_its_interpretation(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/baskets").json()

    assert body["available"] is True
    assert body["invoices"] > 0
    assert body["distinct_items_per_invoice"]["summary"]["mean"] > 0
    assert "transaction" in body["interpretation"]


def test_seasonality_exposes_a_deseasonalised_series_for_phase_5(ready_dataset):
    client, dataset_id = ready_dataset
    body = client.get(f"{DATASETS}/{dataset_id}/analytics/seasonality").json()
    decomposition = body["decomposition"]

    if decomposition.get("available"):
        assert "deseasonalised" in decomposition
        assert len(decomposition["deseasonalised"]) == len(decomposition["observed"])
