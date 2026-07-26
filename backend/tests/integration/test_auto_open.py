from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.db.models import Account, AppState, Job, JobAttempt, Session
from app.db.session import build_sessionmaker
from app.jobs.state_machine import JobState
from app.platforms.facebook.auto_advance import (
    AutoOpenCoordinator,
    AutoOpenRuntimeState,
)
from app.providers.tds.models import load_provider_config
from app.sessions.service import SessionService
from app.ws.manager import WebSocketManager


@dataclass(slots=True)
class RecordingOpener:
    urls: list[str] = field(default_factory=list)

    def open(self, url: str) -> bool:
        self.urls.append(url)
        return True


@dataclass(slots=True)
class RecordingWebSocketManager:
    events: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)

    async def publish(
        self,
        session_id: UUID,
        event: str,
        data: dict[str, Any],
    ) -> None:
        self.events.append((session_id, event, data))


@dataclass(slots=True)
class AutoOpenTestState:
    session_factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    session_id: UUID
    job_ids: list[UUID]


async def _reset_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        await db.execute(delete(AppState))
        await db.execute(delete(JobAttempt))
        await db.execute(delete(Job))
        await db.execute(delete(Session))
        await db.execute(update(Account).values(status="ACTIVE"))
        await db.commit()


@pytest.fixture
async def auto_open_state() -> AutoOpenTestState:
    settings = Settings(_env_file=None, TDS_ACCESS_TOKEN="test-token")
    session_factory = build_sessionmaker(settings)
    engine = session_factory.kw["bind"]
    await _reset_database(session_factory)

    now = datetime.now(UTC)
    async with session_factory() as db:
        account_id = await db.scalar(select(Account.id).limit(1))
        assert account_id is not None
        session = Session(
            account_id=account_id,
            profile_key="facebook_page",
            provider="tds",
            platform="facebook",
            status="RUNNING",
            started_at=now,
            max_jobs=20,
            max_duration_minutes=30,
        )
        db.add(session)
        await db.flush()
        jobs = [
            Job(
                account_id=account_id,
                session_id=session.id,
                external_id=f"auto-open-{index}",
                profile_key="facebook_page",
                provider="tds",
                platform="facebook",
                job_field="facebook_page",
                claim_type="facebook_page_cache",
                url=f"https://www.facebook.com/{1000 + index}",
                action_label="page",
                state=JobState.VALIDATED,
                fetched_at=now + timedelta(milliseconds=index),
                raw_job_json={"id": str(1000 + index), "code": f"code-{index}"},
            )
            for index in range(2)
        ]
        db.add_all(jobs)
        session.jobs_fetched = len(jobs)
        await db.commit()
        session_id = session.id
        job_ids = [job.id for job in jobs]

    yield AutoOpenTestState(
        session_factory=session_factory,
        engine=engine,
        session_id=session_id,
        job_ids=job_ids,
    )

    await _reset_database(session_factory)
    await engine.dispose()


def build_coordinator(
    state: AutoOpenTestState,
    opener: RecordingOpener,
    ws_manager: RecordingWebSocketManager,
) -> AutoOpenCoordinator:
    settings = Settings(
        _env_file=None,
        TDS_ACCESS_TOKEN="test-token",
        APP_ENV="test",
        LINK_OPENER_MODE="local_browser",
        AUTO_OPEN_ENABLED=True,
        AUTO_OPEN_INTERVAL_SECONDS=1,
    )
    return AutoOpenCoordinator(
        settings=settings,
        session_factory=state.session_factory,
        opener=opener,
        ws_manager=ws_manager,
    )


async def wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Timed out waiting for auto-open state")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_auto_advance_is_sequential_and_pause_cancels_countdown(
    auto_open_state: AutoOpenTestState,
) -> None:
    opener = RecordingOpener()
    ws_manager = RecordingWebSocketManager()
    coordinator = build_coordinator(auto_open_state, opener, ws_manager)
    await coordinator.register_session(auto_open_state.session_id)

    await coordinator.queue_updated(auto_open_state.session_id)
    await wait_until(
        lambda: coordinator.status(auto_open_state.session_id).state
        == AutoOpenRuntimeState.WAITING_USER
    )
    assert len(opener.urls) == 1

    async with auto_open_state.session_factory() as db:
        jobs = list(
            await db.scalars(
                select(Job)
                .where(Job.session_id == auto_open_state.session_id)
                .order_by(Job.fetched_at)
            )
        )
        assert [job.state for job in jobs] == [
            JobState.WAITING_USER,
            JobState.VALIDATED,
        ]
        attempts = list(await db.scalars(select(JobAttempt)))
        assert attempts == []

        jobs[0].state = JobState.USER_SKIPPED
        await db.commit()

    await coordinator.job_resolved(auto_open_state.session_id)
    await wait_until(
        lambda: coordinator.status(auto_open_state.session_id).state
        == AutoOpenRuntimeState.COUNTDOWN
    )
    await coordinator.pause(auto_open_state.session_id)
    await asyncio.sleep(1.1)
    assert len(opener.urls) == 1
    assert coordinator.status(auto_open_state.session_id).paused is True

    await coordinator.resume(auto_open_state.session_id)
    await wait_until(
        lambda: len(opener.urls) == 2
        and coordinator.status(auto_open_state.session_id).state
        == AutoOpenRuntimeState.WAITING_USER
    )
    async with auto_open_state.session_factory() as db:
        second = await db.get(Job, auto_open_state.job_ids[1])
        assert second is not None
        assert second.state == JobState.WAITING_USER
    assert sum(event == "job.auto_opened" for _, event, _ in ws_manager.events) == 2
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_stop_cancels_countdown_and_circuit_breaker_blocks_open(
    auto_open_state: AutoOpenTestState,
) -> None:
    opener = RecordingOpener()
    ws_manager = RecordingWebSocketManager()
    coordinator = build_coordinator(auto_open_state, opener, ws_manager)
    await coordinator.register_session(auto_open_state.session_id)

    async with auto_open_state.session_factory() as db:
        session = await db.get(Session, auto_open_state.session_id)
        assert session is not None
        db.add(
            AppState(
                account_id=session.account_id,
                key="tds:circuit_breaker",
                value_json={
                    "state": "OPEN",
                    "retry_at": (
                        datetime.now(UTC) + timedelta(minutes=1)
                    ).isoformat(),
                },
            )
        )
        await db.commit()

    await coordinator.queue_updated(auto_open_state.session_id)
    await wait_until(
        lambda: coordinator.status(auto_open_state.session_id).state
        == AutoOpenRuntimeState.HALTED
    )
    assert opener.urls == []
    assert coordinator.status(auto_open_state.session_id).reason == "TDS_CIRCUIT_OPEN"

    await coordinator.set_enabled(auto_open_state.session_id, False)
    await coordinator.stop_session(auto_open_state.session_id, "USER_REQUESTED")
    await asyncio.sleep(0.05)
    assert opener.urls == []
    assert coordinator.status(auto_open_state.session_id).enabled is False
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_account_warning_cancels_countdown_and_stops_session(
    auto_open_state: AutoOpenTestState,
) -> None:
    opener = RecordingOpener()
    ws_manager = WebSocketManager()
    settings = Settings(
        _env_file=None,
        TDS_ACCESS_TOKEN="test-token",
        APP_ENV="test",
        LINK_OPENER_MODE="local_browser",
        AUTO_OPEN_ENABLED=True,
        AUTO_OPEN_INTERVAL_SECONDS=1,
    )
    coordinator = AutoOpenCoordinator(
        settings=settings,
        session_factory=auto_open_state.session_factory,
        opener=opener,
        ws_manager=ws_manager,
    )
    session_service = SessionService(
        settings=settings,
        session_factory=auto_open_state.session_factory,
        provider_config=load_provider_config(),
        ws_manager=ws_manager,
        auto_open_coordinator=coordinator,
    )
    await coordinator.register_session(auto_open_state.session_id)

    async with auto_open_state.session_factory() as db:
        first = await db.get(Job, auto_open_state.job_ids[0])
        assert first is not None
        first.state = JobState.USER_SKIPPED
        await db.commit()

    await coordinator.job_resolved(auto_open_state.session_id)
    await wait_until(
        lambda: coordinator.status(auto_open_state.session_id).state
        == AutoOpenRuntimeState.COUNTDOWN
    )
    stopped = await session_service.mark_protection_stop(
        auto_open_state.session_id,
        warning_type="CHECKPOINT",
        note="Facebook displayed a checkpoint",
    )
    await asyncio.sleep(1.1)

    assert stopped.status == "STOPPED"
    assert stopped.stop_reason == "ACCOUNT_WARNING:CHECKPOINT"
    assert opener.urls == []
    assert coordinator.status(auto_open_state.session_id).enabled is False
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_session_duration_limit_halts_auto_open(
    auto_open_state: AutoOpenTestState,
) -> None:
    opener = RecordingOpener()
    ws_manager = RecordingWebSocketManager()
    coordinator = build_coordinator(auto_open_state, opener, ws_manager)
    await coordinator.register_session(auto_open_state.session_id)
    async with auto_open_state.session_factory() as db:
        session = await db.get(Session, auto_open_state.session_id)
        assert session is not None
        session.started_at = datetime.now(UTC) - timedelta(minutes=31)
        await db.commit()

    await coordinator.queue_updated(auto_open_state.session_id)
    await wait_until(
        lambda: coordinator.status(auto_open_state.session_id).state
        == AutoOpenRuntimeState.HALTED
    )

    assert opener.urls == []
    assert coordinator.status(auto_open_state.session_id).reason == "MAX_DURATION_REACHED"
    await coordinator.shutdown()
