from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class TDSAccountProfile(BaseModel):
    username: str | None
    balance: int | None
    status: str


class AccountProfileResponse(BaseModel):
    account_id: UUID
    display_name: str
    tds: TDSAccountProfile
