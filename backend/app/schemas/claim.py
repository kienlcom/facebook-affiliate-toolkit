from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ClaimResponse(BaseModel):
    job_id: UUID
    status: str
    points_added: int
    balance_after: int | None
    message: str
    cache_count: int | None = None
    settlement_pending: bool = False
