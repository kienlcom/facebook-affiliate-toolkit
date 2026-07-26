from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError, NotFoundError, TooEarlyError
from app.core.redaction import redact
from app.db.models import Account, Job, JobAttempt, Session
from app.jobs.state_machine import JobState, transition
from app.platforms.facebook.auto_advance import AutoOpenCoordinator
from app.providers.tds.client import TDSClient
from app.providers.tds.errors import (
    TDSAuthError,
    TDSClaimRejectedError,
    TDSCircuitOpenError,
    TDSInvalidResponseError,
    TDSProviderError,
    TDSRateLimitError,
    TDSTooFastError,
    TDSTransportError,
    TDSUnknownResponseError,
)
from app.providers.tds.models import (
    TDSClaimResult,
    TDSClaimStatus,
    TDSJobProfile,
    TDSProviderConfig,
    TDSRequestContext,
)
from app.sessions.service import AccountStatus, SessionService, SessionStatus
from app.ws.manager import WebSocketManager

SleepCallable = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class ClaimOutcome:
    job_id: UUID
    status: JobState
    points_added: int
    balance_after: int | None
    message: str
    cache_count: int | None
    settlement_pending: bool


def can_claim(
    job: Job,
    session: Session,
    account: Account,
    *,
    now: datetime,
    minimum_wait_seconds: int,
) -> None:
    if JobState(job.state) != JobState.USER_CONFIRMED:
        raise ConflictError(
            "JOB_NOT_USER_CONFIRMED",
            "Job must be manually confirmed before claim",
            details={"state": job.state},
        )
    if not job.external_id:
        raise ConflictError("JOB_EXTERNAL_ID_MISSING", "Job external ID is missing")
    if not job.claim_type:
        raise ConflictError("JOB_CLAIM_TYPE_MISSING", "Job claim type is missing")
    if job.opened_at is None:
        raise ConflictError("JOB_NOT_OPENED", "Job has no server opened timestamp")
    if job.user_confirmed_at is None:
        raise ConflictError("JOB_CONFIRMATION_MISSING", "Job confirmation timestamp is missing")
    if job.claimed_at is not None:
        raise ConflictError("JOB_ALREADY_CLAIMED", "Job was already claimed")
    if session.status != SessionStatus.RUNNING:
        raise ConflictError("SESSION_NOT_RUNNING", "Session is not running")
    if account.status != AccountStatus.ACTIVE:
        raise ConflictError("ACCOUNT_PROTECTION_STOP", "Account is protection-stopped")
    if session.jobs_fetched > session.max_jobs:
        raise ConflictError("SESSION_LIMIT_REACHED", "Session job limit was exceeded")
    if now >= session.started_at + timedelta(minutes=session.max_duration_minutes):
        raise ConflictError("SESSION_LIMIT_REACHED", "Session duration limit was reached")

    eligible_at = job.opened_at + timedelta(seconds=minimum_wait_seconds)
    if now < eligible_at:
        retry_after = max(1, math.ceil((eligible_at - now).total_seconds()))
        raise TooEarlyError(
            "CLAIM_TOO_EARLY",
            "Server-side minimum wait has not elapsed",
            retry_after_seconds=retry_after,
        )


class ClaimService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        tds_client: TDSClient,
        session_service: SessionService,
        provider_config: TDSProviderConfig,
        ws_manager: WebSocketManager,
        sleep: SleepCallable = asyncio.sleep,
        auto_open_coordinator: AutoOpenCoordinator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tds_client = tds_client
        self._session_service = session_service
        self._provider_config = provider_config
        self._ws_manager = ws_manager
        self._sleep = sleep
        self._auto_open_coordinator = auto_open_coordinator

    async def claim(self, job_id: UUID) -> ClaimOutcome:
        started_at = datetime.now(UTC)
        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            session = await self._get_session_locked(db, job.session_id)
            account = await self._get_account_locked(db, job.account_id)
            profile = self._provider_config.get_enabled_profile(job.profile_key)
            can_claim(
                job,
                session,
                account,
                now=started_at,
                minimum_wait_seconds=profile.minimum_claim_wait_seconds,
            )
            code_field = profile.response_mapping.code_field
            job_code = str(job.raw_job_json.get(code_field, "")).strip()
            if not job_code:
                raise ConflictError(
                    "JOB_CLAIM_ID_MISSING",
                    "Verified job claim code is missing",
                )

            pending = transition(
                JobState(job.state),
                JobState.USER_CONFIRMED,
                JobState.CLAIM_PENDING,
            )
            job.state = transition(pending, JobState.CLAIM_PENDING, JobState.CLAIMING)
            attempt = JobAttempt(
                job_id=job.id,
                session_id=job.session_id,
                account_id=job.account_id,
                attempt_type="CLAIM",
                started_at=started_at,
                success=False,
            )
            db.add(attempt)
            await db.commit()
            await db.refresh(attempt)
            attempt_id = attempt.id
            context = TDSRequestContext(
                account_id=job.account_id,
                session_id=job.session_id,
                job_id=job.id,
            )

        await self._ws_manager.publish(
            context.session_id,
            "job.claim_started",
            {"job_id": str(job_id), "state": JobState.CLAIMING},
        )

        try:
            review = await self._tds_client.submit_job_review(
                context,
                profile_key=profile.key,
                job_code=job_code,
            )
        except TDSProviderError as error:
            await self._finalize_failure(
                job_id=job_id,
                attempt_id=attempt_id,
                error=error,
            )
            if isinstance(error, TDSAuthError):
                await self._session_service.stop_for_auth_failure(context.session_id)
            elif isinstance(error, (TDSRateLimitError, TDSCircuitOpenError)):
                if self._auto_open_coordinator is not None:
                    await self._auto_open_coordinator.pause_for_safety(
                        context.session_id,
                        error.code,
                    )
            elif (
                self._failure_target(error) == JobState.CLAIM_REJECTED
                and self._auto_open_coordinator is not None
            ):
                await self._auto_open_coordinator.job_resolved(context.session_id)
            raise

        settlement: TDSClaimResult | None = None
        settlement_error: TDSProviderError | None = None
        cache_count = review.cache_count
        if (
            review.status == TDSClaimStatus.CACHE_ACCEPTED
            and cache_count is not None
            and cache_count >= profile.settlement_threshold
        ):
            await self._sleep(profile.minimum_claim_wait_seconds)
            try:
                settlement = await self._tds_client.settle_rewards(
                    context,
                    profile_key=profile.key,
                )
            except TDSProviderError as error:
                settlement_error = error

        outcome = await self._finalize_success(
            job_id=job_id,
            attempt_id=attempt_id,
            review=review,
            settlement=settlement,
            settlement_error=settlement_error,
            profile=profile,
        )
        if isinstance(settlement_error, TDSAuthError):
            await self._session_service.stop_for_auth_failure(context.session_id)
        elif isinstance(settlement_error, (TDSRateLimitError, TDSCircuitOpenError)):
            if self._auto_open_coordinator is not None:
                await self._auto_open_coordinator.pause_for_safety(
                    context.session_id,
                    settlement_error.code,
                )
        elif self._auto_open_coordinator is not None:
            await self._auto_open_coordinator.job_resolved(context.session_id)
        return outcome

    async def _finalize_success(
        self,
        *,
        job_id: UUID,
        attempt_id: int,
        review: TDSClaimResult,
        settlement: TDSClaimResult | None,
        settlement_error: TDSProviderError | None,
        profile: TDSJobProfile,
    ) -> ClaimOutcome:
        now = datetime.now(UTC)
        points_added = settlement.points_earned if settlement and settlement.points_earned else 0
        balance_after = settlement.balance if settlement else None
        cache_count = review.cache_count
        settlement_pending = settlement is None
        if settlement is not None:
            message = settlement.message or "Rewards settled"
        elif settlement_error is not None:
            message = f"Job accepted; settlement pending ({settlement_error.code})"
        elif cache_count is not None and cache_count < profile.settlement_threshold:
            message = (
                f"Job accepted; {profile.settlement_threshold - cache_count} more "
                "cached job(s) required"
            )
        else:
            message = review.message or "Job accepted"

        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            session = await self._get_session_locked(db, job.session_id)
            attempt = await self._get_attempt_locked(db, attempt_id)
            if JobState(job.state) != JobState.CLAIMING:
                attempt.ended_at = now
                attempt.error_code = "JOB_STATE_CHANGED"
                attempt.error_message = f"Job state changed to {job.state}"
                await db.commit()
                raise ConflictError(
                    "JOB_STATE_CHANGED",
                    "Job state changed while claim was in progress",
                    details={"actual": job.state},
                )

            job.state = transition(
                JobState.CLAIMING,
                JobState.CLAIMING,
                JobState.CLAIMED,
            )
            job.claimed_at = now
            job.last_error_code = settlement_error.code if settlement_error else None
            job.last_error_message = str(settlement_error) if settlement_error else None
            session.jobs_claimed += 1
            session.points_earned += points_added
            attempt.ended_at = now
            attempt.success = True
            attempt.response_json = redact(
                {
                    "review": review.raw,
                    "settlement": settlement.raw if settlement else None,
                    "settlement_error": (
                        {
                            "code": settlement_error.code,
                            "message": str(settlement_error),
                        }
                        if settlement_error
                        else None
                    ),
                }
            )
            await db.commit()

        outcome = ClaimOutcome(
            job_id=job_id,
            status=JobState.CLAIMED,
            points_added=points_added,
            balance_after=balance_after,
            message=message,
            cache_count=cache_count,
            settlement_pending=settlement_pending,
        )
        await self._ws_manager.publish(
            job.session_id,
            "job.claim_succeeded",
            {
                "job_id": str(job_id),
                "state": outcome.status,
                "points_added": points_added,
                "balance_after": balance_after,
                "cache_count": cache_count,
                "settlement_pending": settlement_pending,
            },
        )
        return outcome

    async def _finalize_failure(
        self,
        *,
        job_id: UUID,
        attempt_id: int,
        error: TDSProviderError,
    ) -> None:
        now = datetime.now(UTC)
        target = self._failure_target(error)
        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            session = await self._get_session_locked(db, job.session_id)
            attempt = await self._get_attempt_locked(db, attempt_id)
            if JobState(job.state) == JobState.CLAIMING:
                job.state = transition(
                    JobState.CLAIMING,
                    JobState.CLAIMING,
                    target,
                )
                job.last_error_code = error.code
                job.last_error_message = str(error)
                if target in {
                    JobState.CLAIM_REJECTED,
                    JobState.AUTH_FAILED,
                }:
                    session.jobs_failed += 1
            attempt.ended_at = now
            attempt.success = False
            attempt.error_code = error.code
            attempt.error_message = str(error)
            attempt.response_json = redact(error.response_json)
            await db.commit()

        await self._ws_manager.publish(
            job.session_id,
            "job.claim_failed",
            {
                "job_id": str(job_id),
                "state": job.state,
                "error_code": error.code,
            },
        )
        if isinstance(error, (TDSRateLimitError, TDSCircuitOpenError)):
            await self._ws_manager.publish(
                job.session_id,
                "api.rate_limited",
                {
                    "error_code": error.code,
                    "retry_at": error.retry_at.isoformat(),
                },
            )

    @staticmethod
    def _failure_target(error: TDSProviderError) -> JobState:
        if isinstance(error, TDSAuthError):
            return JobState.AUTH_FAILED
        if isinstance(
            error,
            (
                TDSTooFastError,
                TDSRateLimitError,
                TDSCircuitOpenError,
                TDSTransportError,
            ),
        ):
            return JobState.RETRY_WAIT
        if isinstance(
            error,
            (
                TDSClaimRejectedError,
                TDSInvalidResponseError,
                TDSUnknownResponseError,
            ),
        ):
            return JobState.CLAIM_REJECTED
        return JobState.CLAIM_REJECTED

    @staticmethod
    async def _get_job_locked(db: AsyncSession, job_id: UUID) -> Job:
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            raise NotFoundError("JOB_NOT_FOUND", "Job does not exist")
        return job

    @staticmethod
    async def _get_session_locked(db: AsyncSession, session_id: UUID) -> Session:
        session = await db.scalar(
            select(Session).where(Session.id == session_id).with_for_update()
        )
        if session is None:
            raise NotFoundError("SESSION_NOT_FOUND", "Session does not exist")
        return session

    @staticmethod
    async def _get_account_locked(db: AsyncSession, account_id: UUID) -> Account:
        account = await db.scalar(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        if account is None:
            raise NotFoundError("ACCOUNT_NOT_FOUND", "Account does not exist")
        return account

    @staticmethod
    async def _get_attempt_locked(db: AsyncSession, attempt_id: int) -> JobAttempt:
        attempt = await db.scalar(
            select(JobAttempt)
            .where(JobAttempt.id == attempt_id)
            .with_for_update()
        )
        if attempt is None:
            raise NotFoundError("JOB_ATTEMPT_NOT_FOUND", "Job attempt does not exist")
        return attempt
