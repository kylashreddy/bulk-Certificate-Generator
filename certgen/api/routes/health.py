"""Health endpoint at /healthz (outside /api/v1: it is for load balancers and
docker healthchecks, not API clients, and must not change between API versions)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from certgen.api.dependencies import get_session
from certgen.services.health_check import database_is_reachable

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    if database_is_reachable(session):
        return JSONResponse({"status": "ok", "database": "ok"})
    return JSONResponse({"status": "degraded", "database": "unreachable"}, status_code=503)
