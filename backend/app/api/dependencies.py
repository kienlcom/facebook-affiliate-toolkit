from __future__ import annotations

from fastapi import Request

from app.claims.service import ClaimService
from app.jobs.service import JobsService
from app.providers.tds.client import TDSClient
from app.providers.tds.models import TDSProviderConfig
from app.sessions.service import SessionService
from app.ws.manager import WebSocketManager


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_jobs_service(request: Request) -> JobsService:
    return request.app.state.jobs_service


def get_claim_service(request: Request) -> ClaimService:
    return request.app.state.claim_service


def get_tds_client(request: Request) -> TDSClient:
    return request.app.state.tds_client


def get_provider_config(request: Request) -> TDSProviderConfig:
    return request.app.state.provider_config


def get_ws_manager(request: Request) -> WebSocketManager:
    return request.app.state.ws_manager
