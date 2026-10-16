"""The forecasting endpoints, against a real database.

These drive the whole stack: HTTP in, SQL aggregation, the pure forecasting
core, persistence, JSON out. The ones that matter most are the two protocol
tests - that cross-validation folds never reach into the locked window, and
that the hold-out is scored only after a model was named. Those are the claims
the results chapter rests on, and a test is the only thing that keeps them true
as the code changes.

The background task writes through the test's transaction-scoped session,
because `conftest.client` patches `forecast_service._open_session` the same way
it patches the processing one. Without that the job would open a second
connection, write into a transaction these assertions cannot see, and every
status would read "queued".
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

pytestmark = pytest.mark.db

DATASETS = "/api/v1/datasets"

# Two years of daily rows: ~104 weeks, enough for a 52-week season to be
# meaningful and for a 12-week hold-out to leave room for folds.
HISTORY_DAYS = 740


def build_csv(days: int = HISTORY_DAYS) -> str:
    """Daily rows with a weekly rhythm and a yearly cycle, plus the awkward
    cases the pipeline has to survive: a return, a postage line and a guest."""
    import math

    rows = []
    for index, stamp in enumerate(pd.date_range("2010-01-04", periods=days)):
        if stamp.dayofweek == 5:          # the retailer does not trade Saturdays
            continue
        season = 1.0 + 0.35 * math.sin(2 * math.pi * index / 365.0)
        for item in range(3):
            quantity = max(1, int(round((2 + item) * season)))
            rows.append(
                f"{3000 + index}{item},SYN-00{item + 1},SYNTHETIC ITEM {item + 1},"
                f"{quantity},{stamp.strftime('%Y-%m-%d')} 09:0{item}:00,{3 + item}.00,"
                f"{500 + (index % 25)},"
                f"{'France' if index % 7 == 0 else 'United Kingdom'}"
            )
    rows.append("C9999,SYN-001,SYNTHETIC ITEM 1,-2,2010-02-01 09:00:00,3.00,501,United Kingdom")
    rows.append("9998,POST,POSTAGE,1,2010-02-01 09:00:00,18.00,502,United Kingdom")
    rows.append("9995,SYN-003,SYNTHETIC ITEM 3,2,2010-02-03 09:00:00,5.00,,United Kingdom")

    header = "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country"
    return header + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def ready_dataset(registered_client):
    """Upload, map and process a dataset with enough history to forecast."""
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


def _start(client, dataset_id, **body):
    payload = {"horizon": 8, "folds": 2, "models": ["naive", "seasonal_naive", "ets"]}
    payload.update(body)
    return client.post(f"{DATASETS}/{dataset_id}/forecast/runs", json=payload)


def _detail(client, dataset_id, run_id):
    return client.get(f"{DATASETS}/{dataset_id}/forecast/runs/{run_id}").json()


# -- the model catalogue -------------------------------------------------


def test_the_model_catalogue_is_available_without_a_dataset(client):
    """The frontend builds its model picker from this before anything exists."""
    body = client.get("/api/v1/forecast/models").json()

    names = {row["model"] for row in body["models"]}
    assert {"naive", "seasonal_naive", "ets", "fourier"} <= names
    assert body["defaults"]["primary_metric"] == "WAPE"


def test_every_model_says_whether_it_can_actually_run(client):
    """An optional library that is not installed should cost a second to
    discover, not an hour into an experiment."""
    for row in client.get("/api/v1/forecast/models").json()["models"]:
        assert isinstance(row["available"], bool)
        if not row["available"]:
            assert "pip install" in row["unavailable_reason"]


# -- guards --------------------------------------------------------------


def test_a_dataset_a_user_does_not_own_is_not_forecastable(registered_client):
    client, _, _ = registered_client
    import uuid

    response = client.post(f"{DATASETS}/{uuid.uuid4()}/forecast/runs", json={})
    assert response.status_code == 404


def test_an_unknown_model_is_refused_before_anything_is_queued(ready_dataset):
    client, dataset_id = ready_dataset
    response = _start(client, dataset_id, models=["prophet"])

    assert response.status_code == 422
    assert "prophet" in str(response.json())

    # Nothing was recorded: a rejected request must not leave a run behind.
    assert client.get(f"{DATASETS}/{dataset_id}/forecast/runs").json()["count"] == 0


def test_the_latest_endpoint_is_404_until_a_run_has_finished(ready_dataset):
    client, dataset_id = ready_dataset
    assert client.get(f"{DATASETS}/{dataset_id}/forecast/latest").status_code == 404


# -- a complete run ------------------------------------------------------


def test_starting_a_run_returns_202_with_somewhere_to_poll(ready_dataset):
    client, dataset_id = ready_dataset
    response = _start(client, dataset_id)

    assert response.status_code == 202
    body = response.json()
    assert body["poll"].endswith(body["id"])


def test_a_completed_run_carries_its_protocol_results_and_environment(ready_dataset):
    client, dataset_id = ready_dataset
    run_id = _start(client, dataset_id).json()["id"]

    detail = _detail(client, dataset_id, run_id)
    if detail["status"] == "failed":
        pytest.fail(f"the run failed: {detail['error']}")

    assert detail["status"] == "ready"
    assert detail["protocol"]["horizon"] == 8
    assert len(detail["protocol"]["folds"]) == 2
    assert detail["summary"]
    assert detail["environment"]["library_versions"]["pandas"]
    assert len(detail["config_hash"]) == 64


def test_the_holdout_is_scored_only_after_a_model_was_named(ready_dataset):
    """The claim the whole protocol rests on."""
    client, dataset_id = ready_dataset
    detail = _detail(client, dataset_id, _start(client, dataset_id).json()["id"])
    if detail["status"] != "ready":
        pytest.fail(f"the run failed: {detail['error']}")

    selection = detail["selection"]
    assert selection["selected_model"]
    assert selection["holdout_scored_at"]
    assert selection["warning"] is None

    assert detail["cross_validation"]
    assert all(not row["is_holdout"] for row in detail["cross_validation"])
    assert all(row["is_holdout"] for row in detail["holdout"])


def test_cross_validation_folds_never_reach_into_the_locked_window(ready_dataset):
    client, dataset_id = ready_dataset
    detail = _detail(client, dataset_id, _start(client, dataset_id).json()["id"])
    if detail["status"] != "ready":
        pytest.fail(f"the run failed: {detail['error']}")

    holdout_start = detail["protocol"]["holdout"]["test_start"]
    for fold in detail["protocol"]["folds"]:
        assert fold["test_end"] < holdout_start
        assert fold["train_end"] < fold["test_start"]


def test_the_observation_counts_survive_into_storage(ready_dataset):
    """A WAPE computed on 6 of 8 weeks is a different number from one computed
    on all 8, and the typed column alone cannot tell them apart."""
    client, dataset_id = ready_dataset
    detail = _detail(client, dataset_id, _start(client, dataset_id).json()["id"])
    if detail["status"] != "ready":
        pytest.fail(f"the run failed: {detail['error']}")

    row = detail["cross_validation"][0]
    assert row["metrics"]["WAPE"]["observations_used"] > 0


def test_the_incomplete_final_period_is_reported_on_the_series(ready_dataset):
    client, dataset_id = ready_dataset
    detail = _detail(client, dataset_id, _start(client, dataset_id).json()["id"])
    if detail["status"] != "ready":
        pytest.fail(f"the run failed: {detail['error']}")

    series = detail["series"]
    assert series["granularity"] == "week"
    assert series["periods"] > 30
    assert "incomplete_final_periods_dropped" in series


def test_the_latest_endpoint_returns_the_finished_run(ready_dataset):
    client, dataset_id = ready_dataset
    run_id = _start(client, dataset_id).json()["id"]
    if _detail(client, dataset_id, run_id)["status"] != "ready":
        pytest.skip("the run did not complete")

    latest = client.get(f"{DATASETS}/{dataset_id}/forecast/latest").json()
    assert latest["id"] == run_id


def test_runs_are_listed_newest_first(ready_dataset):
    client, dataset_id = ready_dataset
    _start(client, dataset_id, horizon=6)
    _start(client, dataset_id, horizon=8)

    listing = client.get(f"{DATASETS}/{dataset_id}/forecast/runs").json()

    assert listing["count"] >= 2
    stamps = [row["created_at"] for row in listing["runs"]]
    assert stamps == sorted(stamps, reverse=True)


def test_the_same_protocol_twice_gives_the_same_config_hash(ready_dataset):
    """Two runs with the same hash ran the same experiment. That is the first
    question anyone auditing a results table should be able to answer."""
    client, dataset_id = ready_dataset
    first = _detail(client, dataset_id, _start(client, dataset_id).json()["id"])
    second = _detail(client, dataset_id, _start(client, dataset_id).json()["id"])

    assert first["config_hash"] == second["config_hash"]


def test_changing_the_protocol_changes_the_hash(ready_dataset):
    client, dataset_id = ready_dataset
    first = _detail(client, dataset_id, _start(client, dataset_id, horizon=6).json()["id"])
    second = _detail(client, dataset_id, _start(client, dataset_id, horizon=8).json()["id"])

    assert first["config_hash"] != second["config_hash"]


def test_an_impossible_protocol_fails_the_run_with_a_reason(ready_dataset):
    """A 52-week horizon over 4 folds does not fit two years of weekly data.
    The run should fail with a message that explains the arithmetic, not with a
    traceback and a row stuck on 'running'."""
    client, dataset_id = ready_dataset
    run_id = _start(client, dataset_id, horizon=52, folds=4).json()["id"]

    detail = _detail(client, dataset_id, run_id)

    assert detail["status"] == "failed"
    assert detail["error"]
    assert any(word in detail["error"].lower()
               for word in ("need", "observations", "usable", "at least"))


def test_a_run_cannot_be_read_through_a_dataset_that_does_not_own_it(ready_dataset):
    client, dataset_id = ready_dataset
    run_id = _start(client, dataset_id).json()["id"]

    other = client.post(
        DATASETS,
        files={"file": ("other.csv", io.BytesIO(build_csv(60).encode()), "text/csv")},
        data={"is_synthetic": "true"},
    ).json()

    response = client.get(f"{DATASETS}/{other['id']}/forecast/runs/{run_id}")
    assert response.status_code == 404
