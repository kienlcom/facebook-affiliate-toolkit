from __future__ import annotations

from datetime import UTC, datetime

from app.db.models import Job, Session
from app.platforms.facebook.auto_advance import AutoOpenStatus
from app.schemas.job import JobResponse
from app.schemas.session import (
    SessionCounters,
    AutoOpenStatusResponse,
    SessionLimits,
    SessionResponse,
    SessionSummaryResponse,
)


def job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        session_id=job.session_id,
        external_id=job.external_id,
        profile_key=job.profile_key,
        url=job.url,
        action_label=job.action_label,
        state=job.state,
        fetched_at=job.fetched_at,
        opened_at=job.opened_at,
        user_confirmed_at=job.user_confirmed_at,
        claimed_at=job.claimed_at,
    )


def session_response(session: Session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        account_id=session.account_id,
        status=session.status,
        profile_key=session.profile_key,
        started_at=session.started_at,
        ended_at=session.ended_at,
        stop_reason=session.stop_reason,
        limits=SessionLimits(
            max_jobs=session.max_jobs,
            max_duration_minutes=session.max_duration_minutes,
        ),
    )


def session_summary_response(
    session: Session,
    jobs: list[Job],
    auto_open: AutoOpenStatus,
) -> SessionSummaryResponse:
    end = session.ended_at or datetime.now(UTC)
    elapsed_seconds = max(0, int((end - session.started_at).total_seconds()))
    return SessionSummaryResponse(
        session=session_response(session),
        counters=SessionCounters(
            fetched=session.jobs_fetched,
            opened=session.jobs_opened,
            confirmed=session.jobs_confirmed,
            claimed=session.jobs_claimed,
            failed=session.jobs_failed,
            points_earned=session.points_earned,
        ),
        elapsed_seconds=elapsed_seconds,
        remaining_jobs=max(0, session.max_jobs - session.jobs_fetched),
        jobs=[job_response(job) for job in jobs],
        auto_open=AutoOpenStatusResponse(
            available=auto_open.available,
            mode=auto_open.mode,
            enabled=auto_open.enabled,
            paused=auto_open.paused,
            state=auto_open.state,
            interval_seconds=auto_open.interval_seconds,
            next_open_at=auto_open.next_open_at,
            seconds_remaining=auto_open.seconds_remaining,
            reason=auto_open.reason,
        ),
    )
