from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError, NotFoundError
from app.db.models import Account, Job, Session
from app.jobs.state_machine import ACTIVE_STATES, JobState, StateConflictError, transition
from app.platforms.facebook.urls import validate_facebook_url
from app.platforms.facebook.auto_advance import AutoOpenCoordinator
from app.providers.tds.client import TDSClient
from app.providers.tds.errors import TDSAuthError, TDSCircuitOpenError, TDSRateLimitError
from app.providers.tds.models import TDSProviderConfig, TDSRequestContext
from app.sessions.service import AccountStatus, SessionService, SessionStatus
from app.ws.manager import WebSocketManager


class JobsService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        tds_client: TDSClient,
        session_service: SessionService,
        provider_config: TDSProviderConfig,
        ws_manager: WebSocketManager,
        auto_open_coordinator: AutoOpenCoordinator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tds_client = tds_client
        self._session_service = session_service
        self._provider_config = provider_config
        self._ws_manager = ws_manager
        self._auto_open_coordinator = auto_open_coordinator

    async def fetch(self, session_id: UUID) -> tuple[list[Job], int]:
        async with self._session_factory() as db:
            session = await self._get_session_locked(db, session_id)
            await self._assert_fetch_allowed(db, session)
            account_id = session.account_id
            profile_key = session.profile_key

        try:
            provider_result = await self._tds_client.fetch_jobs(
                TDSRequestContext(account_id=account_id, session_id=session_id),
                profile_key,
            )
        except TDSAuthError:
            await self._session_service.stop_for_auth_failure(session_id)
            raise
        except (TDSRateLimitError, TDSCircuitOpenError) as error:
            if self._auto_open_coordinator is not None:
                await self._auto_open_coordinator.pause_for_safety(
                    session_id,
                    error.code,
                )
            await self._ws_manager.publish(
                session_id,
                "api.rate_limited",
                {
                    "error_code": error.code,
                    "retry_at": error.retry_at.isoformat(),
                },
            )
            raise

        created: list[Job] = []
        async with self._session_factory() as db:
            session = await self._get_session_locked(db, session_id)
            await self._assert_fetch_allowed(db, session)
            profile = self._provider_config.get_enabled_profile(session.profile_key)
            remaining_capacity = session.max_jobs - session.jobs_fetched
            for provider_job in provider_result.jobs:
                if len(created) >= remaining_capacity:
                    break
                try:
                    url = validate_facebook_url(provider_job.url)
                    state = JobState.VALIDATED
                except ValueError:
                    url = provider_job.url
                    state = JobState.LINK_INVALID

                statement = (
                    insert(Job)
                    .values(
                        account_id=session.account_id,
                        session_id=session.id,
                        external_id=provider_job.external_id,
                        profile_key=session.profile_key,
                        provider=session.provider,
                        platform=session.platform,
                        job_field=profile.job_field,
                        claim_type=profile.claim_type,
                        url=url,
                        action_label=provider_job.action,
                        state=state,
                        fetched_at=datetime.now(UTC),
                        raw_job_json=provider_job.raw,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_jobs_account_provider_profile_external"
                    )
                    .returning(Job.id)
                )
                created_id = await db.scalar(statement)
                if created_id is not None:
                    created_job = await db.scalar(select(Job).where(Job.id == created_id))
                    if created_job is not None:
                        created.append(created_job)

            session.jobs_fetched += len(created)
            session.jobs_failed += sum(
                1 for job in created if job.state == JobState.LINK_INVALID
            )
            await db.commit()

        for job in created:
            await self._ws_manager.publish(
                session_id,
                "job.created",
                {
                    "job_id": str(job.id),
                    "state": job.state,
                    "external_id": job.external_id,
                    "url": job.url,
                    "action_label": job.action_label,
                },
            )
        duplicates_ignored = len(provider_result.jobs) - len(created)
        if self._auto_open_coordinator is not None:
            await self._auto_open_coordinator.queue_updated(session_id)
        return created, duplicates_ignored

    async def get(self, job_id: UUID) -> Job:
        async with self._session_factory() as db:
            job = await db.scalar(select(Job).where(Job.id == job_id))
            if job is None:
                raise NotFoundError("JOB_NOT_FOUND", "Job does not exist")
            return job

    async def mark_opened(self, job_id: UUID) -> Job:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            session = await self._get_running_session_locked(db, job.session_id)
            waiting_count = await db.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.session_id == session.id,
                    Job.state == JobState.WAITING_USER,
                    Job.id != job.id,
                )
            )
            if waiting_count:
                raise ConflictError(
                    "JOB_WAITING_USER",
                    "Resolve the current waiting job before opening another",
                )
            current = JobState(job.state)
            try:
                opening = transition(current, JobState.VALIDATED, JobState.OPENING)
                opened = transition(opening, JobState.OPENING, JobState.OPENED)
                job.state = transition(opened, JobState.OPENED, JobState.WAITING_USER)
            except StateConflictError as exc:
                raise ConflictError(
                    "JOB_INVALID_STATE",
                    "Job cannot be opened from its current state",
                    details={"expected": exc.expected, "actual": exc.actual},
                ) from exc
            job.opened_at = now
            session.jobs_opened += 1
            await db.commit()

        await self._publish_state(job)
        return job

    async def confirm(self, job_id: UUID) -> Job:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            session = await self._get_running_session_locked(db, job.session_id)
            account = await db.scalar(
                select(Account).where(Account.id == job.account_id).with_for_update()
            )
            if account is None:
                raise NotFoundError("ACCOUNT_NOT_FOUND", "Account does not exist")
            if account.status != AccountStatus.ACTIVE:
                raise ConflictError(
                    "ACCOUNT_PROTECTION_STOP",
                    "Account is protection-stopped",
                )
            self._transition_or_conflict(
                job,
                expected=JobState.WAITING_USER,
                target=JobState.USER_CONFIRMED,
                message="Job cannot be confirmed from its current state",
            )
            job.user_confirmed_at = now
            session.jobs_confirmed += 1
            await db.commit()

        await self._publish_state(job)
        return job

    async def skip(self, job_id: UUID, reason: str | None) -> Job:
        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            self._transition_or_conflict(
                job,
                expected=JobState.WAITING_USER,
                target=JobState.USER_SKIPPED,
                message="Job cannot be skipped from its current state",
            )
            job.last_error_code = "USER_SKIPPED"
            job.last_error_message = reason
            await db.commit()

        await self._publish_state(job)
        if self._auto_open_coordinator is not None:
            await self._auto_open_coordinator.job_resolved(job.session_id)
        return job

    async def mark_invalid(self, job_id: UUID) -> Job:
        async with self._session_factory() as db:
            job = await self._get_job_locked(db, job_id)
            session = await self._get_session_locked(db, job.session_id)
            self._transition_or_conflict(
                job,
                expected=JobState.WAITING_USER,
                target=JobState.LINK_INVALID,
                message="Job cannot be marked invalid from its current state",
            )
            job.last_error_code = "LINK_INVALID"
            session.jobs_failed += 1
            await db.commit()

        await self._publish_state(job)
        if self._auto_open_coordinator is not None:
            await self._auto_open_coordinator.job_resolved(job.session_id)
        return job

    async def _assert_fetch_allowed(self, db: AsyncSession, session: Session) -> None:
        if session.status != SessionStatus.RUNNING:
            raise ConflictError("SESSION_NOT_RUNNING", "Session is not running")

        account = await db.scalar(
            select(Account).where(Account.id == session.account_id).with_for_update()
        )
        if account is None:
            raise NotFoundError("ACCOUNT_NOT_FOUND", "Account does not exist")
        if account.status != AccountStatus.ACTIVE:
            raise ConflictError(
                "ACCOUNT_PROTECTION_STOP",
                "Account is protection-stopped",
            )

        active_count = await db.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.session_id == session.id,
                Job.state.in_([state.value for state in ACTIVE_STATES]),
            )
        )
        if active_count:
            raise ConflictError(
                "JOB_BATCH_ACTIVE",
                "Resolve every active job in the current batch before fetching more",
                details={"active_jobs": active_count},
            )

        now = datetime.now(UTC)
        duration_limit = session.started_at + timedelta(
            minutes=session.max_duration_minutes
        )
        if session.jobs_fetched >= session.max_jobs:
            await self._stop_for_limit(
                db,
                session,
                reason="MAX_JOBS_REACHED",
                now=now,
            )
            await self._ws_manager.publish(
                session.id,
                "session.stopped",
                {"status": session.status, "reason": session.stop_reason},
            )
            raise ConflictError("SESSION_LIMIT_REACHED", "Session job limit reached")
        if now >= duration_limit:
            await self._stop_for_limit(
                db,
                session,
                reason="MAX_DURATION_REACHED",
                now=now,
            )
            await self._ws_manager.publish(
                session.id,
                "session.stopped",
                {"status": session.status, "reason": session.stop_reason},
            )
            raise ConflictError("SESSION_LIMIT_REACHED", "Session duration limit reached")

    @staticmethod
    async def _stop_for_limit(
        db: AsyncSession,
        session: Session,
        *,
        reason: str,
        now: datetime,
    ) -> None:
        session.status = SessionStatus.STOPPED
        session.ended_at = now
        session.stop_reason = reason
        await db.commit()

    @staticmethod
    async def _get_session_locked(db: AsyncSession, session_id: UUID) -> Session:
        session = await db.scalar(
            select(Session).where(Session.id == session_id).with_for_update()
        )
        if session is None:
            raise NotFoundError("SESSION_NOT_FOUND", "Session does not exist")
        return session

    @staticmethod
    async def _get_job_locked(db: AsyncSession, job_id: UUID) -> Job:
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            raise NotFoundError("JOB_NOT_FOUND", "Job does not exist")
        return job

    @staticmethod
    async def _get_running_session_locked(
        db: AsyncSession,
        session_id: UUID,
    ) -> Session:
        session = await JobsService._get_session_locked(db, session_id)
        if session.status != SessionStatus.RUNNING:
            raise ConflictError("SESSION_NOT_RUNNING", "Session is not running")
        return session

    @staticmethod
    def _transition_or_conflict(
        job: Job,
        *,
        expected: JobState,
        target: JobState,
        message: str,
    ) -> None:
        current = JobState(job.state)
        try:
            job.state = transition(current, expected, target)
        except StateConflictError as exc:
            raise ConflictError(
                "JOB_INVALID_STATE",
                message,
                details={"expected": exc.expected, "actual": exc.actual},
            ) from exc

    async def _publish_state(self, job: Job) -> None:
        await self._ws_manager.publish(
            job.session_id,
            "job.state_changed",
            {"job_id": str(job.id), "state": job.state},
        )
