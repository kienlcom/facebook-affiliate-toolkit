from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Account, AppState, Job, Session
from app.jobs.state_machine import JobState, transition
from app.platforms.facebook.opener import LinkOpener
from app.platforms.facebook.urls import validate_facebook_url

logger = logging.getLogger(__name__)

CIRCUIT_STATE_KEY = "tds:circuit_breaker"
BLOCKING_STATES = {
    JobState.OPENING,
    JobState.OPENED,
    JobState.WAITING_USER,
    JobState.USER_CONFIRMED,
    JobState.CLAIM_PENDING,
    JobState.CLAIMING,
    JobState.RETRY_WAIT,
}
SleepCallable = Callable[[float], Awaitable[None]]


class EventPublisher(Protocol):
    async def publish(
        self,
        session_id: UUID,
        event: str,
        data: dict[str, Any],
    ) -> None:
        """Publish one redacted session event."""


class AutoOpenRuntimeState(StrEnum):
    OFF = "OFF"
    IDLE = "IDLE"
    COUNTDOWN = "COUNTDOWN"
    OPENING = "OPENING"
    WAITING_DEVICE = "WAITING_DEVICE"
    WAITING_USER = "WAITING_USER"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


class LinkOpenTarget(StrEnum):
    HOST_PC = "host_pc"
    CURRENT_DEVICE = "current_device"


@dataclass(frozen=True, slots=True)
class AutoOpenStatus:
    available: bool
    mode: str
    target: LinkOpenTarget
    enabled: bool
    paused: bool
    state: AutoOpenRuntimeState
    interval_seconds: int
    next_open_at: datetime | None
    seconds_remaining: int | None
    pending_job_id: UUID | None
    reason: str | None


@dataclass(slots=True)
class _Runtime:
    enabled: bool = False
    paused: bool = False
    target: LinkOpenTarget = LinkOpenTarget.HOST_PC
    state: AutoOpenRuntimeState = AutoOpenRuntimeState.OFF
    next_open_at: datetime | None = None
    pending_job_id: UUID | None = None
    reason: str | None = None
    task: asyncio.Task[None] | None = None


@dataclass(frozen=True, slots=True)
class _OpenDecision:
    job_id: UUID | None = None
    url: str | None = None
    state: AutoOpenRuntimeState = AutoOpenRuntimeState.IDLE
    reason: str | None = None
    halt: bool = False


class AutoOpenCoordinator:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        opener: LinkOpener,
        ws_manager: EventPublisher,
        sleep: SleepCallable = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._opener = opener
        self._ws_manager = ws_manager
        self._sleep = sleep
        self._runtimes: dict[UUID, _Runtime] = {}
        self._runtime_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return (
            self._settings.LINK_OPENER_MODE == "local_browser"
            and self._settings.AUTO_OPEN_ENABLED
            and self._settings.APP_ENV.casefold() in {"development", "local", "test"}
        )

    def status(self, session_id: UUID, *, now: datetime | None = None) -> AutoOpenStatus:
        runtime = self._runtimes.get(session_id)
        current_time = now or datetime.now(UTC)
        if runtime is None:
            return AutoOpenStatus(
                available=self.available,
                mode=self._settings.LINK_OPENER_MODE,
                target=LinkOpenTarget.HOST_PC,
                enabled=False,
                paused=False,
                state=AutoOpenRuntimeState.OFF,
                interval_seconds=self._settings.AUTO_OPEN_INTERVAL_SECONDS,
                next_open_at=None,
                seconds_remaining=None,
                pending_job_id=None,
                reason=None,
            )
        seconds_remaining = (
            max(
                0,
                math.ceil((runtime.next_open_at - current_time).total_seconds()),
            )
            if runtime.next_open_at is not None
            else None
        )
        return AutoOpenStatus(
            available=self.available,
            mode=self._settings.LINK_OPENER_MODE,
            target=runtime.target,
            enabled=runtime.enabled,
            paused=runtime.paused,
            state=runtime.state,
            interval_seconds=self._settings.AUTO_OPEN_INTERVAL_SECONDS,
            next_open_at=runtime.next_open_at,
            seconds_remaining=seconds_remaining,
            pending_job_id=runtime.pending_job_id,
            reason=runtime.reason,
        )

    async def register_session(self, session_id: UUID) -> AutoOpenStatus:
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.enabled = self.available
            runtime.paused = False
            runtime.target = LinkOpenTarget.HOST_PC
            runtime.pending_job_id = None
            runtime.state = (
                AutoOpenRuntimeState.IDLE
                if runtime.enabled
                else AutoOpenRuntimeState.OFF
            )
            runtime.reason = "QUEUE_EMPTY" if runtime.enabled else None
        if runtime.enabled:
            await self._publish_enabled(session_id, runtime)
        return self.status(session_id)

    async def set_enabled(self, session_id: UUID, enabled: bool) -> AutoOpenStatus:
        await self._ensure_running_session(session_id)
        if enabled and not self.available:
            raise ConflictError(
                "AUTO_OPEN_NOT_AVAILABLE",
                "Auto-open requires a local backend with local_browser mode enabled",
            )
        await self._cancel_task(session_id)
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.enabled = enabled
            runtime.paused = False
            runtime.next_open_at = None
            runtime.pending_job_id = None
            runtime.state = (
                AutoOpenRuntimeState.IDLE
                if enabled
                else AutoOpenRuntimeState.OFF
            )
            runtime.reason = None
        await self._publish_enabled(session_id, runtime)
        if enabled:
            await self._schedule(session_id, delay_seconds=0)
        return self.status(session_id)

    async def set_target(
        self,
        session_id: UUID,
        target: LinkOpenTarget,
    ) -> AutoOpenStatus:
        await self._ensure_running_session(session_id)
        if not self.available:
            raise ConflictError(
                "AUTO_OPEN_NOT_AVAILABLE",
                "Link target selection requires local_browser mode",
            )
        await self._cancel_task(session_id)
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.target = target
            runtime.pending_job_id = None
            runtime.next_open_at = None
            runtime.state = (
                AutoOpenRuntimeState.IDLE
                if runtime.enabled and not runtime.paused
                else runtime.state
            )
            runtime.reason = None
        await self._ws_manager.publish(
            session_id,
            "session.link_target_changed",
            {"target": target.value},
        )
        if runtime.enabled and not runtime.paused:
            await self._schedule(session_id, delay_seconds=0)
        return self.status(session_id)

    async def pause(self, session_id: UUID, *, reason: str = "USER_PAUSED") -> AutoOpenStatus:
        await self._ensure_running_session(session_id)
        runtime = self._runtimes.get(session_id)
        if runtime is None or not runtime.enabled:
            raise ConflictError("AUTO_OPEN_NOT_ENABLED", "Auto-open is not enabled")
        await self._pause_runtime(session_id, reason=reason, halted=False)
        return self.status(session_id)

    async def resume(self, session_id: UUID) -> AutoOpenStatus:
        await self._ensure_running_session(session_id)
        if not self.available:
            raise ConflictError(
                "AUTO_OPEN_NOT_AVAILABLE",
                "Auto-open is not available for this backend",
            )
        runtime = self._runtimes.get(session_id)
        if runtime is None or not runtime.enabled:
            raise ConflictError("AUTO_OPEN_NOT_ENABLED", "Auto-open is not enabled")
        await self._cancel_task(session_id)
        async with self._runtime_lock:
            runtime.paused = False
            runtime.state = AutoOpenRuntimeState.IDLE
            runtime.reason = None
        await self._ws_manager.publish(
            session_id,
            "session.auto_open_resumed",
            {"enabled": True, "paused": False},
        )
        await self._schedule(session_id, delay_seconds=0)
        return self.status(session_id)

    async def queue_updated(self, session_id: UUID) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            await self.register_session(session_id)
            runtime = self._runtimes.get(session_id)
        if (
            runtime is not None
            and runtime.enabled
            and not runtime.paused
            and runtime.pending_job_id is None
        ):
            await self._schedule(session_id, delay_seconds=0)

    async def job_opened(self, session_id: UUID, job_id: UUID) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None or not runtime.enabled:
            return
        async with self._runtime_lock:
            runtime.pending_job_id = None
            runtime.state = AutoOpenRuntimeState.WAITING_USER
            runtime.reason = "WAITING_FOR_USER"

    async def job_resolved(self, session_id: UUID) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is not None and runtime.enabled and not runtime.paused:
            runtime.pending_job_id = None
            await self._schedule(
                session_id,
                delay_seconds=self._settings.AUTO_OPEN_INTERVAL_SECONDS,
            )

    async def pause_for_safety(self, session_id: UUID, reason: str) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None or not runtime.enabled:
            return
        await self._pause_runtime(session_id, reason=reason, halted=True)

    async def stop_session(self, session_id: UUID, reason: str) -> None:
        await self._cancel_task(session_id)
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.enabled = False
            runtime.paused = False
            runtime.state = AutoOpenRuntimeState.OFF
            runtime.next_open_at = None
            runtime.pending_job_id = None
            runtime.reason = reason
        await self._publish_enabled(session_id, runtime)

    async def shutdown(self) -> None:
        session_ids = list(self._runtimes)
        for session_id in session_ids:
            await self._cancel_task(session_id)

    async def _schedule(self, session_id: UUID, *, delay_seconds: int) -> None:
        await self._cancel_task(session_id)
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            if not runtime.enabled or runtime.paused:
                return
            runtime.state = (
                AutoOpenRuntimeState.COUNTDOWN
                if delay_seconds > 0
                else AutoOpenRuntimeState.IDLE
            )
            runtime.reason = None
            runtime.next_open_at = datetime.now(UTC) + timedelta(
                seconds=delay_seconds
            )
            runtime.task = asyncio.create_task(
                self._run(session_id, delay_seconds),
                name=f"auto-open:{session_id}",
            )

    async def _run(self, session_id: UUID, delay_seconds: int) -> None:
        current_task = asyncio.current_task()
        try:
            for remaining in range(delay_seconds, 0, -1):
                if not await self._is_runnable(session_id, current_task):
                    return
                runtime = self._runtimes[session_id]
                await self._ws_manager.publish(
                    session_id,
                    "auto_open.next_in",
                    {
                        "seconds_remaining": remaining,
                        "next_open_at": (
                            runtime.next_open_at.isoformat()
                            if runtime.next_open_at is not None
                            else None
                        ),
                    },
                )
                await self._sleep(1)
            if await self._is_runnable(session_id, current_task):
                await self._open_next(session_id)
        except asyncio.CancelledError:
            raise
        finally:
            async with self._runtime_lock:
                runtime = self._runtimes.get(session_id)
                if runtime is not None and runtime.task is current_task:
                    runtime.task = None
                    runtime.next_open_at = None
                    if runtime.state == AutoOpenRuntimeState.COUNTDOWN:
                        runtime.state = AutoOpenRuntimeState.IDLE

    async def _open_next(self, session_id: UUID) -> None:
        runtime = self._runtimes.get(session_id)
        target = runtime.target if runtime is not None else LinkOpenTarget.HOST_PC
        decision = await self._decide_next(
            session_id,
            reserve=target == LinkOpenTarget.HOST_PC,
        )
        if decision.halt:
            await self._pause_current_task(session_id, decision.reason or "HALTED")
            return
        if decision.job_id is None or decision.url is None:
            await self._set_runtime_state(
                session_id,
                state=decision.state,
                reason=decision.reason,
            )
            return

        if target == LinkOpenTarget.CURRENT_DEVICE:
            async with self._runtime_lock:
                runtime = self._runtimes.setdefault(session_id, _Runtime())
                runtime.state = AutoOpenRuntimeState.WAITING_DEVICE
                runtime.pending_job_id = decision.job_id
                runtime.reason = "WAITING_FOR_DEVICE_TAP"
                runtime.next_open_at = None
            await self._ws_manager.publish(
                session_id,
                "job.open_ready",
                {
                    "job_id": str(decision.job_id),
                    "url": decision.url,
                    "target": LinkOpenTarget.CURRENT_DEVICE.value,
                },
            )
            return

        await self._set_runtime_state(
            session_id,
            state=AutoOpenRuntimeState.OPENING,
            reason=None,
        )
        await self._ws_manager.publish(
            session_id,
            "job.state_changed",
            {"job_id": str(decision.job_id), "state": JobState.OPENING},
        )
        open_error: Exception | None = None
        open_task = asyncio.create_task(
            asyncio.to_thread(self._opener.open, decision.url),
            name=f"browser-open:{decision.job_id}",
        )
        cancellation: asyncio.CancelledError | None = None
        try:
            opened = await asyncio.shield(open_task)
        except asyncio.CancelledError as exc:
            cancellation = exc
            try:
                opened = await open_task
            except Exception as open_exc:
                opened = False
                open_error = open_exc
        except Exception as exc:
            opened = False
            open_error = exc
        if open_error is not None:
            logger.error(
                "facebook.auto_open_failed",
                extra={
                    "session_id": str(session_id),
                    "job_id": str(decision.job_id),
                    "error_code": type(open_error).__name__,
                },
            )

        job = await self._finalize_open(
            session_id=session_id,
            job_id=decision.job_id,
            opened=opened,
            error_code=type(open_error).__name__ if open_error else None,
        )
        if cancellation is not None:
            raise cancellation
        if job is None:
            return
        await self._ws_manager.publish(
            session_id,
            "job.state_changed",
            {"job_id": str(job.id), "state": job.state},
        )
        if JobState(job.state) == JobState.WAITING_USER:
            await self._set_runtime_state(
                session_id,
                state=AutoOpenRuntimeState.WAITING_USER,
                reason="WAITING_FOR_USER",
            )
            await self._ws_manager.publish(
                session_id,
                "job.auto_opened",
                {
                    "job_id": str(job.id),
                    "state": job.state,
                    "opened_at": (
                        job.opened_at.isoformat()
                        if job.opened_at is not None
                        else None
                    ),
                },
            )
            return
        await self._pause_current_task(session_id, "BROWSER_OPEN_FAILED")

    async def _decide_next(
        self,
        session_id: UUID,
        *,
        reserve: bool,
    ) -> _OpenDecision:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            session = await db.scalar(
                select(Session).where(Session.id == session_id).with_for_update()
            )
            if session is None:
                return _OpenDecision(reason="SESSION_NOT_FOUND", halt=True)
            if session.status != "RUNNING":
                return _OpenDecision(reason="SESSION_NOT_RUNNING", halt=True)
            account = await db.scalar(
                select(Account)
                .where(Account.id == session.account_id)
                .with_for_update()
            )
            if account is None or account.status != "ACTIVE":
                return _OpenDecision(reason="ACCOUNT_NOT_ACTIVE", halt=True)
            if now >= session.started_at + timedelta(
                minutes=session.max_duration_minutes
            ):
                return _OpenDecision(reason="MAX_DURATION_REACHED", halt=True)
            if session.jobs_opened >= session.max_jobs:
                return _OpenDecision(reason="MAX_JOBS_REACHED", halt=True)
            if await self._is_circuit_open(db, session.account_id, now):
                return _OpenDecision(reason="TDS_CIRCUIT_OPEN", halt=True)

            blocking_count = await db.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.session_id == session_id,
                    Job.state.in_([state.value for state in BLOCKING_STATES]),
                )
            )
            if blocking_count:
                return _OpenDecision(
                    state=AutoOpenRuntimeState.WAITING_USER,
                    reason="JOB_IN_PROGRESS",
                )

            job = await db.scalar(
                select(Job)
                .where(
                    Job.session_id == session_id,
                    Job.state == JobState.VALIDATED,
                )
                .order_by(Job.fetched_at, Job.id)
                .limit(1)
                .with_for_update()
            )
            if job is None:
                return _OpenDecision(reason="QUEUE_EMPTY")

            try:
                url = validate_facebook_url(job.url)
            except ValueError:
                opening = transition(
                    JobState(job.state),
                    JobState.VALIDATED,
                    JobState.OPENING,
                )
                job.state = transition(
                    opening,
                    JobState.OPENING,
                    JobState.OPEN_FAILED,
                )
                job.last_error_code = "AUTO_OPEN_URL_INVALID"
                session.jobs_failed += 1
                await db.commit()
                return _OpenDecision(reason="URL_INVALID", halt=True)

            if reserve:
                job.state = transition(
                    JobState(job.state),
                    JobState.VALIDATED,
                    JobState.OPENING,
                )
                await db.commit()
            return _OpenDecision(job_id=job.id, url=url)

    async def _finalize_open(
        self,
        *,
        session_id: UUID,
        job_id: UUID,
        opened: bool,
        error_code: str | None,
    ) -> Job | None:
        async with self._session_factory() as db:
            job = await db.scalar(
                select(Job).where(Job.id == job_id).with_for_update()
            )
            session = await db.scalar(
                select(Session).where(Session.id == session_id).with_for_update()
            )
            if job is None or session is None:
                return None
            if JobState(job.state) != JobState.OPENING:
                return job
            if not opened:
                job.state = transition(
                    JobState.OPENING,
                    JobState.OPENING,
                    JobState.OPEN_FAILED,
                )
                job.last_error_code = error_code or "BROWSER_OPEN_FAILED"
                session.jobs_failed += 1
            else:
                opened_state = transition(
                    JobState.OPENING,
                    JobState.OPENING,
                    JobState.OPENED,
                )
                job.state = transition(
                    opened_state,
                    JobState.OPENED,
                    JobState.WAITING_USER,
                )
                job.opened_at = datetime.now(UTC)
                session.jobs_opened += 1
            await db.commit()
            return job

    async def _pause_runtime(
        self,
        session_id: UUID,
        *,
        reason: str,
        halted: bool,
    ) -> None:
        await self._cancel_task(session_id)
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.paused = True
            runtime.pending_job_id = None
            runtime.state = (
                AutoOpenRuntimeState.HALTED
                if halted
                else AutoOpenRuntimeState.PAUSED
            )
            runtime.next_open_at = None
            runtime.reason = reason
        await self._ws_manager.publish(
            session_id,
            "session.auto_open_paused",
            {"enabled": runtime.enabled, "paused": True, "reason": reason},
        )

    async def _pause_current_task(self, session_id: UUID, reason: str) -> None:
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.paused = True
            runtime.pending_job_id = None
            runtime.state = AutoOpenRuntimeState.HALTED
            runtime.next_open_at = None
            runtime.reason = reason
        await self._ws_manager.publish(
            session_id,
            "session.auto_open_paused",
            {"enabled": runtime.enabled, "paused": True, "reason": reason},
        )

    async def _set_runtime_state(
        self,
        session_id: UUID,
        *,
        state: AutoOpenRuntimeState,
        reason: str | None,
    ) -> None:
        async with self._runtime_lock:
            runtime = self._runtimes.setdefault(session_id, _Runtime())
            runtime.state = state
            runtime.reason = reason
            if state != AutoOpenRuntimeState.COUNTDOWN:
                runtime.next_open_at = None

    async def _cancel_task(self, session_id: UUID) -> None:
        async with self._runtime_lock:
            runtime = self._runtimes.get(session_id)
            task = runtime.task if runtime is not None else None
            if runtime is not None:
                runtime.task = None
                runtime.next_open_at = None
        if task is None or task is asyncio.current_task() or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def _is_runnable(
        self,
        session_id: UUID,
        task: asyncio.Task[None] | None,
    ) -> bool:
        async with self._runtime_lock:
            runtime = self._runtimes.get(session_id)
            return bool(
                runtime is not None
                and runtime.task is task
                and runtime.enabled
                and not runtime.paused
            )

    async def _ensure_running_session(self, session_id: UUID) -> None:
        async with self._session_factory() as db:
            session = await db.scalar(select(Session).where(Session.id == session_id))
            if session is None:
                raise NotFoundError("SESSION_NOT_FOUND", "Session does not exist")
            if session.status != "RUNNING":
                raise ConflictError("SESSION_NOT_RUNNING", "Session is not running")

    @staticmethod
    async def _is_circuit_open(
        db: AsyncSession,
        account_id: UUID,
        now: datetime,
    ) -> bool:
        state = await db.scalar(
            select(AppState).where(
                AppState.account_id == account_id,
                AppState.key == CIRCUIT_STATE_KEY,
            )
        )
        if state is None or state.value_json.get("state") != "OPEN":
            return False
        retry_at_raw = state.value_json.get("retry_at")
        try:
            retry_at = datetime.fromisoformat(str(retry_at_raw))
        except ValueError:
            return True
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return retry_at > now

    async def _publish_enabled(self, session_id: UUID, runtime: _Runtime) -> None:
        await self._ws_manager.publish(
            session_id,
            "session.auto_open_enabled",
            {
                "enabled": runtime.enabled,
                "paused": runtime.paused,
                "mode": self._settings.LINK_OPENER_MODE,
                "target": runtime.target.value,
            },
        )
