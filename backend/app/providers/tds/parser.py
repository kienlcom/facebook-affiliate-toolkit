from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    TDSJob,
    TDSJobProfile,
    TDSJobsResult,
    TDSProfileEndpoint,
    TDSProfileResult,
)


def _require_success_status(status_code: int, payload: dict[str, Any]) -> None:
    if not 200 <= status_code < 300:
        raise TDSHttpError(
            f"TDS returned HTTP {status_code}",
            status_code=status_code,
            response_json=payload,
        )


def _error_message(payload: dict[str, Any]) -> str | None:
    value = payload.get("error")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _raise_common_error(payload: dict[str, Any]) -> None:
    message = _error_message(payload)
    if message is None:
        return
    normalized = message.casefold()
    if "access token" in normalized:
        raise TDSAuthError(message, response_json=payload)
    if "chưa được thêm vào cấu hình" in normalized:
        raise TDSAccountNotConfiguredError(message, response_json=payload)
    raise TDSUnknownResponseError(message, response_json=payload)


def parse_profile(
    status_code: int,
    headers: Mapping[str, str],
    payload: dict[str, Any],
    mapping: TDSProfileEndpoint,
) -> TDSProfileResult:
    del headers
    _require_success_status(status_code, payload)
    _raise_common_error(payload)

    data = payload.get(mapping.data_field)
    if payload.get("success") != 200 or not isinstance(data, dict):
        raise TDSUnknownResponseError("Unknown TDS profile response", response_json=payload)
    try:
        return TDSProfileResult(
            username=str(data[mapping.username_field]),
            balance=int(data[mapping.balance_field]),
            secondary_balance=int(data[mapping.secondary_balance_field]),
            facebook_id=str(data[mapping.facebook_id_field]),
            raw=payload,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TDSUnknownResponseError("Invalid TDS profile fields", response_json=payload) from exc


def parse_jobs(
    status_code: int,
    headers: Mapping[str, str],
    payload: dict[str, Any],
    profile: TDSJobProfile,
) -> TDSJobsResult:
    del headers
    _require_success_status(status_code, payload)
    _raise_common_error(payload)

    mapping = profile.response_mapping
    raw_jobs = payload.get(mapping.jobs_field)
    if not isinstance(raw_jobs, list):
        raise TDSUnknownResponseError("Unknown TDS jobs response", response_json=payload)

    jobs: list[TDSJob] = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, dict):
            raise TDSUnknownResponseError("Invalid TDS job item", response_json=payload)
        try:
            external_id = str(raw_job[mapping.external_id_field]).strip()
            code = str(raw_job[mapping.code_field]).strip()
            action = str(raw_job[mapping.action_field]).strip()
        except KeyError as exc:
            raise TDSUnknownResponseError("Missing TDS job field", response_json=payload) from exc
        if not external_id or not code or not action:
            raise TDSUnknownResponseError("Empty TDS job field", response_json=payload)
        jobs.append(
            TDSJob(
                external_id=external_id,
                code=code,
                action=action,
                url=profile.url_template.format(external_id=external_id),
                raw=raw_job,
            )
        )

    try:
        cache_count = int(payload.get(mapping.cache_field, 0))
    except (TypeError, ValueError) as exc:
        raise TDSUnknownResponseError("Invalid TDS cache field", response_json=payload) from exc
    return TDSJobsResult(jobs=jobs, cache_count=cache_count)


def parse_claim(
    status_code: int,
    headers: Mapping[str, str],
    payload: dict[str, Any],
) -> TDSClaimResult:
    del headers
    _require_success_status(status_code, payload)

    message = _error_message(payload)
    if message is not None:
        normalized = message.casefold()
        if "access token" in normalized:
            raise TDSAuthError(message, response_json=payload)
        if "quá nhanh" in normalized:
            countdown_value = payload.get("countdown")
            countdown = float(countdown_value) if isinstance(countdown_value, (int, float)) else None
            raise TDSTooFastError(message, countdown=countdown, response_json=payload)
        raise TDSClaimRejectedError(message, response_json=payload)

    data = payload.get("data")
    if payload.get("success") == 200 and isinstance(data, dict):
        try:
            return TDSClaimResult(
                status=TDSClaimStatus.SETTLED,
                balance=int(data["xu"]),
                jobs_success=int(data["job_success"]),
                points_earned=int(data["xu_them"]),
                message=str(data["msg"]),
                raw=payload,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TDSUnknownResponseError("Invalid TDS settlement fields", response_json=payload) from exc

    cache_value = payload.get("cache")
    if isinstance(cache_value, int) and cache_value >= 0 and payload.get("msg") == "Thành công":
        return TDSClaimResult(
            status=TDSClaimStatus.CACHE_ACCEPTED,
            cache_count=cache_value,
            message=str(payload["msg"]),
            raw=payload,
        )

    raise TDSUnknownResponseError("Unknown TDS claim response", response_json=payload)
