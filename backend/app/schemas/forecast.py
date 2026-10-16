"""Request and response models for the forecasting endpoints.

The request model is where an impossible experiment is rejected cheaply -
before a background task is queued, a row is written, and the user is told to
poll for something that was never going to work. Pydantic does the range
checks; `forecast_service.validate_request` does the ones that need the
registry (is this model name real, is its library installed).

Responses stay `dict[str, Any]` for the same reason the analytics ones do: the
payloads are nested, assembled by the service in the shape the frontend wants,
and re-declaring them here would create a second place to keep in step for no
validation benefit.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.forecasting.evaluate import PRIMARY_METRIC


class ForecastRunRequest(BaseModel):
    """Declare an experiment.

    Every default here is the architecture's default, so the plain `POST` with
    an empty body runs the protocol the report describes.
    """

    horizon: Annotated[int, Field(ge=1, le=52)] = 12
    folds: Annotated[int, Field(ge=1, le=10)] = 4
    season_length: Annotated[int, Field(ge=1, le=366)] = 52
    granularity: Literal["day", "week", "month"] = "week"
    value_column: Literal["net_revenue", "gross_revenue", "units", "orders"] = "net_revenue"
    window_style: Literal["expanding", "sliding"] = "expanding"
    primary_metric: Literal["WAPE", "MASE", "MAE", "RMSE", "MAPE", "sMAPE"] = PRIMARY_METRIC

    models: list[str] = Field(
        default_factory=list,
        description="Model names from /forecast/models. Empty means the default ladder.",
    )
    combination_rule: Literal["median", "mean", "trimmed_mean"] = "median"
    combination_members: list[str] = Field(default_factory=list)

    @field_validator("models", "combination_members")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        """Duplicates would fit a model twice and give it two votes in the
        combination, which is a silent way to weight it."""
        return sorted(set(value))


class ForecastRunAccepted(BaseModel):
    """202 response: the run exists, the work has not finished."""

    id: str
    status: str
    poll: str = Field(description="Where to check progress.")
    message: str = (
        "The experiment has been queued. Poll the URL in `poll` until status is "
        "'ready' or 'failed'."
    )
