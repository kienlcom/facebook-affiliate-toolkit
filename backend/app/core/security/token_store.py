from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.config.settings import Settings


class TokenStore(Protocol):
    async def get_token(self, account_id: UUID, credential_type: str) -> str:
        """Return a server-side credential for an account."""


class LocalEnvTokenStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_token(self, account_id: UUID, credential_type: str) -> str:
        if credential_type != "tds_access_token":
            raise ValueError(f"Unsupported credential type: {credential_type}")
        return self._settings.TDS_ACCESS_TOKEN
