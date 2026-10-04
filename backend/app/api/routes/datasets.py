"""Dataset endpoints: the upload wizard and the data-quality report.

The flow the frontend follows (architecture §11.1):

    POST /datasets                -> 201, file stored, columns profiled
    POST /datasets/{id}/process   -> 202, cleaning starts in the background
    GET  /datasets/{id}           -> poll until status is 'ready' or 'failed'
    GET  /datasets/{id}/quality-report
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Response, UploadFile, status
from fastapi.responses import PlainTextResponse

from app.api.deps import AppSettings, CurrentUser, DbSession, OwnedDataset
from app.db.repositories import datasets as dataset_repo
from app.preprocessing.field_guide import TEMPLATE_CSV, field_guide_document
from app.schemas.dataset import (
    DatasetDetail,
    DatasetList,
    DatasetSummary,
    ProcessAccepted,
    ProcessRequest,
)
from app.services import dataset_service
from app.services.processing_service import process_dataset

router = APIRouter(prefix="/datasets", tags=["datasets"])


# --- Static routes first -----------------------------------------------------
# These must be declared before /datasets/{dataset_id}, or "template" would be
# read as a dataset ID.

@router.get("/template", response_class=PlainTextResponse, summary="Recommended CSV template")
def download_template() -> PlainTextResponse:
    return PlainTextResponse(
        TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="retailpulse_template.csv"'},
    )


@router.get("/field-guide", summary="Canonical fields and capability rules")
def field_guide(_: CurrentUser) -> dict:
    """What RetailPulse understands, and what each analysis needs.

    The frontend only evaluates these rules, so a new field or a changed
    requirement is a one-file change on the server.
    """
    return field_guide_document()


# --- Collection --------------------------------------------------------------

@router.get("", response_model=DatasetList, summary="List my datasets")
def list_datasets(session: DbSession, user: CurrentUser) -> DatasetList:
    rows = dataset_repo.list_datasets(session, user.id)
    return DatasetList(
        items=[DatasetSummary.model_validate(row) for row in rows], total=len(rows)
    )


@router.post(
    "", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED, summary="Upload a CSV"
)
def upload_dataset(
    session: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    file: Annotated[UploadFile, File(description="CSV file of sales transactions")],
    is_synthetic: Annotated[bool, Form()] = False,
) -> DatasetDetail:
    """Step 1: store the file unchanged and profile its columns.

    Nothing is cleaned yet. The response carries the detected columns and a
    suggested mapping for the user to confirm.
    """
    dataset = dataset_service.create_dataset_from_upload(
        session,
        user=user,
        filename=file.filename,
        stream=file.file,
        is_synthetic=is_synthetic,
        settings=settings,
    )
    return DatasetDetail.model_validate(dataset)


# --- Single dataset ----------------------------------------------------------

@router.get("/{dataset_id}", response_model=DatasetDetail, summary="Dataset status and profile")
def get_dataset(dataset: OwnedDataset) -> DatasetDetail:
    return DatasetDetail.model_validate(dataset)


@router.post(
    "/{dataset_id}/process",
    response_model=ProcessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Confirm the mapping and start cleaning",
)
def process(
    dataset: OwnedDataset,
    payload: ProcessRequest,
    session: DbSession,
    background: BackgroundTasks,
) -> ProcessAccepted:
    """Step 2: validate the mapping, then clean in the background.

    202 Accepted means "I have taken this on" - not "it is done". Cleaning a
    million rows takes far longer than a browser will wait, so the client polls
    GET /datasets/{id} until the status is final.
    """
    options = payload.options.model_dump(exclude_none=True)
    dataset_service.prepare_processing(session, dataset, payload.mapping, options)

    # The task is queued now and runs after the response has been sent, so the
    # status is already 'processing' by the time the client sees it.
    session.commit()
    background.add_task(process_dataset, dataset.id)

    return ProcessAccepted(
        id=dataset.id, status=dataset.status, poll=f"/api/v1/datasets/{dataset.id}"
    )


@router.get("/{dataset_id}/quality-report", summary="What the cleaning pipeline did")
def quality_report(dataset: OwnedDataset) -> dict:
    return dataset_service.quality_report_or_conflict(dataset)


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # 204 means "done, and there is nothing to send back". FastAPI turns a
    # `-> None` return annotation into a response model, then refuses to build a
    # body for a 204, so the endpoint must be declared as returning a bare
    # Response instead.
    response_class=Response,
    summary="Delete a dataset",
)
def delete_dataset(dataset: OwnedDataset, session: DbSession) -> Response:
    """Deletes the stored file and, by cascade, every row derived from it."""
    dataset_service.delete_dataset(session, dataset)
    return Response(status_code=status.HTTP_204_NO_CONTENT)