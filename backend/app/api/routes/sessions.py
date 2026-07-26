from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_auto_open_coordinator,
    get_jobs_service,
    get_session_service,
)
from app.api.serializers import job_response, session_response, session_summary_response
from app.jobs.service import JobsService
from app.platforms.facebook.auto_advance import AutoOpenCoordinator
from app.schemas.job import FetchJobsResponse
from app.schemas.session import (
    AccountWarningRequest,
    AutoOpenRequest,
    AutoOpenStatusResponse,
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


@router.get("/active", response_model=SessionResponse | None)
async def active_session(
    service: SessionService = Depends(get_session_service),
) -> SessionResponse | None:
    account = await service.get_local_account()
    session = await service.get_active(account.id)
    return session_response(session) if session is not None else None


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
    auto_open: AutoOpenCoordinator = Depends(get_auto_open_coordinator),
) -> SessionSummaryResponse:
    session, jobs = await service.summary(session_id)
    return session_summary_response(session, jobs, auto_open.status(session_id))


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


@router.post("/{session_id}/auto-open", response_model=AutoOpenStatusResponse)
async def set_auto_open(
    session_id: UUID,
    payload: AutoOpenRequest,
    coordinator: AutoOpenCoordinator = Depends(get_auto_open_coordinator),
) -> AutoOpenStatusResponse:
    return AutoOpenStatusResponse.model_validate(
        await coordinator.set_enabled(session_id, payload.enabled),
        from_attributes=True,
    )


@router.post(
    "/{session_id}/auto-open/pause",
    response_model=AutoOpenStatusResponse,
)
async def pause_auto_open(
    session_id: UUID,
    coordinator: AutoOpenCoordinator = Depends(get_auto_open_coordinator),
) -> AutoOpenStatusResponse:
    return AutoOpenStatusResponse.model_validate(
        await coordinator.pause(session_id),
        from_attributes=True,
    )


@router.post(
    "/{session_id}/auto-open/resume",
    response_model=AutoOpenStatusResponse,
)
async def resume_auto_open(
    session_id: UUID,
    coordinator: AutoOpenCoordinator = Depends(get_auto_open_coordinator),
) -> AutoOpenStatusResponse:
    return AutoOpenStatusResponse.model_validate(
        await coordinator.resume(session_id),
        from_attributes=True,
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
