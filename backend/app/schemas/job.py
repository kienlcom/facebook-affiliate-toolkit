from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: UUID
    session_id: UUID
    external_id: str
    profile_key: str
    url: str
    action_label: str | None
    state: str
    fetched_at: datetime
    opened_at: datetime | None
    user_confirmed_at: datetime | None
    claimed_at: datetime | None


class FetchJobsResponse(BaseModel):
    jobs: list[JobResponse]
    duplicates_ignored: int


class JobActionResponse(BaseModel):
    job: JobResponse


class SkipJobRequest(BaseModel):
    reason: str | None = None
