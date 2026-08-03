from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.platforms.facebook.auto_advance import LinkOpenTarget
from app.schemas.job import JobResponse


class CreateSessionRequest(BaseModel):
    profile_key: str = Field(min_length=1, max_length=255)


class SessionLimits(BaseModel):
    max_jobs: int
    max_duration_minutes: int


class SessionResponse(BaseModel):
    id: UUID
    account_id: UUID
    status: str
    profile_key: str
    started_at: datetime
    ended_at: datetime | None
    stop_reason: str | None
    limits: SessionLimits


class StopSessionRequest(BaseModel):
    reason: str = Field(default="USER_REQUESTED", min_length=1, max_length=255)


class SessionCounters(BaseModel):
    fetched: int
    opened: int
    confirmed: int
    claimed: int
    failed: int
    points_earned: int


class AutoOpenRequest(BaseModel):
    enabled: bool


class LinkOpenTargetRequest(BaseModel):
    target: LinkOpenTarget


class AutoOpenStatusResponse(BaseModel):
    available: bool
    mode: Literal["frontend_manual", "local_browser"]
    target: LinkOpenTarget
    enabled: bool
    paused: bool
    state: str
    interval_seconds: int
    next_open_at: datetime | None
    seconds_remaining: int | None
    pending_job_id: UUID | None
    reason: str | None


class SessionSummaryResponse(BaseModel):
    session: SessionResponse
    counters: SessionCounters
    elapsed_seconds: int
    remaining_jobs: int
    jobs: list[JobResponse]
    auto_open: AutoOpenStatusResponse


WarningType = Literal[
    "CHECKPOINT",
    "TEMPORARY_BLOCK",
    "IDENTITY_VERIFICATION",
    "FEATURE_UNAVAILABLE",
    "SUSPICIOUS_ACTIVITY",
    "OTHER",
]


class AccountWarningRequest(BaseModel):
    warning_type: WarningType
    note: str | None = Field(default=None, max_length=1000)
