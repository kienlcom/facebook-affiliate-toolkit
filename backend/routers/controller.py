from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from database import SessionLocal
from models import Channel
from services.auto_scroll import auto_scroll_service

router = APIRouter(prefix="/api/controller", tags=["controller"])


class ScrollConfigPayload(BaseModel):
    scroll_interval: int = Field(default=30, ge=10, le=60)
    scroll_x: int = Field(default=500, ge=0)
    scroll_y_start: int = Field(default=780, ge=0)
    scroll_y_end: int = Field(default=240, ge=0)


def load_active_channels() -> list[dict[str, object]]:
    with SessionLocal() as db:
        channels = db.scalars(
            select(Channel).where(Channel.is_active.is_(True)).order_by(Channel.created_at.desc())
        )
        return [
            {
                "id": channel.id,
                "channel_name": channel.channel_name,
                "channel_url": channel.channel_url,
                "is_active": channel.is_active,
            }
            for channel in channels
        ]


@router.post("/start")
def start_controller(config: ScrollConfigPayload = ScrollConfigPayload()) -> dict[str, object]:
    return auto_scroll_service.start(load_active_channels, config.model_dump())


@router.post("/stop")
def stop_controller() -> dict[str, object]:
    return auto_scroll_service.stop()


@router.post("/buy")
def buy_controller() -> dict[str, object]:
    return auto_scroll_service.buy()


@router.post("/skip")
def skip_controller() -> dict[str, object]:
    try:
        return auto_scroll_service.skip()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot scroll: {exc}") from exc


@router.get("/status")
def controller_status() -> dict[str, object]:
    return auto_scroll_service.status()
