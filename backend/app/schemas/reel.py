from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReelLinkResponse(BaseModel):
    id: UUID
    slug: str
    title: str
    url: str
    absolute_url: str
    image_count: int
    sort_order: int
    enabled: bool


class ReelRunRequest(BaseModel):
    """Override tuỳ chọn; bỏ trống thì dùng giá trị trong Settings."""

    dwell_seconds: float | None = Field(default=None, gt=0, le=600)
    headed: bool | None = None


class ReelRunEvent(BaseModel):
    ts: str
    level: str
    event: str
    data: dict[str, Any]


class ReelRunResponse(BaseModel):
    run_id: str
    status: str
    headed: bool
    dwell_seconds: float
    link_count: int
    started_at: str | None
    ended_at: str | None
    result: dict[str, Any] | None
    error: str | None


class ReelRunLogsResponse(ReelRunResponse):
    events: list[ReelRunEvent]
