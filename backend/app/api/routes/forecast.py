"""Forecasting endpoints (architecture §9.2, §13).

    GET  /forecast/models                      what this server can run
    POST /datasets/{id}/forecast/runs          -> 202, the experiment starts
    GET  /datasets/{id}/forecast/runs          recent runs, newest first
    GET  /datasets/{id}/forecast/runs/{run_id} the full result
    GET  /datasets/{id}/forecast/latest        the newest ready run, for the dashboard

The 202-and-poll shape is the same as dataset processing, and for the same
reason: a ladder of models over several folds is not something to hold an HTTP
connection open for. The response carries the URL to poll, so the client does
not have to assemble it.

`/forecast/models` is deliberately outside the dataset prefix and needs no
dataset: the frontend asks it once to build the model picker, and a missing
optional library should be visible before anyone chooses a model that cannot
run.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api.deps import DbSession, OwnedDataset
from app.core.errors import NotFound
from app.db.repositories import forecasts as repo
from app.schemas.forecast import ForecastRunAccepted, ForecastRunRequest
from app.services import forecast_service
from app.services.forecast_service import execute_run

router = APIRouter(tags=["forecasting"])


@router.get("/forecast/models", summary="Models this server can run")
def models() -> dict[str, Any]:
    """Which models are registered, and which cannot run here and why.

    Asked before a run rather than discovered during one: an optional library
    that is not installed should cost a second, not an hour.
    """
    return forecast_service.available_model_list()


@router.post(
    "/datasets/{dataset_id}/forecast/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ForecastRunAccepted,
    summary="Start a forecasting experiment",
)
def start_run(
    dataset: OwnedDataset,
    session: DbSession,
    background: BackgroundTasks,
    request: ForecastRunRequest | None = None,
) -> ForecastRunAccepted:
    """202 Accepted: the run is recorded and queued, not finished.

    An empty body runs the protocol the architecture declares, so the common
    case needs no parameters at all.
    """
    options = request or ForecastRunRequest()
    run = forecast_service.start_run(
        session, dataset,
        horizon=options.horizon,
        folds=options.folds,
        season_length=options.season_length,
        granularity=options.granularity,
        value_column=options.value_column,
        window_style=options.window_style,
        models=options.models or None,
        combination_rule=options.combination_rule,
        combination_members=options.combination_members or None,
        primary_metric=options.primary_metric,
    )
    # The session commits when the request returns; the task must not start
    # before the row is visible to the new session it will open.
    session.commit()
    background.add_task(execute_run, run.id)

    return ForecastRunAccepted(
        id=str(run.id),
        status=run.status,
        poll=f"/api/v1/datasets/{dataset.id}/forecast/runs/{run.id}",
    )


@router.get("/datasets/{dataset_id}/forecast/runs", summary="Recent runs, newest first")
def list_runs(
    dataset: OwnedDataset,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    return forecast_service.list_runs(session, dataset, limit=limit)


@router.get(
    "/datasets/{dataset_id}/forecast/runs/{run_id}",
    summary="One run: protocol, results, significance and environment",
)
def get_run(dataset: OwnedDataset, session: DbSession, run_id: uuid.UUID) -> dict[str, Any]:
    """Also the polling endpoint: `status` is 'queued', 'running', 'ready' or 'failed'."""
    run = forecast_service.get_run_or_404(session, dataset, run_id)
    return forecast_service.run_detail(session, run)


@router.get(
    "/datasets/{dataset_id}/forecast/latest",
    summary="The most recent finished run, for the dashboard",
)
def latest(
    dataset: OwnedDataset,
    session: DbSession,
    series_key: str | None = None,
) -> dict[str, Any]:
    run = repo.latest_ready_run(session, dataset.id, series_key)
    if run is None:
        raise NotFound(
            "No finished forecast run for this dataset yet. Start one with "
            "POST /forecast/runs."
        )
    return forecast_service.run_detail(session, run)
