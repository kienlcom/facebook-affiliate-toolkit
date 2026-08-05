from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Channel

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelCreate(BaseModel):
    channel_name: str = Field(..., min_length=1, max_length=255)
    channel_url: HttpUrl
    is_active: bool = True


class ChannelUpdate(BaseModel):
    channel_name: str | None = Field(default=None, min_length=1, max_length=255)
    channel_url: HttpUrl | None = None
    is_active: bool | None = None


class ChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_name: str
    channel_url: str
    is_active: bool
    created_at: datetime


@router.get("", response_model=list[ChannelRead])
def list_channels(db: Session = Depends(get_db)) -> list[Channel]:
    return list(db.scalars(select(Channel).order_by(Channel.created_at.desc())))


@router.post("", response_model=ChannelRead, status_code=status.HTTP_201_CREATED)
def create_channel(payload: ChannelCreate, db: Session = Depends(get_db)) -> Channel:
    channel = Channel(
        channel_name=payload.channel_name.strip(),
        channel_url=str(payload.channel_url),
        is_active=payload.is_active,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@router.put("/{channel_id}", response_model=ChannelRead)
def update_channel(
    channel_id: int,
    payload: ChannelUpdate,
    db: Session = Depends(get_db),
) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    if payload.channel_name is not None:
        channel.channel_name = payload.channel_name.strip()
    if payload.channel_url is not None:
        channel.channel_url = str(payload.channel_url)
    if payload.is_active is not None:
        channel.is_active = payload.is_active

    db.commit()
    db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(channel_id: int, db: Session = Depends(get_db)) -> None:
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    db.delete(channel)
    db.commit()
