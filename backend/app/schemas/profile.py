from __future__ import annotations

from pydantic import BaseModel


class JobProfileResponse(BaseModel):
    key: str
    display_name: str
    provider: str
    platform: str
    minimum_claim_wait_seconds: int
    settlement_threshold: int
    verification_status: str
