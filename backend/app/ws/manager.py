from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from app.core.redaction import redact

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(websocket)

    async def disconnect(self, session_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(session_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(session_id, None)

    async def publish(
        self,
        session_id: UUID,
        event: str,
        data: dict[str, Any],
    ) -> None:
        envelope = {
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": str(session_id),
            "data": redact(data),
        }
        async with self._lock:
            connections = list(self._connections.get(session_id, set()))

        failed: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(envelope)
            except Exception as exc:
                failed.append(websocket)
                logger.warning(
                    "websocket.send_failed",
                    extra={
                        "session_id": str(session_id),
                        "error_code": type(exc).__name__,
                    },
                )
        for websocket in failed:
            await self.disconnect(session_id, websocket)

    async def connection_count(self, session_id: UUID | None = None) -> int:
        async with self._lock:
            if session_id is not None:
                return len(self._connections.get(session_id, set()))
            return sum(len(connections) for connections in self._connections.values())
