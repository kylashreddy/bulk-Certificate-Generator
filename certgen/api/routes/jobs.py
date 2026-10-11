"""Job endpoints. Each handler: parse input -> call one service -> present the result."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from certgen.api.dependencies import (
    get_dispatcher,
    get_session,
    get_settings_dependency,
    get_storage,
)
from certgen.api.presenters import (
    job_url,
    present_certificate_summary,
    present_job_created,
    present_job_status,
)
from certgen.config import Settings
from certgen.dispatch.dispatchers import Dispatcher
from certgen.domain.statuses import CertificateStatus
from certgen.schemas.certificate_views import CertificatePage
from certgen.schemas.error_envelope import ErrorEnvelope
from certgen.schemas.job_requests import CreateJobRequest
from certgen.schemas.job_responses import JobCreated, JobRetried, JobStatusView
from certgen.services.archive_export import snapshot_job_archive, stream_job_archive
from certgen.services.certificate_queries import get_job, list_job_certificates
from certgen.services.job_creation import create_job
from certgen.services.job_progress import load_job_progress
from certgen.services.job_retry import requeue_failed_certificates
from certgen.storage.protocol import CertificateStorage

router = APIRouter(prefix="/jobs", tags=["jobs"])

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobCreated,
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
def submit_job(
    request: CreateJobRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
    strict: Annotated[
        bool, Query(description="Reject the whole request if any row is invalid")
    ] = False,
) -> JobCreated:
    result = create_job(
        session,
        request,
        idempotency_key=idempotency_key,
        strict=strict,
        max_recipients=settings.max_recipients_per_job,
    )
    created = present_job_created(result)
    response.headers["Location"] = job_url(result.job.id)
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    else:
        # Dispatch only after the commit inside create_job, so a worker can never
        # look for rows that are not yet visible.
        dispatcher.submit(result.job.id)
    return created


@router.get("/{job_id}", response_model=JobStatusView, responses=ERROR_RESPONSES)
def read_job_status(
    job_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> JobStatusView:
    job = get_job(session, job_id)
    return present_job_status(job, load_job_progress(session, job_id))


@router.get("/{job_id}/certificates", response_model=CertificatePage, responses=ERROR_RESPONSES)
def list_certificates(
    job_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[CertificateStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: str | None = None,
) -> CertificatePage:
    page = list_job_certificates(session, job_id, status=status_filter, limit=limit, cursor=cursor)
    return CertificatePage(
        items=[present_certificate_summary(certificate) for certificate in page.certificates],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{job_id}/archive.zip",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}}, **ERROR_RESPONSES},
)
def download_archive(
    job_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[CertificateStorage, Depends(get_storage)],
) -> StreamingResponse:
    snapshot = snapshot_job_archive(session, job_id)
    return StreamingResponse(
        stream_job_archive(snapshot, storage),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job_id}.zip"'},
    )


@router.post(
    "/{job_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobRetried,
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
def retry_failed(
    job_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> JobRetried:
    requeued_count = requeue_failed_certificates(session, job_id)
    dispatcher.submit(job_id)
    return JobRetried(
        job_id=job_id, status=get_job(session, job_id).status, requeued_count=requeued_count
    )
