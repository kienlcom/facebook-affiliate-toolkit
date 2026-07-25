"""Offline parser prototype for sanitized TDS fixtures.

This module intentionally performs no network I/O. Phase 2 ports these
verified response classifications into the production provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PrototypeResultType(StrEnum):
    PROFILE = "PROFILE"
    JOBS = "JOBS"
    NO_JOBS = "NO_JOBS"
    CLAIM_CACHE_ACCEPTED = "CLAIM_CACHE_ACCEPTED"
    CLAIM_SUCCESS = "CLAIM_SUCCESS"


class PrototypeErrorCode(StrEnum):
    AUTH_ERROR = "AUTH_ERROR"
    ACCOUNT_NOT_CONFIGURED = "ACCOUNT_NOT_CONFIGURED"
    CLAIM_TOO_FAST = "CLAIM_TOO_FAST"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    UNKNOWN_RESPONSE = "UNKNOWN_RESPONSE"


class PrototypeParseError(ValueError):
    def __init__(self, code: PrototypeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PrototypeResult:
    result_type: PrototypeResultType
    payload: dict[str, Any]


def _error_message(payload: dict[str, Any]) -> str | None:
    value = payload.get("error")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _raise_known_error(payload: dict[str, Any], *, claim: bool = False) -> None:
    message = _error_message(payload)
    if message is None:
        return
    normalized = message.casefold()
    if "access token" in normalized:
        raise PrototypeParseError(PrototypeErrorCode.AUTH_ERROR, message)
    if "chưa được thêm vào cấu hình" in normalized:
        raise PrototypeParseError(PrototypeErrorCode.ACCOUNT_NOT_CONFIGURED, message)
    if claim and "quá nhanh" in normalized:
        raise PrototypeParseError(PrototypeErrorCode.CLAIM_TOO_FAST, message)
    if claim:
        raise PrototypeParseError(PrototypeErrorCode.CLAIM_REJECTED, message)
    raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, message)


def parse_profile(payload: dict[str, Any]) -> PrototypeResult:
    _raise_known_error(payload)
    data = payload.get("data")
    if payload.get("success") != 200 or not isinstance(data, dict):
        raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Unknown profile response")
    try:
        normalized = {
            "username": str(data["user"]),
            "balance": int(data["xu"]),
            "secondary_balance": int(data["xudie"]),
            "facebook_id": str(data["idfb"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Invalid profile fields") from exc
    return PrototypeResult(PrototypeResultType.PROFILE, normalized)


def parse_jobs(payload: dict[str, Any]) -> PrototypeResult:
    _raise_known_error(payload)
    raw_jobs = payload.get("data")
    if not isinstance(raw_jobs, list):
        raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Unknown jobs response")

    jobs: list[dict[str, str]] = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, dict):
            raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Invalid job item")
        try:
            external_id = str(raw_job["id"])
            code = str(raw_job["code"])
            action = str(raw_job["type"])
        except KeyError as exc:
            raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Missing job field") from exc
        if not external_id or not code or not action:
            raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Empty job field")
        jobs.append(
            {
                "external_id": external_id,
                "code": code,
                "action": action,
                "url": f"https://www.facebook.com/{external_id}",
            }
        )

    result_type = PrototypeResultType.NO_JOBS if not jobs else PrototypeResultType.JOBS
    return PrototypeResult(result_type, {"cache": int(payload.get("cache", 0)), "jobs": jobs})


def parse_claim(payload: dict[str, Any]) -> PrototypeResult:
    _raise_known_error(payload, claim=True)
    data = payload.get("data")
    if payload.get("success") == 200 and isinstance(data, dict):
        try:
            normalized = {
                "balance": int(data["xu"]),
                "jobs_success": int(data["job_success"]),
                "points_earned": int(data["xu_them"]),
                "message": str(data["msg"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Invalid claim fields") from exc
        return PrototypeResult(PrototypeResultType.CLAIM_SUCCESS, normalized)

    cache = payload.get("cache")
    if isinstance(cache, int) and cache >= 0 and payload.get("msg") == "Thành công":
        return PrototypeResult(PrototypeResultType.CLAIM_CACHE_ACCEPTED, {"cache": cache})

    raise PrototypeParseError(PrototypeErrorCode.UNKNOWN_RESPONSE, "Unknown claim response")
