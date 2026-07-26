from __future__ import annotations

from app.core.errors import AppError
from app.providers.tds.errors import (
    TDSAccountNotConfiguredError,
    TDSAuthError,
    TDSCircuitOpenError,
    TDSClaimRejectedError,
    TDSHttpError,
    TDSInvalidResponseError,
    TDSProviderError,
    TDSRateLimitError,
    TDSTooFastError,
    TDSTransportError,
    TDSUnknownResponseError,
)


def map_provider_error(error: TDSProviderError) -> AppError:
    if isinstance(error, TDSAuthError):
        return AppError(
            code=error.code,
            message="TDS access token is invalid",
            status_code=401,
        )
    if isinstance(error, TDSAccountNotConfiguredError):
        return AppError(
            code=error.code,
            message="Facebook account is not configured in TDS",
            status_code=409,
        )
    if isinstance(error, TDSTooFastError):
        return AppError(
            code=error.code,
            message="TDS requires more time before this operation",
            status_code=425,
            details={"countdown": error.countdown},
        )
    if isinstance(error, TDSClaimRejectedError):
        if "job không hợp lệ" in str(error).casefold():
            return AppError(
                code=error.code,
                message=(
                    "TDS báo job không hợp lệ nên không cộng xu. "
                    "Hãy bỏ qua job này và lấy batch mới; nếu lỗi lặp lại, "
                    "dừng phiên và không tiếp tục claim."
                ),
                status_code=422,
                details={
                    "reason": "INVALID_JOB",
                    "provider_message": "Job không hợp lệ",
                    "action": "SKIP_AND_FETCH_FRESH_BATCH",
                },
            )
        if "không cướp job" in str(error).casefold():
            return AppError(
                code=error.code,
                message=(
                    "TDS no longer recognizes this job as active; "
                    "load a fresh batch and finish it before fetching another"
                ),
                status_code=422,
                details={"reason": "JOB_NOT_ACTIVE_IN_TDS"},
            )
        return AppError(
            code=error.code,
            message="TDS rejected the claim",
            status_code=422,
            details={"reason": "PROVIDER_REJECTED"},
        )
    if isinstance(error, TDSRateLimitError):
        return AppError(
            code=error.code,
            message="TDS rate limit is active",
            status_code=429,
            details={
                "retry_after_seconds": error.retry_after_seconds,
                "retry_at": error.retry_at.isoformat(),
            },
        )
    if isinstance(error, TDSCircuitOpenError):
        return AppError(
            code=error.code,
            message="TDS circuit breaker is open",
            status_code=429,
            details={"retry_at": error.retry_at.isoformat()},
        )
    if isinstance(error, TDSTransportError):
        return AppError(
            code=error.code,
            message="TDS is temporarily unavailable",
            status_code=503,
        )
    if isinstance(error, (TDSInvalidResponseError, TDSUnknownResponseError)):
        return AppError(
            code=error.code,
            message="TDS returned an unrecognized response",
            status_code=502,
        )
    if isinstance(error, TDSHttpError):
        return AppError(
            code=error.code,
            message="TDS returned an HTTP error",
            status_code=502,
            details={"provider_status_code": error.status_code},
        )
    return AppError(
        code=error.code,
        message="TDS provider operation failed",
        status_code=502,
    )
