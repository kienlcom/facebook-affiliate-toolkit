from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Account, Job, Session
from app.jobs.state_machine import ACTIVE_STATES, JobState, transition
from app.providers.tds.models import TDSProviderConfig
from app.ws.manager import WebSocketManager


class SessionStatus(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PROTECTION_STOP = "PROTECTION_STOP"
    AUTH_FAILED = "AUTH_FAILED"


class SessionService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        provider_config: TDSProviderConfig,
        ws_manager: WebSocketManager,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._provider_config = provider_config
        self._ws_manager = ws_manager

    async def get_local_account(self) -> Account:
        async with self._session_factory() as db:
            account = await db.scalar(select(Account).order_by(Account.created_at).limit(1))
            if account is None:
                raise NotFoundError("ACCOUNT_NOT_FOUND", "Local account does not exist")
            return account

    async def create(self, account_id: UUID, profile_key: str) -> Session:
        try:
            profile = self._provider_config.get_enabled_profile(profile_key)
        except ValueError as exc:
            raise ConflictError("PROFILE_NOT_AVAILABLE", str(exc)) from exc

        now = datetime.now(UTC)
        async with self._session_factory() as db:
            account = await db.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None:
                raise NotFoundError("ACCOUNT_NOT_FOUND", "Account does not exist")
            if account.status != AccountStatus.ACTIVE:
                raise ConflictError(
                    "ACCOUNT_PROTECTION_STOP",
                    "Account is not available for a new session",
                    details={"account_status": account.status},
                )
            session = Session(
                account_id=account.id,
                profile_key=profile.key,
                provider=profile.provider,
                platform=profile.platform,
                status=SessionStatus.RUNNING,
                started_at=now,
                max_jobs=self._settings.MAX_JOBS_PER_SESSION,
                max_duration_minutes=self._settings.MAX_SESSION_DURATION_MINUTES,
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

        await self._ws_manager.publish(
            session.id,
            "session.started",
            {"status": session.status, "profile_key": session.profile_key},
        )
        return session

    async def get(self, session_id: UUID, *, for_update: bool = False) -> Session:
        async with self._session_factory() as db:
            statement = select(Session).where(Session.id == session_id)
            if for_update:
                statement = statement.with_for_update()
            session = await db.scalar(statement)
            if session is None:
                raise NotFoundError("SESSION_NOT_FOUND", "Session does not exist")
            return session

    async def stop(self, session_id: UUID, reason: str) -> Session:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            session = await self._get_locked(db, session_id)
            if session.status == SessionStatus.RUNNING:
                await self._stop_locked(
                    db,
                    session,
                    reason=reason,
                    job_target=JobState.CANCELLED,
                    now=now,
                )
                await db.commit()

        await self._ws_manager.publish(
            session.id,
            "session.stopped",
            {"status": session.status, "reason": session.stop_reason},
        )
        return session

    async def summary(self, session_id: UUID) -> tuple[Session, list[Job]]:
        async with self._session_factory() as db:
            session = await db.scalar(select(Session).where(Session.id == session_id))
            if session is None:
                raise NotFoundError("SESSION_NOT_FOUND", "Session does not exist")
            jobs = list(
                await db.scalars(
                    select(Job)
                    .where(Job.session_id == session_id)
                    .order_by(Job.fetched_at, Job.id)
                )
            )
            return session, jobs

    async def mark_protection_stop(
        self,
        session_id: UUID,
        *,
        warning_type: str,
        note: str | None,
    ) -> Session:
        now = datetime.now(UTC)
        reason = f"ACCOUNT_WARNING:{warning_type}"
        async with self._session_factory() as db:
            session = await self._get_locked(db, session_id)
            account = await db.scalar(
                select(Account)
                .where(Account.id == session.account_id)
                .with_for_update()
            )
            if account is None:
                raise NotFoundError("ACCOUNT_NOT_FOUND", "Account does not exist")
            account.status = AccountStatus.PROTECTION_STOP
            if session.status == SessionStatus.RUNNING:
                await self._stop_locked(
                    db,
                    session,
                    reason=reason,
                    job_target=JobState.ACCOUNT_PROTECTION_STOP,
                    now=now,
                )
            await db.commit()

        await self._ws_manager.publish(
            session.id,
            "account.warning",
            {
                "warning_type": warning_type,
                "note_provided": note is not None,
                "session_status": session.status,
            },
        )
        await self._ws_manager.publish(
            session.id,
            "session.stopped",
            {"status": session.status, "reason": session.stop_reason},
        )
        return session

    async def stop_for_auth_failure(self, session_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            session = await self._get_locked(db, session_id)
            account = await db.scalar(
                select(Account)
                .where(Account.id == session.account_id)
                .with_for_update()
            )
            if account is not None:
                account.status = AccountStatus.AUTH_FAILED
            if session.status == SessionStatus.RUNNING:
                await self._stop_locked(
                    db,
                    session,
                    reason="TDS_AUTH_ERROR",
                    job_target=JobState.CANCELLED,
                    now=now,
                )
            await db.commit()

        await self._ws_manager.publish(
            session.id,
            "session.stopped",
            {"status": session.status, "reason": session.stop_reason},
        )

    async def recover_interrupted_sessions(self) -> int:
        now = datetime.now(UTC)
        recovered = 0
        async with self._session_factory() as db:
            sessions = list(
                await db.scalars(
                    select(Session)
                    .where(Session.status == SessionStatus.RUNNING)
                    .with_for_update()
                )
            )
            for session in sessions:
                await self._stop_locked(
                    db,
                    session,
                    reason="BACKEND_RESTARTED",
                    job_target=JobState.CANCELLED,
                    now=now,
                )
                recovered += 1
            await db.commit()
        return recovered

    @staticmethod
    async def _get_locked(db: AsyncSession, session_id: UUID) -> Session:
        session = await db.scalar(
            select(Session).where(Session.id == session_id).with_for_update()
        )
        if session is None:
            raise NotFoundError("SESSION_NOT_FOUND", "Session does not exist")
        return session

    @staticmethod
    async def _stop_locked(
        db: AsyncSession,
        session: Session,
        *,
        reason: str,
        job_target: JobState,
        now: datetime,
    ) -> None:
        session.status = SessionStatus.STOPPED
        session.ended_at = now
        session.stop_reason = reason
        jobs = list(
            await db.scalars(
                select(Job)
                .where(Job.session_id == session.id)
                .with_for_update()
            )
        )
        for job in jobs:
            current = JobState(job.state)
            if current not in ACTIVE_STATES:
                continue
            job.state = transition(current, current, job_target)
