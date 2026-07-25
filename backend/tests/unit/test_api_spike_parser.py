from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from api_spike.parser_prototype import (
    PrototypeErrorCode,
    PrototypeParseError,
    PrototypeResult,
    PrototypeResultType,
    parse_claim,
    parse_jobs,
    parse_profile,
)

FIXTURE_DIR = Path(__file__).parents[2] / "api_spike" / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_parse_profile_success() -> None:
    result = parse_profile(load_fixture("profile_success.json"))
    assert result.result_type is PrototypeResultType.PROFILE
    assert result.payload["username"] == "kienlcom"
    assert result.payload["balance"] == 81300


def test_parse_jobs_success_builds_facebook_url() -> None:
    result = parse_jobs(load_fixture("jobs_success.json"))
    assert result.result_type is PrototypeResultType.JOBS
    assert result.payload["jobs"][0]["code"] == "XNFWMQ4A09LEWXJRF16H"
    assert result.payload["jobs"][0]["url"] == "https://www.facebook.com/1135126193022919"


def test_parse_jobs_empty_is_not_auth_error() -> None:
    result = parse_jobs(load_fixture("jobs_empty.json"))
    assert result.result_type is PrototypeResultType.NO_JOBS
    assert result.payload["jobs"] == []


def test_parse_claim_cache_and_settlement_success() -> None:
    cache_result = parse_claim(load_fixture("claim_cache_success.json"))
    settlement_result = parse_claim(load_fixture("claim_success.json"))
    assert cache_result == PrototypeResult(PrototypeResultType.CLAIM_CACHE_ACCEPTED, {"cache": 5})
    assert settlement_result.result_type is PrototypeResultType.CLAIM_SUCCESS
    assert settlement_result.payload["points_earned"] == 6300


@pytest.mark.parametrize(
    ("fixture_name", "parser", "expected_code"),
    [
        ("profile_invalid_token.json", parse_profile, PrototypeErrorCode.AUTH_ERROR),
        ("jobs_account_not_configured.json", parse_jobs, PrototypeErrorCode.ACCOUNT_NOT_CONFIGURED),
        ("claim_too_fast.json", parse_claim, PrototypeErrorCode.CLAIM_TOO_FAST),
        ("claim_rejected.json", parse_claim, PrototypeErrorCode.CLAIM_REJECTED),
        ("claim_auth_error.json", parse_claim, PrototypeErrorCode.AUTH_ERROR),
    ],
)
def test_known_errors(
    fixture_name: str,
    parser: Callable[[dict[str, Any]], PrototypeResult],
    expected_code: PrototypeErrorCode,
) -> None:
    with pytest.raises(PrototypeParseError) as exc_info:
        parser(load_fixture(fixture_name))
    assert exc_info.value.code is expected_code


@pytest.mark.parametrize("parser", [parse_profile, parse_jobs, parse_claim])
def test_unknown_json_fails_clearly(
    parser: Callable[[dict[str, Any]], PrototypeResult],
) -> None:
    with pytest.raises(PrototypeParseError) as exc_info:
        parser({"unexpected": True})
    assert exc_info.value.code is PrototypeErrorCode.UNKNOWN_RESPONSE
