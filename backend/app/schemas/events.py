from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class WebSocketEvent(BaseModel):
    event: str
    timestamp: datetime
    session_id: UUID
    data: dict[str, Any]
