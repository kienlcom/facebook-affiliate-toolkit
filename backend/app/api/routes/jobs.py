from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_claim_service, get_jobs_service
from app.api.serializers import job_response
from app.claims.service import ClaimService
from app.jobs.service import JobsService
from app.schemas.claim import ClaimResponse
from app.schemas.job import JobActionResponse, SkipJobRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/{job_id}/opened", response_model=JobActionResponse)
async def opened(
    job_id: UUID,
    service: JobsService = Depends(get_jobs_service),
) -> JobActionResponse:
    return JobActionResponse(job=job_response(await service.mark_opened(job_id)))


@router.post("/{job_id}/confirm", response_model=JobActionResponse)
async def confirm(
    job_id: UUID,
    service: JobsService = Depends(get_jobs_service),
) -> JobActionResponse:
    return JobActionResponse(job=job_response(await service.confirm(job_id)))


@router.post("/{job_id}/skip", response_model=JobActionResponse)
async def skip(
    job_id: UUID,
    payload: SkipJobRequest,
    service: JobsService = Depends(get_jobs_service),
) -> JobActionResponse:
    return JobActionResponse(job=job_response(await service.skip(job_id, payload.reason)))


@router.post("/{job_id}/invalid", response_model=JobActionResponse)
async def invalid(
    job_id: UUID,
    service: JobsService = Depends(get_jobs_service),
) -> JobActionResponse:
    return JobActionResponse(job=job_response(await service.mark_invalid(job_id)))


@router.post("/{job_id}/claim", response_model=ClaimResponse)
async def claim(
    job_id: UUID,
    service: ClaimService = Depends(get_claim_service),
) -> ClaimResponse:
    outcome = await service.claim(job_id)
    return ClaimResponse(
        job_id=outcome.job_id,
        status=outcome.status,
        points_added=outcome.points_added,
        balance_after=outcome.balance_after,
        message=outcome.message,
        cache_count=outcome.cache_count,
        settlement_pending=outcome.settlement_pending,
    )
