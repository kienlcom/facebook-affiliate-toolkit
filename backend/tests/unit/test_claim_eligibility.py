from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.claims.service import can_claim
from app.core.errors import ConflictError, TooEarlyError
from app.db.models import Account, Job, Session
from app.jobs.state_machine import JobState

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def eligible_records() -> tuple[Job, Session, Account]:
    account_id = uuid4()
    session_id = uuid4()
    account = Account(
        id=account_id,
        display_name="Local User",
        status="ACTIVE",
    )
    session = Session(
        id=session_id,
        account_id=account_id,
        profile_key="facebook_page",
        provider="tds",
        platform="facebook",
        status="RUNNING",
        started_at=NOW - timedelta(minutes=1),
        max_jobs=20,
        max_duration_minutes=30,
        jobs_fetched=1,
    )
    job = Job(
        id=uuid4(),
        account_id=account_id,
        session_id=session_id,
        external_id="123456789",
        profile_key="facebook_page",
        provider="tds",
        platform="facebook",
        job_field="facebook_page",
        claim_type="facebook_page_cache",
        url="https://www.facebook.com/123456789",
        state=JobState.USER_CONFIRMED,
        fetched_at=NOW - timedelta(seconds=20),
        opened_at=NOW - timedelta(seconds=10),
        user_confirmed_at=NOW - timedelta(seconds=5),
        raw_job_json={"code": "JOB-CODE"},
    )
    return job, session, account


def test_valid_claim_is_eligible() -> None:
    job, session, account = eligible_records()
    can_claim(job, session, account, now=NOW, minimum_wait_seconds=3)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda job, session, account: setattr(job, "opened_at", None), "JOB_NOT_OPENED"),
        (
            lambda job, session, account: setattr(job, "user_confirmed_at", None),
            "JOB_CONFIRMATION_MISSING",
        ),
        (
            lambda job, session, account: setattr(session, "status", "STOPPED"),
            "SESSION_NOT_RUNNING",
        ),
        (
            lambda job, session, account: setattr(account, "status", "PROTECTION_STOP"),
            "ACCOUNT_PROTECTION_STOP",
        ),
        (
            lambda job, session, account: setattr(job, "claimed_at", NOW),
            "JOB_ALREADY_CLAIMED",
        ),
        (
            lambda job, session, account: setattr(job, "state", JobState.USER_SKIPPED),
            "JOB_NOT_USER_CONFIRMED",
        ),
    ],
)
def test_claim_ineligibility(
    mutation,
    expected_code: str,
) -> None:
    job, session, account = eligible_records()
    mutation(job, session, account)
    with pytest.raises(ConflictError) as exc_info:
        can_claim(job, session, account, now=NOW, minimum_wait_seconds=3)
    assert exc_info.value.code == expected_code


def test_server_minimum_wait_is_enforced() -> None:
    job, session, account = eligible_records()
    job.opened_at = NOW - timedelta(seconds=1)
    with pytest.raises(TooEarlyError) as exc_info:
        can_claim(job, session, account, now=NOW, minimum_wait_seconds=3)
    assert exc_info.value.code == "CLAIM_TOO_EARLY"
    assert exc_info.value.details["retry_after_seconds"] == 2


def test_session_duration_limit_blocks_claim() -> None:
    job, session, account = eligible_records()
    session.started_at = NOW - timedelta(minutes=31)
    with pytest.raises(ConflictError) as exc_info:
        can_claim(job, session, account, now=NOW, minimum_wait_seconds=3)
    assert exc_info.value.code == "SESSION_LIMIT_REACHED"
