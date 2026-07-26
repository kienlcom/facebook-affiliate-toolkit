from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.core.security.token_store import LocalEnvTokenStore
from app.db.models import Account, ApiCall, AppState
from app.db.session import build_sessionmaker
from app.providers.tds.client import CIRCUIT_STATE_KEY, TDSClient
from app.providers.tds.errors import (
    TDSClaimRejectedError,
    TDSCircuitOpenError,
    TDSHttpError,
    TDSInvalidResponseError,
    TDSRateLimitError,
    TDSUnavailableError,
)
from app.providers.tds.models import TDSClaimStatus, TDSRequestContext

FIXTURE_DIR = Path(__file__).parents[2] / "api_spike" / "fixtures"
BASE_URL = "https://traodoisub.com/api/"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@dataclass
class ClientTestState:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    account_id: UUID


@pytest.fixture
async def client_state() -> AsyncIterator[ClientTestState]:
    settings = Settings(
        _env_file=None,
        TDS_ACCESS_TOKEN="integration-secret-token",
        TDS_BASE_URL=BASE_URL,
        TDS_MAX_RETRIES=2,
    )
    session_factory = build_sessionmaker(settings)
    engine = session_factory.kw["bind"]
    async with session_factory() as session:
        account_id = await session.scalar(select(Account.id).limit(1))
        assert account_id is not None
        await session.execute(delete(ApiCall).where(ApiCall.account_id == account_id))
        await session.execute(delete(AppState).where(AppState.account_id == account_id))
        await session.commit()
    yield ClientTestState(settings, session_factory, engine, account_id)
    async with session_factory() as session:
        await session.execute(delete(ApiCall).where(ApiCall.account_id == account_id))
        await session.execute(delete(AppState).where(AppState.account_id == account_id))
        await session.commit()
    await engine.dispose()


def build_client(state: ClientTestState) -> TDSClient:
    return TDSClient(
        settings=state.settings,
        token_store=LocalEnvTokenStore(state.settings),
        session_factory=state.session_factory,
        retry_base_delay_seconds=0,
    )


@pytest.mark.asyncio
async def test_timeout_then_success_retries_and_persists_each_attempt(
    client_state: ClientTestState,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            BASE_URL,
            params={"fields": "facebook_page", "access_token": "integration-secret-token"},
        ).mock(
            side_effect=[
                httpx.ReadTimeout("temporary timeout"),
                httpx.Response(200, json=load_fixture("jobs_success.json")),
            ]
        )
        async with build_client(client_state) as client:
            result = await client.fetch_jobs(
                TDSRequestContext(account_id=client_state.account_id),
                "facebook_page",
            )

    assert route.call_count == 2
    assert len(result.jobs) == 2
    async with client_state.session_factory() as session:
        calls = list(
            await session.scalars(
                select(ApiCall)
                .where(ApiCall.account_id == client_state.account_id)
                .order_by(ApiCall.id)
            )
        )
    assert [call.success for call in calls] == [False, True]
    assert [call.error_code for call in calls] == ["TDS_TIMEOUT", None]
    assert all("integration-secret-token" not in call.url_redacted for call in calls)
    assert all("REDACTED" in call.url_redacted for call in calls)


@pytest.mark.asyncio
async def test_503_three_times_stops_after_bounded_retries(
    client_state: ClientTestState,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            BASE_URL,
            params={"fields": "profile", "access_token": "integration-secret-token"},
        ).mock(return_value=httpx.Response(503, json={"error": "maintenance"}))
        async with build_client(client_state) as client:
            with pytest.raises(TDSUnavailableError) as exc_info:
                await client.fetch_profile(TDSRequestContext(account_id=client_state.account_id))

    assert exc_info.value.status_code == 503
    assert route.call_count == 3
    async with client_state.session_factory() as session:
        calls = list(
            await session.scalars(
                select(ApiCall).where(ApiCall.account_id == client_state.account_id)
            )
        )
    assert len(calls) == 3
    assert all(call.error_code == "TDS_TEMPORARY_HTTP_ERROR" for call in calls)


@pytest.mark.asyncio
async def test_429_persists_retry_after_and_opens_circuit(
    client_state: ClientTestState,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            BASE_URL,
            params={"fields": "profile", "access_token": "integration-secret-token"},
        ).mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "30"},
                json={"error": "rate limited"},
            )
        )
        async with build_client(client_state) as client:
            with pytest.raises(TDSRateLimitError) as first_error:
                await client.fetch_profile(TDSRequestContext(account_id=client_state.account_id))
            with pytest.raises(TDSCircuitOpenError):
                await client.fetch_profile(TDSRequestContext(account_id=client_state.account_id))

    assert first_error.value.retry_after_seconds == 30
    assert route.call_count == 1
    async with client_state.session_factory() as session:
        call = await session.scalar(
            select(ApiCall).where(ApiCall.account_id == client_state.account_id)
        )
        state = await session.scalar(
            select(AppState).where(
                AppState.account_id == client_state.account_id,
                AppState.key == CIRCUIT_STATE_KEY,
            )
        )
    assert call is not None
    assert call.status_code == 429
    assert call.retry_after_seconds == 30
    assert call.error_code == "TDS_RATE_LIMITED"
    assert state is not None
    assert state.value_json["state"] == "OPEN"
    assert state.value_json["retry_after_seconds"] == 30


@pytest.mark.asyncio
async def test_html_body_fails_without_retry_and_is_recorded(
    client_state: ClientTestState,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            BASE_URL,
            params={"fields": "profile", "access_token": "integration-secret-token"},
        ).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html>maintenance</html>",
            )
        )
        async with build_client(client_state) as client:
            with pytest.raises(TDSInvalidResponseError):
                await client.fetch_profile(TDSRequestContext(account_id=client_state.account_id))

    assert route.call_count == 1
    async with client_state.session_factory() as session:
        call = await session.scalar(
            select(ApiCall).where(ApiCall.account_id == client_state.account_id)
        )
    assert call is not None
    assert call.success is False
    assert call.error_code == "TDS_INVALID_RESPONSE"
    assert "integration-secret-token" not in call.url_redacted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b""),
        httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            text="{not-json",
        ),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
)
async def test_malformed_success_body_fails_without_retry(
    client_state: ClientTestState,
    response: httpx.Response,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            BASE_URL,
            params={"fields": "profile", "access_token": "integration-secret-token"},
        ).mock(return_value=response)
        async with build_client(client_state) as client:
            with pytest.raises(TDSInvalidResponseError):
                await client.fetch_profile(TDSRequestContext(account_id=client_state.account_id))
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_non_retryable_http_error_is_attempted_once(
    client_state: ClientTestState,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            BASE_URL,
            params={"fields": "profile", "access_token": "integration-secret-token"},
        ).mock(return_value=httpx.Response(400, json={"error": "bad request"}))
        async with build_client(client_state) as client:
            with pytest.raises(TDSHttpError) as exc_info:
                await client.fetch_profile(TDSRequestContext(account_id=client_state.account_id))
    assert exc_info.value.status_code == 400
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_http_200_business_error_is_not_success_and_is_not_retried(
    client_state: ClientTestState,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            f"{BASE_URL}coin/",
            params={
                "type": "facebook_page",
                "id": "facebook_api",
                "access_token": "integration-secret-token",
            },
        ).mock(return_value=httpx.Response(200, json=load_fixture("claim_rejected.json")))
        async with build_client(client_state) as client:
            with pytest.raises(TDSClaimRejectedError):
                await client.settle_rewards(
                    TDSRequestContext(account_id=client_state.account_id),
                    profile_key="facebook_page",
                )

    assert route.call_count == 1
    async with client_state.session_factory() as session:
        call = await session.scalar(
            select(ApiCall).where(ApiCall.account_id == client_state.account_id)
        )
    assert call is not None
    assert call.status_code == 200
    assert call.success is False
    assert call.error_code == "TDS_CLAIM_REJECTED"


@pytest.mark.asyncio
async def test_review_uses_job_code_and_parses_cache_success(
    client_state: ClientTestState,
) -> None:
    job_code = "VERIFIED-JOB-CODE"
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            f"{BASE_URL}coin/",
            params={
                "type": "facebook_page_cache",
                "id": job_code,
                "access_token": "integration-secret-token",
            },
        ).mock(return_value=httpx.Response(200, json=load_fixture("claim_cache_success.json")))
        async with build_client(client_state) as client:
            result = await client.submit_job_review(
                TDSRequestContext(account_id=client_state.account_id),
                profile_key="facebook_page",
                job_code=job_code,
            )

    assert route.call_count == 1
    assert result.status is TDSClaimStatus.CACHE_ACCEPTED
    assert result.cache_count == 5


@pytest.mark.asyncio
async def test_facebook_follow_uses_official_jobs_review_and_settlement_mapping(
    client_state: ClientTestState,
) -> None:
    job_code = "PILOT-FOLLOW-CODE"
    with respx.mock(assert_all_called=True) as router:
        jobs_route = router.get(
            BASE_URL,
            params={
                "fields": "facebook_follow",
                "access_token": "integration-secret-token",
            },
        ).mock(
            return_value=httpx.Response(
                200,
                json=load_fixture("jobs_follow_success.json"),
            )
        )
        review_route = router.get(
            f"{BASE_URL}coin/",
            params={
                "type": "facebook_follow_cache",
                "id": job_code,
                "access_token": "integration-secret-token",
            },
        ).mock(
            return_value=httpx.Response(
                200,
                json=load_fixture("claim_cache_success.json"),
            )
        )
        settlement_route = router.get(
            f"{BASE_URL}coin/",
            params={
                "type": "facebook_follow",
                "id": "facebook_api",
                "access_token": "integration-secret-token",
            },
        ).mock(
            return_value=httpx.Response(
                200,
                json=load_fixture("claim_success.json"),
            )
        )

        async with build_client(client_state) as client:
            jobs = await client.fetch_jobs(
                TDSRequestContext(account_id=client_state.account_id),
                "facebook_follow",
            )
            review = await client.submit_job_review(
                TDSRequestContext(account_id=client_state.account_id),
                profile_key="facebook_follow",
                job_code=job_code,
            )
            settlement = await client.settle_rewards(
                TDSRequestContext(account_id=client_state.account_id),
                profile_key="facebook_follow",
            )

    assert jobs_route.call_count == 1
    assert review_route.call_count == 1
    assert settlement_route.call_count == 1
    assert len(jobs.jobs) == 8
    assert review.status is TDSClaimStatus.CACHE_ACCEPTED
    assert settlement.status is TDSClaimStatus.SETTLED
