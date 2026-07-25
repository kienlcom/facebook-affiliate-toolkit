from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from app.providers.tds.errors import (
    TDSAccountNotConfiguredError,
    TDSAuthError,
    TDSClaimRejectedError,
    TDSHttpError,
    TDSTooFastError,
    TDSUnknownResponseError,
)
from app.providers.tds.models import (
    TDSClaimResult,
    TDSClaimStatus,
    TDSJobsResult,
    TDSProfileResult,
    load_provider_config,
)
from app.providers.tds.parser import parse_claim, parse_jobs, parse_profile

FIXTURE_DIR = Path(__file__).parents[2] / "api_spike" / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_profile_parser_uses_verified_mapping() -> None:
    config = load_provider_config()
    result = parse_profile(200, {}, load_fixture("profile_success.json"), config.profile)
    assert result == TDSProfileResult(
        username="kienlcom",
        balance=81300,
        secondary_balance=0,
        facebook_id="100074844057308",
        raw=load_fixture("profile_success.json"),
    )


def test_jobs_parser_handles_jobs_and_empty_as_normal_results() -> None:
    profile = load_provider_config().get_enabled_profile("facebook_page")
    jobs = parse_jobs(200, {}, load_fixture("jobs_success.json"), profile)
    empty = parse_jobs(200, {}, load_fixture("jobs_empty.json"), profile)
    assert isinstance(jobs, TDSJobsResult)
    assert jobs.no_jobs is False
    assert jobs.jobs[0].code == "XNFWMQ4A09LEWXJRF16H"
    assert jobs.jobs[0].url == "https://www.facebook.com/1135126193022919"
    assert empty.no_jobs is True
    assert empty.jobs == []


def test_claim_parser_handles_cache_and_settlement_success() -> None:
    cached = parse_claim(200, {}, load_fixture("claim_cache_success.json"))
    settled = parse_claim(200, {}, load_fixture("claim_success.json"))
    assert cached == TDSClaimResult(
        status=TDSClaimStatus.CACHE_ACCEPTED,
        cache_count=5,
        message="Thành công",
        raw=load_fixture("claim_cache_success.json"),
    )
    assert settled.status is TDSClaimStatus.SETTLED
    assert settled.balance == 81300
    assert settled.jobs_success == 3
    assert settled.points_earned == 6300


@pytest.mark.parametrize(
    ("fixture_name", "parser", "error_type"),
    [
        (
            "profile_invalid_token.json",
            lambda payload: parse_profile(200, {}, payload, load_provider_config().profile),
            TDSAuthError,
        ),
        (
            "jobs_account_not_configured.json",
            lambda payload: parse_jobs(
                200,
                {},
                payload,
                load_provider_config().get_enabled_profile("facebook_page"),
            ),
            TDSAccountNotConfiguredError,
        ),
        ("claim_too_fast.json", lambda payload: parse_claim(200, {}, payload), TDSTooFastError),
        ("claim_rejected.json", lambda payload: parse_claim(200, {}, payload), TDSClaimRejectedError),
        ("claim_auth_error.json", lambda payload: parse_claim(200, {}, payload), TDSAuthError),
    ],
)
def test_verified_error_mapping(
    fixture_name: str,
    parser: Callable[[dict[str, Any]], object],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        parser(load_fixture(fixture_name))


@pytest.mark.parametrize(
    "parser",
    [
        lambda: parse_profile(200, {}, {"unexpected": True}, load_provider_config().profile),
        lambda: parse_jobs(
            200,
            {},
            {"unexpected": True},
            load_provider_config().get_enabled_profile("facebook_page"),
        ),
        lambda: parse_claim(200, {}, {"unexpected": True}),
    ],
)
def test_unknown_json_fails_clearly(parser: Callable[[], object]) -> None:
    with pytest.raises(TDSUnknownResponseError):
        parser()


def test_non_success_http_status_is_not_parsed_as_success() -> None:
    with pytest.raises(TDSHttpError) as exc_info:
        parse_claim(503, {}, load_fixture("claim_success.json"))
    assert exc_info.value.status_code == 503
