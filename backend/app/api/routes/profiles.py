from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_provider_config
from app.providers.tds.models import TDSProviderConfig
from app.schemas.profile import JobProfileResponse

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("", response_model=list[JobProfileResponse])
async def profiles(
    config: TDSProviderConfig = Depends(get_provider_config),
) -> list[JobProfileResponse]:
    return [
        JobProfileResponse(
            key=profile.key,
            display_name=profile.display_name,
            provider=profile.provider,
            platform=profile.platform,
            minimum_claim_wait_seconds=profile.minimum_claim_wait_seconds,
            settlement_threshold=profile.settlement_threshold,
        )
        for profile in config.profiles
        if profile.enabled and profile.verified_at
    ]
