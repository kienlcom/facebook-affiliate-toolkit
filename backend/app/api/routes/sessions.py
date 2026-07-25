from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_jobs_service, get_session_service
from app.api.serializers import job_response, session_response, session_summary_response
from app.jobs.service import JobsService
from app.schemas.job import FetchJobsResponse
from app.schemas.session import (
    AccountWarningRequest,
    CreateSessionRequest,
    SessionResponse,
    SessionSummaryResponse,
    StopSessionRequest,
)
from app.sessions.service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    account = await service.get_local_account()
    session = await service.create(account.id, payload.profile_key)
    return session_response(session)


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_session(
    session_id: UUID,
    payload: StopSessionRequest,
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    return session_response(await service.stop(session_id, payload.reason))


@router.get("/{session_id}/summary", response_model=SessionSummaryResponse)
async def session_summary(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
) -> SessionSummaryResponse:
    session, jobs = await service.summary(session_id)
    return session_summary_response(session, jobs)


@router.post("/{session_id}/fetch", response_model=FetchJobsResponse)
async def fetch_jobs(
    session_id: UUID,
    service: JobsService = Depends(get_jobs_service),
) -> FetchJobsResponse:
    jobs, duplicates_ignored = await service.fetch(session_id)
    return FetchJobsResponse(
        jobs=[job_response(job) for job in jobs],
        duplicates_ignored=duplicates_ignored,
    )


@router.post("/{session_id}/account-warning", response_model=SessionResponse)
async def account_warning(
    session_id: UUID,
    payload: AccountWarningRequest,
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = await service.mark_protection_stop(
        session_id,
        warning_type=payload.warning_type,
        note=payload.note,
    )
    return session_response(session)
