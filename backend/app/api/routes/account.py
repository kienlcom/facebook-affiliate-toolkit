from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_session_service, get_tds_client
from app.providers.tds.client import TDSClient
from app.providers.tds.models import TDSRequestContext
from app.schemas.account import AccountProfileResponse, TDSAccountProfile
from app.sessions.service import SessionService

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/profile", response_model=AccountProfileResponse)
async def account_profile(
    session_service: SessionService = Depends(get_session_service),
    tds_client: TDSClient = Depends(get_tds_client),
) -> AccountProfileResponse:
    account = await session_service.get_local_account()
    profile = await tds_client.fetch_profile(
        TDSRequestContext(account_id=account.id)
    )
    return AccountProfileResponse(
        account_id=account.id,
        display_name=account.display_name,
        tds=TDSAccountProfile(
            username=profile.username,
            balance=profile.balance,
            status="VALID",
        ),
    )
