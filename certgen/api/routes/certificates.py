"""Certificate endpoints: metadata, PDF download, and public verification."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from certgen.api.content_disposition import attachment_header
from certgen.api.dependencies import get_session, get_storage
from certgen.api.presenters import present_certificate_detail
from certgen.schemas.certificate_views import CertificateDetail, VerificationResult
from certgen.schemas.error_envelope import ErrorEnvelope
from certgen.services.certificate_queries import (
    find_issued_by_verification_code,
    get_certificate,
    load_issued_pdf,
)
from certgen.storage.protocol import CertificateStorage

router = APIRouter(tags=["certificates"])

NOT_FOUND: dict[int | str, dict[str, object]] = {404: {"model": ErrorEnvelope}}


@router.get("/certificates/{certificate_id}", response_model=CertificateDetail, responses=NOT_FOUND)
def read_certificate(
    certificate_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> CertificateDetail:
    return present_certificate_detail(get_certificate(session, certificate_id))


@router.get(
    "/certificates/{certificate_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, **NOT_FOUND},
)
def download_certificate_pdf(
    certificate_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[CertificateStorage, Depends(get_storage)],
) -> Response:
    issued = load_issued_pdf(session, storage, certificate_id)
    serial = issued.certificate.serial or str(certificate_id)
    return Response(
        content=issued.pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": attachment_header(issued.certificate.recipient_name, serial)
        },
    )


@router.get("/verify/{verification_code}", response_model=VerificationResult, responses=NOT_FOUND)
def verify_certificate(
    verification_code: str, session: Annotated[Session, Depends(get_session)]
) -> VerificationResult:
    """The QR code on every certificate points here. Only issued certificates verify;
    the response deliberately omits the email address because this URL is public."""
    certificate, job = find_issued_by_verification_code(session, verification_code)
    return VerificationResult(
        valid=True,
        serial=certificate.serial or "",
        recipient_name=certificate.recipient_name,
        title=job.title,
        issuer_name=job.issuer_name,
        issued_on=job.issued_on,
    )
