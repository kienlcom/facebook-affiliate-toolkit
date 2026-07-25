from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from time import perf_counter
from typing import Any, TypeVar
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential, wait_none

from app.config.settings import Settings
from app.core.redaction import redact, redact_url
from app.core.security.token_store import TokenStore
from app.db.models import ApiCall, AppState
from app.providers.tds.errors import (
    TDSCircuitOpenError,
    TDSHttpError,
    TDSInvalidResponseError,
    TDSNetworkError,
    TDSProviderError,
    TDSRateLimitError,
    TDSTimeoutError,
    TDSTransportError,
    TDSUnavailableError,
)
from app.providers.tds.models import (
    TDSClaimResult,
    TDSJobsResult,
    TDSProfileResult,
    TDSProviderConfig,
    TDSRequestContext,
    load_provider_config,
)
from app.providers.tds.parser import parse_claim, parse_jobs, parse_profile

ResultT = TypeVar("ResultT")
Parser = Callable[[int, Mapping[str, str], dict[str, Any]], ResultT]

CIRCUIT_STATE_KEY = "tds:circuit_breaker"
DEFAULT_RETRY_AFTER_SECONDS = 60
RETRYABLE_STATUS_CODES = {502, 503, 504}

logger = logging.getLogger(__name__)


class _RetryableAttempt(Exception):
    def __init__(self, final_error: TDSProviderError) -> None:
        super().__init__(final_error.code)
        self.final_error = final_error


class TDSClient:
    def __init__(
        self,
        *,
        settings: Settings,
        token_store: TokenStore,
        session_factory: async_sessionmaker[AsyncSession],
        provider_config: TDSProviderConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
        retry_base_delay_seconds: float = 2,
    ) -> None:
        self._settings = settings
        self._token_store = token_store
        self._session_factory = session_factory
        self._config = provider_config or load_provider_config()
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=str(settings.TDS_BASE_URL),
            timeout=httpx.Timeout(settings.TDS_REQUEST_TIMEOUT_SECONDS),
            follow_redirects=False,
        )

    async def __aenter__(self) -> TDSClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def fetch_profile(self, context: TDSRequestContext) -> TDSProfileResult:
        mapping = self._config.profile
        return await self._execute(
            context=context,
            operation="profile",
            method=mapping.method,
            path=mapping.path,
            params={"fields": mapping.fields},
            parser=lambda status, headers, payload: parse_profile(status, headers, payload, mapping),
        )

    async def fetch_jobs(self, context: TDSRequestContext, profile_key: str) -> TDSJobsResult:
        profile = self._config.get_enabled_profile(profile_key)
        return await self._execute(
            context=context,
            operation="get_jobs",
            method=profile.job_method,
            path=profile.job_path,
            params={"fields": profile.job_field},
            parser=lambda status, headers, payload: parse_jobs(status, headers, payload, profile),
        )

    async def submit_job_review(
        self,
        context: TDSRequestContext,
        *,
        profile_key: str,
        job_code: str,
    ) -> TDSClaimResult:
        profile = self._config.get_enabled_profile(profile_key)
        if not job_code.strip():
            raise ValueError("job_code must not be empty")
        return await self._execute(
            context=context,
            operation="claim_review",
            method=profile.claim_method,
            path=profile.claim_path,
            params={"type": profile.claim_type, "id": job_code},
            parser=parse_claim,
        )

    async def settle_rewards(
        self,
        context: TDSRequestContext,
        *,
        profile_key: str,
    ) -> TDSClaimResult:
        profile = self._config.get_enabled_profile(profile_key)
        return await self._execute(
            context=context,
            operation="claim_settlement",
            method=profile.claim_method,
            path=profile.claim_path,
            params={"type": profile.settlement_type, "id": profile.settlement_id},
            parser=parse_claim,
        )

    async def _execute(
        self,
        *,
        context: TDSRequestContext,
        operation: str,
        method: str,
        path: str,
        params: dict[str, str],
        parser: Parser[ResultT],
    ) -> ResultT:
        await self._ensure_circuit_allows_request(context.account_id)
        token = await self._token_store.get_token(context.account_id, "tds_access_token")
        request_params = {**params, "access_token": token}
        wait_strategy = (
            wait_none()
            if self._retry_base_delay_seconds <= 0
            else wait_exponential(
                multiplier=self._retry_base_delay_seconds,
                min=self._retry_base_delay_seconds,
                max=self._retry_base_delay_seconds * 2,
            )
        )
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._settings.TDS_MAX_RETRIES + 1),
            wait=wait_strategy,
            retry=retry_if_exception_type(_RetryableAttempt),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    result = await self._single_attempt(
                        context=context,
                        operation=operation,
                        method=method,
                        path=path,
                        params=request_params,
                        parser=parser,
                    )
                    await self._close_circuit(context.account_id)
                    return result
        except _RetryableAttempt as exc:
            raise exc.final_error from None
        raise RuntimeError("TDS retry loop completed without a result")

    async def _single_attempt(
        self,
        *,
        context: TDSRequestContext,
        operation: str,
        method: str,
        path: str,
        params: dict[str, str],
        parser: Parser[ResultT],
    ) -> ResultT:
        request = self._http_client.build_request(method, path, params=params)
        safe_url = redact_url(str(request.url))
        started = perf_counter()
        try:
            response = await self._http_client.send(request)
        except httpx.TimeoutException as exc:
            duration_ms = self._duration_ms(started)
            error = TDSTimeoutError("TDS request timed out")
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=None,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=None,
                retry_after_seconds=None,
            )
            raise _RetryableAttempt(error) from None
        except httpx.NetworkError as exc:
            duration_ms = self._duration_ms(started)
            error = TDSNetworkError("Temporary TDS network error")
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=None,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=None,
                retry_after_seconds=None,
            )
            raise _RetryableAttempt(error) from None
        except httpx.TransportError as exc:
            duration_ms = self._duration_ms(started)
            error = TDSTransportError("TDS transport error")
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=None,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=None,
                retry_after_seconds=None,
            )
            raise error from None

        duration_ms = self._duration_ms(started)
        status_code = response.status_code
        headers = dict(response.headers)
        best_effort_payload = self._best_effort_payload(response)

        if status_code == 429:
            retry_after_seconds = self._parse_retry_after(response.headers)
            retry_at = datetime.now(UTC) + timedelta(seconds=retry_after_seconds)
            error = TDSRateLimitError(
                "TDS rate limit is active",
                retry_after_seconds=retry_after_seconds,
                retry_at=retry_at,
                response_json=best_effort_payload,
            )
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=status_code,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=best_effort_payload,
                retry_after_seconds=retry_after_seconds,
            )
            await self._open_circuit(context.account_id, error)
            logger.warning(
                "tds.rate_limited",
                extra={
                    "account_id": str(context.account_id),
                    "session_id": str(context.session_id) if context.session_id else None,
                    "job_id": str(context.job_id) if context.job_id else None,
                    "provider": "tds",
                    "status": status_code,
                    "error_code": error.code,
                },
            )
            raise error

        if status_code in RETRYABLE_STATUS_CODES:
            error = TDSUnavailableError(
                f"TDS temporarily unavailable with HTTP {status_code}",
                status_code=status_code,
            )
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=status_code,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=best_effort_payload,
                retry_after_seconds=None,
            )
            raise _RetryableAttempt(error)

        if not 200 <= status_code < 300:
            error = TDSHttpError(
                f"TDS returned HTTP {status_code}",
                status_code=status_code,
                response_json=best_effort_payload,
            )
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=status_code,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=best_effort_payload,
                retry_after_seconds=None,
            )
            raise error

        try:
            payload = self._decode_json_object(response)
            result = parser(status_code, headers, payload)
        except TDSProviderError as error:
            await self._persist_api_call(
                context=context,
                operation=operation,
                method=method,
                url_redacted=safe_url,
                status_code=status_code,
                duration_ms=duration_ms,
                success=False,
                error_code=error.code,
                response_json=error.response_json or best_effort_payload,
                retry_after_seconds=None,
            )
            raise

        await self._persist_api_call(
            context=context,
            operation=operation,
            method=method,
            url_redacted=safe_url,
            status_code=status_code,
            duration_ms=duration_ms,
            success=True,
            error_code=None,
            response_json=payload,
            retry_after_seconds=None,
        )
        return result

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))

    @staticmethod
    def _decode_json_object(response: httpx.Response) -> dict[str, Any]:
        raw_body = response.content.strip()
        content_type = response.headers.get("content-type", "").casefold()
        if not raw_body:
            raise TDSInvalidResponseError("TDS returned an empty body")
        if "text/html" in content_type or raw_body.startswith(b"<"):
            raise TDSInvalidResponseError("TDS returned HTML instead of JSON")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TDSInvalidResponseError("TDS returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TDSInvalidResponseError("TDS JSON response must be an object")
        return payload

    @staticmethod
    def _best_effort_payload(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except ValueError:
            body = response.text.strip()
            return {"body": body[:2000]} if body else None
        return payload if isinstance(payload, dict) else {"body": payload}

    @staticmethod
    def _parse_retry_after(headers: Mapping[str, str]) -> int:
        value = headers.get("retry-after")
        if value is None:
            return DEFAULT_RETRY_AFTER_SECONDS
        try:
            return max(0, int(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return DEFAULT_RETRY_AFTER_SECONDS
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0, math.ceil((retry_at - datetime.now(UTC)).total_seconds()))

    async def _persist_api_call(
        self,
        *,
        context: TDSRequestContext,
        operation: str,
        method: str,
        url_redacted: str,
        status_code: int | None,
        duration_ms: int,
        success: bool,
        error_code: str | None,
        response_json: dict[str, Any] | None,
        retry_after_seconds: int | None,
    ) -> None:
        safe_response = redact(response_json) if response_json is not None else None
        async with self._session_factory() as session:
            session.add(
                ApiCall(
                    account_id=context.account_id,
                    session_id=context.session_id,
                    job_id=context.job_id,
                    provider="tds",
                    operation=operation,
                    method=method,
                    url_redacted=url_redacted,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    success=success,
                    error_code=error_code,
                    response_json=safe_response,
                    retry_after_seconds=retry_after_seconds,
                )
            )
            await session.commit()

    async def _ensure_circuit_allows_request(self, account_id: UUID) -> None:
        async with self._session_factory() as session:
            state = await session.scalar(
                select(AppState).where(
                    AppState.account_id == account_id,
                    AppState.key == CIRCUIT_STATE_KEY,
                )
            )
            if state is None or state.value_json.get("state") != "OPEN":
                return
            retry_at_raw = state.value_json.get("retry_at")
            try:
                retry_at = datetime.fromisoformat(str(retry_at_raw))
            except ValueError as exc:
                raise TDSCircuitOpenError(
                    "TDS circuit state is invalid",
                    retry_at=datetime.now(UTC) + timedelta(seconds=DEFAULT_RETRY_AFTER_SECONDS),
                ) from exc
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            if retry_at > datetime.now(UTC):
                raise TDSCircuitOpenError("TDS circuit is open", retry_at=retry_at)
            state.value_json = {
                **state.value_json,
                "state": "HALF_OPEN",
                "half_opened_at": datetime.now(UTC).isoformat(),
            }
            await session.commit()

    async def _open_circuit(self, account_id: UUID, error: TDSRateLimitError) -> None:
        now = datetime.now(UTC)
        value = {
            "state": "OPEN",
            "opened_at": now.isoformat(),
            "retry_at": error.retry_at.isoformat(),
            "retry_after_seconds": error.retry_after_seconds,
        }
        statement = insert(AppState).values(
            account_id=account_id,
            key=CIRCUIT_STATE_KEY,
            value_json=value,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[AppState.account_id, AppState.key],
            set_={"value_json": value, "updated_at": now},
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()

    async def _close_circuit(self, account_id: UUID) -> None:
        async with self._session_factory() as session:
            state = await session.scalar(
                select(AppState).where(
                    AppState.account_id == account_id,
                    AppState.key == CIRCUIT_STATE_KEY,
                )
            )
            if state is None or state.value_json.get("state") == "CLOSED":
                return
            state.value_json = {
                "state": "CLOSED",
                "closed_at": datetime.now(UTC).isoformat(),
            }
            await session.commit()
