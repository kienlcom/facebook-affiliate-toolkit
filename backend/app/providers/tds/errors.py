from __future__ import annotations

from datetime import datetime
from typing import Any


class TDSProviderError(Exception):
    code = "TDS_PROVIDER_ERROR"
    retryable = False

    def __init__(self, message: str, *, response_json: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response_json = response_json


class TDSAuthError(TDSProviderError):
    code = "TDS_AUTH_ERROR"


class TDSAccountNotConfiguredError(TDSProviderError):
    code = "TDS_ACCOUNT_NOT_CONFIGURED"


class TDSTooFastError(TDSProviderError):
    code = "TDS_TOO_FAST"

    def __init__(
        self,
        message: str,
        *,
        countdown: float | None = None,
        response_json: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, response_json=response_json)
        self.countdown = countdown


class TDSClaimRejectedError(TDSProviderError):
    code = "TDS_CLAIM_REJECTED"


class TDSUnknownResponseError(TDSProviderError):
    code = "TDS_UNKNOWN_RESPONSE"


class TDSInvalidResponseError(TDSProviderError):
    code = "TDS_INVALID_RESPONSE"


class TDSHttpError(TDSProviderError):
    code = "TDS_HTTP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        response_json: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, response_json=response_json)
        self.status_code = status_code


class TDSTransportError(TDSProviderError):
    code = "TDS_TRANSPORT_ERROR"
    retryable = True


class TDSTimeoutError(TDSTransportError):
    code = "TDS_TIMEOUT"


class TDSNetworkError(TDSTransportError):
    code = "TDS_NETWORK_ERROR"


class TDSUnavailableError(TDSTransportError):
    code = "TDS_TEMPORARY_HTTP_ERROR"

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class TDSRateLimitError(TDSProviderError):
    code = "TDS_RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int,
        retry_at: datetime,
        response_json: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, response_json=response_json)
        self.retry_after_seconds = retry_after_seconds
        self.retry_at = retry_at


class TDSCircuitOpenError(TDSProviderError):
    code = "TDS_CIRCUIT_OPEN"

    def __init__(self, message: str, *, retry_at: datetime) -> None:
        super().__init__(message)
        self.retry_at = retry_at
