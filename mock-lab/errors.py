"""Error contract cho mock lab.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §8.
"""

from __future__ import annotations

from typing import Any

CODE_TO_HTTP: dict[str, int] = {
    "INVALID_REQUEST": 400,
    "INVALID_SCENARIO": 400,
    "TEST_ENDPOINT_DISABLED": 403,
    "SESSION_NOT_FOUND": 404,
    "JOB_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "SESSION_NOT_RUNNING": 409,
    "SESSION_PAUSED": 409,
    "JOB_INVALID_STATE": 409,
    "VERIFICATION_FAILED": 409,
    "ACTION_NOT_VERIFIED": 409,
    "ALREADY_CLAIMED": 409,
    "JOB_ALREADY_CLAIMING": 409,
    "CLAIM_TOO_EARLY": 409,
    "SETTLEMENT_NOT_READY": 409,
    "SETTLEMENT_TOO_EARLY": 409,
    "RATE_LIMITED": 429,
    "RUNNER_ALREADY_RUNNING": 409,
    "RUNNER_NOT_FOUND": 404,
    "MOCK_API_OFFLINE": 503,
    "INTERNAL_ERROR": 500,
}

DEFAULT_MESSAGES: dict[str, str] = {
    "INVALID_REQUEST": "Request payload or query parameter is invalid.",
    "INVALID_SCENARIO": "Scenario is not part of the closed enum.",
    "TEST_ENDPOINT_DISABLED": "This endpoint is only available when app_env=test.",
    "SESSION_NOT_FOUND": "Session does not exist.",
    "JOB_NOT_FOUND": "Job does not exist.",
    "NOT_FOUND": "Resource does not exist.",
    "SESSION_NOT_RUNNING": "Session is not running.",
    "SESSION_PAUSED": "Session is paused for safety.",
    "JOB_INVALID_STATE": "Job transition is not allowed from the current state.",
    "VERIFICATION_FAILED": "Verification could not prove the action was completed.",
    "ACTION_NOT_VERIFIED": "Job action has not been verified.",
    "ALREADY_CLAIMED": "Job was already claimed.",
    "JOB_ALREADY_CLAIMING": "Job claim is already being processed.",
    "CLAIM_TOO_EARLY": "Claim is not eligible yet.",
    "SETTLEMENT_NOT_READY": "Settlement threshold has not been reached.",
    "SETTLEMENT_TOO_EARLY": "Settlement wait has not elapsed.",
    "RATE_LIMITED": "Provider rate limit is active.",
    "RUNNER_ALREADY_RUNNING": "A Selenium runner is already running.",
    "RUNNER_NOT_FOUND": "Runner job does not exist.",
    "MOCK_API_OFFLINE": "Mock API is unavailable.",
    "INTERNAL_ERROR": "Unexpected internal error.",
}


class ApiError(Exception):
    """Lỗi có mã ổn định, map sang HTTP status theo bảng §8."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, code)
        self.details = details or {}
        super().__init__(f"{code}: {self.message}")

    @property
    def http_status(self) -> int:
        return CODE_TO_HTTP.get(self.code, 500)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }
