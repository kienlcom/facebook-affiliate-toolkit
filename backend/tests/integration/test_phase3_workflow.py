from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.claims.service import ClaimService
from app.config.settings import Settings
from app.core.errors import ConflictError
from app.db.models import Account, ApiCall, AppState, Job, JobAttempt, Session
from app.db.session import build_sessionmaker
from app.main import app
from app.providers.tds.models import (
    TDSClaimResult,
    TDSClaimStatus,
    TDSRequestContext,
    load_provider_config,
)
from app.sessions.service import SessionService
from app.ws.manager import WebSocketManager

FIXTURE_DIR = Path(__file__).parents[2] / "api_spike" / "fixtures"
TDS_BASE_URL = "https://traodoisub.com/api/"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


async def reset_workflow_database() -> None:
    settings = Settings(_env_file=None, TDS_ACCESS_TOKEN="test-token")
    session_factory = build_sessionmaker(settings)
    engine = session_factory.kw["bind"]
    async with session_factory() as db:
        await db.execute(delete(ApiCall))
        await db.execute(delete(AppState))
        await db.execute(delete(JobAttempt))
        await db.execute(delete(Job))
        await db.execute(delete(Session))
        await db.execute(update(Account).values(status="ACTIVE"))
        await db.commit()
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_workflow_database() -> None:
    asyncio.run(reset_workflow_database())
    yield
    asyncio.run(reset_workflow_database())


def test_rest_fetch_dedup_state_actions_warning_and_websocket() -> None:
    with respx.mock(assert_all_called=True) as router:
        profile_route = router.get(
            TDS_BASE_URL,
            params={"fields": "profile", "access_token": "test-token"},
        ).mock(return_value=httpx.Response(200, json=load_fixture("profile_success.json")))
        jobs_route = router.get(
            TDS_BASE_URL,
            params={"fields": "facebook_page", "access_token": "test-token"},
        ).mock(return_value=httpx.Response(200, json=load_fixture("jobs_success.json")))

        with TestClient(app) as client:
            account_response = client.get("/api/account/profile")
            assert account_response.status_code == 200
            assert account_response.json()["tds"]["balance"] == 81300
            assert "token" not in account_response.text.casefold()

            profiles_response = client.get("/api/profiles")
            assert profiles_response.status_code == 200
            assert profiles_response.json()[0]["key"] == "facebook_page"
            assert profiles_response.json()[1]["key"] == "facebook_follow"
            assert profiles_response.json()[1]["verification_status"] == "PILOT"

            created = client.post(
                "/api/sessions",
                json={"profile_key": "facebook_page"},
            )
            assert created.status_code == 201
            session_id = created.json()["id"]
            active = client.get("/api/sessions/active")
            assert active.status_code == 200
            assert active.json()["id"] == session_id

            with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
                fetched = client.post(f"/api/sessions/{session_id}/fetch")
                assert fetched.status_code == 200
                assert len(fetched.json()["jobs"]) == 2
                event = websocket.receive_json()
                assert event["event"] == "job.created"
                assert event["session_id"] == session_id
                assert "access_token" not in json.dumps(event)

                duplicate_fetch = client.post(f"/api/sessions/{session_id}/fetch")
                assert duplicate_fetch.status_code == 409
                assert duplicate_fetch.json()["error"]["code"] == "JOB_BATCH_ACTIVE"
                assert duplicate_fetch.json()["error"]["details"]["active_jobs"] == 2

                job_id = fetched.json()["jobs"][0]["id"]
                opened = client.post(f"/api/jobs/{job_id}/opened")
                assert opened.status_code == 200
                assert opened.json()["job"]["state"] == "WAITING_USER"

                second_job_id = fetched.json()["jobs"][1]["id"]
                blocked_open = client.post(f"/api/jobs/{second_job_id}/opened")
                assert blocked_open.status_code == 409
                assert blocked_open.json()["error"]["code"] == "JOB_WAITING_USER"

                state_event = websocket.receive_json()
                while state_event["event"] != "job.state_changed":
                    state_event = websocket.receive_json()
                assert state_event["data"]["state"] == "WAITING_USER"

                confirmed = client.post(f"/api/jobs/{job_id}/confirm")
                assert confirmed.status_code == 200
                assert confirmed.json()["job"]["state"] == "USER_CONFIRMED"

                summary = client.get(f"/api/sessions/{session_id}/summary")
                assert summary.status_code == 200
                assert summary.json()["auto_open"] == {
                        "available": False,
                        "mode": "frontend_manual",
                        "target": "host_pc",
                        "enabled": False,
                    "paused": False,
                    "state": "OFF",
                    "interval_seconds": 20,
                    "next_open_at": None,
                        "seconds_remaining": None,
                        "pending_job_id": None,
                        "reason": None,
                }
                assert summary.json()["counters"] == {
                    "fetched": 2,
                    "opened": 1,
                    "confirmed": 1,
                    "claimed": 0,
                    "failed": 0,
                    "points_earned": 0,
                }
                assert summary.json()["remaining_jobs"] == 18

                unavailable_auto_open = client.post(
                    f"/api/sessions/{session_id}/auto-open",
                    json={"enabled": True},
                )
                assert unavailable_auto_open.status_code == 409
                assert (
                    unavailable_auto_open.json()["error"]["code"]
                    == "AUTO_OPEN_NOT_AVAILABLE"
                )

                confirmed_again = client.post(f"/api/jobs/{job_id}/confirm")
                assert confirmed_again.status_code == 409
                error = confirmed_again.json()["error"]
                assert error["code"] == "JOB_INVALID_STATE"
                assert error["request_id"]

                warning = client.post(
                    f"/api/sessions/{session_id}/account-warning",
                    json={
                        "warning_type": "CHECKPOINT",
                        "note": "Facebook displayed a checkpoint",
                    },
                )
                assert warning.status_code == 200
                assert warning.json()["status"] == "STOPPED"
                assert warning.json()["stop_reason"] == "ACCOUNT_WARNING:CHECKPOINT"

                blocked_fetch = client.post(f"/api/sessions/{session_id}/fetch")
                assert blocked_fetch.status_code == 409
                assert blocked_fetch.json()["error"]["code"] == "SESSION_NOT_RUNNING"

    assert profile_route.call_count == 1
    assert jobs_route.call_count == 1


def test_fetch_deduplicates_across_completed_sessions() -> None:
    with respx.mock(assert_all_called=True) as router:
        jobs_route = router.get(
            TDS_BASE_URL,
            params={"fields": "facebook_page", "access_token": "test-token"},
        ).mock(return_value=httpx.Response(200, json=load_fixture("jobs_success.json")))

        with TestClient(app) as client:
            first_session = client.post(
                "/api/sessions",
                json={"profile_key": "facebook_page"},
            )
            assert first_session.status_code == 201
            first_session_id = first_session.json()["id"]

            duplicate_session = client.post(
                "/api/sessions",
                json={"profile_key": "facebook_page"},
            )
            assert duplicate_session.status_code == 409
            assert duplicate_session.json()["error"]["code"] == "SESSION_ALREADY_RUNNING"

            first_fetch = client.post(f"/api/sessions/{first_session_id}/fetch")
            assert first_fetch.status_code == 200
            assert len(first_fetch.json()["jobs"]) == 2

            for job in first_fetch.json()["jobs"]:
                opened = client.post(f"/api/jobs/{job['id']}/opened")
                assert opened.status_code == 200
                skipped = client.post(
                    f"/api/jobs/{job['id']}/skip",
                    json={"reason": "dedup test"},
                )
                assert skipped.status_code == 200

            stopped = client.post(
                f"/api/sessions/{first_session_id}/stop",
                json={"reason": "TEST_COMPLETED"},
            )
            assert stopped.status_code == 200

            second_session = client.post(
                "/api/sessions",
                json={"profile_key": "facebook_page"},
            )
            assert second_session.status_code == 201
            second_fetch = client.post(
                f"/api/sessions/{second_session.json()['id']}/fetch"
            )
            assert second_fetch.status_code == 200
            assert second_fetch.json()["jobs"] == []
            assert second_fetch.json()["duplicates_ignored"] == 2

    assert jobs_route.call_count == 2


class BlockingTDSClient:
    def __init__(self) -> None:
        self.review_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def submit_job_review(
        self,
        context: TDSRequestContext,
        *,
        profile_key: str,
        job_code: str,
    ) -> TDSClaimResult:
        del context, profile_key, job_code
        self.review_calls += 1
        self.started.set()
        await self.release.wait()
        return TDSClaimResult(
            status=TDSClaimStatus.CACHE_ACCEPTED,
            cache_count=1,
            message="Thành công",
            raw={"cache": 1, "msg": "Thành công", "error": ""},
        )

    async def settle_rewards(
        self,
        context: TDSRequestContext,
        *,
        profile_key: str,
    ) -> TDSClaimResult:
        del context, profile_key
        raise AssertionError("Settlement must not run below the verified threshold")


async def seed_confirmed_job(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_code: str,
) -> UUID:
    now = datetime.now(UTC)
    async with session_factory() as db:
        account = await db.scalar(select(Account).limit(1))
        assert account is not None
        session = Session(
            id=uuid4(),
            account_id=account.id,
            profile_key="facebook_page",
            provider="tds",
            platform="facebook",
            status="RUNNING",
            started_at=now - timedelta(minutes=1),
            jobs_fetched=1,
            max_jobs=20,
            max_duration_minutes=30,
        )
        job = Job(
            id=uuid4(),
            account_id=account.id,
            session_id=session.id,
            external_id=str(uuid4().int),
            profile_key="facebook_page",
            provider="tds",
            platform="facebook",
            job_field="facebook_page",
            claim_type="facebook_page_cache",
            url="https://www.facebook.com/123456789",
            action_label="page",
            state="USER_CONFIRMED",
            fetched_at=now - timedelta(seconds=20),
            opened_at=now - timedelta(seconds=10),
            user_confirmed_at=now - timedelta(seconds=5),
            raw_job_json={"code": job_code, "type": "page"},
        )
        db.add_all([session, job])
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_two_concurrent_claims_make_one_provider_request_and_write_db() -> None:
    settings = Settings(_env_file=None, TDS_ACCESS_TOKEN="test-token")
    session_factory = build_sessionmaker(settings)
    engine = session_factory.kw["bind"]
    provider_config = load_provider_config()
    ws_manager = WebSocketManager()
    session_service = SessionService(
        settings=settings,
        session_factory=session_factory,
        provider_config=provider_config,
        ws_manager=ws_manager,
    )
    fake_client = BlockingTDSClient()
    claim_service = ClaimService(
        session_factory=session_factory,
        tds_client=fake_client,  # type: ignore[arg-type]
        session_service=session_service,
        provider_config=provider_config,
        ws_manager=ws_manager,
        sleep=lambda seconds: asyncio.sleep(0),
    )

    job_id = await seed_confirmed_job(
        session_factory,
        job_code="CONCURRENT-JOB-CODE",
    )

    first_claim = asyncio.create_task(claim_service.claim(job_id))
    await fake_client.started.wait()
    with pytest.raises(ConflictError) as second_error:
        await claim_service.claim(job_id)
    assert second_error.value.code == "JOB_NOT_USER_CONFIRMED"
    fake_client.release.set()
    outcome = await first_claim

    assert fake_client.review_calls == 1
    assert outcome.status.value == "CLAIMED"
    assert outcome.points_added == 0
    assert outcome.settlement_pending is True

    async with session_factory() as db:
        stored_job = await db.get(Job, job_id)
        attempts = list(
            await db.scalars(select(JobAttempt).where(JobAttempt.job_id == job_id))
        )
        stored_session = await db.get(Session, stored_job.session_id)
    assert stored_job is not None
    assert stored_job.state == "CLAIMED"
    assert stored_job.claimed_at is not None
    assert len(attempts) == 1
    assert attempts[0].success is True
    assert stored_session is not None
    assert stored_session.jobs_claimed == 1

    with pytest.raises(ConflictError):
        await claim_service.claim(job_id)
    assert fake_client.review_calls == 1
    await engine.dispose()


class SettlingTDSClient:
    def __init__(self) -> None:
        self.review_calls = 0
        self.settlement_calls = 0

    async def submit_job_review(
        self,
        context: TDSRequestContext,
        *,
        profile_key: str,
        job_code: str,
    ) -> TDSClaimResult:
        del context, profile_key, job_code
        self.review_calls += 1
        return TDSClaimResult(
            status=TDSClaimStatus.CACHE_ACCEPTED,
            cache_count=5,
            message="Thành công",
            raw={"cache": 5, "msg": "Thành công", "error": ""},
        )

    async def settle_rewards(
        self,
        context: TDSRequestContext,
        *,
        profile_key: str,
    ) -> TDSClaimResult:
        del context, profile_key
        self.settlement_calls += 1
        return TDSClaimResult(
            status=TDSClaimStatus.SETTLED,
            balance=81300,
            jobs_success=3,
            points_earned=6300,
            message="+6300 Xu",
            raw={
                "success": 200,
                "data": {
                    "xu": 81300,
                    "job_success": 3,
                    "xu_them": 6300,
                    "msg": "+6300 Xu",
                },
            },
        )


@pytest.mark.asyncio
async def test_settlement_success_updates_points_and_attempt_response() -> None:
    settings = Settings(_env_file=None, TDS_ACCESS_TOKEN="test-token")
    session_factory = build_sessionmaker(settings)
    engine = session_factory.kw["bind"]
    provider_config = load_provider_config()
    ws_manager = WebSocketManager()
    session_service = SessionService(
        settings=settings,
        session_factory=session_factory,
        provider_config=provider_config,
        ws_manager=ws_manager,
    )
    fake_client = SettlingTDSClient()
    claim_service = ClaimService(
        session_factory=session_factory,
        tds_client=fake_client,  # type: ignore[arg-type]
        session_service=session_service,
        provider_config=provider_config,
        ws_manager=ws_manager,
        sleep=lambda seconds: asyncio.sleep(0),
    )
    job_id = await seed_confirmed_job(
        session_factory,
        job_code="SETTLEMENT-JOB-CODE",
    )

    outcome = await claim_service.claim(job_id)
    assert outcome.points_added == 6300
    assert outcome.balance_after == 81300
    assert outcome.settlement_pending is False
    assert fake_client.review_calls == 1
    assert fake_client.settlement_calls == 1

    async with session_factory() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        session = await db.get(Session, job.session_id)
        attempt = await db.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        )
    assert session is not None
    assert session.jobs_claimed == 1
    assert session.points_earned == 6300
    assert attempt is not None
    assert attempt.success is True
    assert attempt.response_json["settlement"]["data"]["xu_them"] == 6300
    await engine.dispose()
