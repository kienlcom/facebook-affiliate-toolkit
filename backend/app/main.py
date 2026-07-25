from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes.account import router as account_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.ws import router as ws_router
from app.claims.service import ClaimService
from app.config.settings import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.redaction import redact
from app.core.security.token_store import LocalEnvTokenStore
from app.db.session import build_sessionmaker
from app.jobs.service import JobsService
from app.providers.tds.client import TDSClient
from app.providers.tds.error_mapping import map_provider_error
from app.providers.tds.errors import TDSProviderError
from app.providers.tds.models import load_provider_config
from app.sessions.service import SessionService
from app.ws.manager import WebSocketManager

logger = logging.getLogger(__name__)


def _error_response(
    *,
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "details": redact(details or {}),
            }
        },
    )


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    session_factory = build_sessionmaker(settings)
    engine = session_factory.kw["bind"]
    provider_config = load_provider_config()
    ws_manager = WebSocketManager()
    token_store = LocalEnvTokenStore(settings)
    tds_client = TDSClient(
        settings=settings,
        token_store=token_store,
        session_factory=session_factory,
        provider_config=provider_config,
    )
    session_service = SessionService(
        settings=settings,
        session_factory=session_factory,
        provider_config=provider_config,
        ws_manager=ws_manager,
    )
    jobs_service = JobsService(
        session_factory=session_factory,
        tds_client=tds_client,
        session_service=session_service,
        provider_config=provider_config,
        ws_manager=ws_manager,
    )
    claim_service = ClaimService(
        session_factory=session_factory,
        tds_client=tds_client,
        session_service=session_service,
        provider_config=provider_config,
        ws_manager=ws_manager,
    )

    async with engine.connect() as connection:
        await connection.execute(text("select 1"))
    await session_service.recover_interrupted_sessions()

    fastapi_app.state.settings = settings
    fastapi_app.state.session_factory = session_factory
    fastapi_app.state.provider_config = provider_config
    fastapi_app.state.ws_manager = ws_manager
    fastapi_app.state.tds_client = tds_client
    fastapi_app.state.session_service = session_service
    fastapi_app.state.jobs_service = jobs_service
    fastapi_app.state.claim_service = claim_service
    try:
        yield
    finally:
        await tds_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    fastapi_app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @fastapi_app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            supplied_request_id
            if supplied_request_id and len(supplied_request_id) <= 128
            else str(uuid.uuid4())
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @fastapi_app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @fastapi_app.exception_handler(TDSProviderError)
    async def provider_error_handler(
        request: Request,
        exc: TDSProviderError,
    ) -> JSONResponse:
        mapped = map_provider_error(exc)
        return _error_response(
            request=request,
            code=mapped.code,
            message=mapped.message,
            status_code=mapped.status_code,
            details=mapped.details,
        )

    @fastapi_app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            code="REQUEST_VALIDATION_ERROR",
            message="Request validation failed",
            status_code=422,
            details=exc.errors(),
        )

    @fastapi_app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(
            request=request,
            code="HTTP_ERROR",
            message=str(exc.detail),
            status_code=exc.status_code,
        )

    @fastapi_app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(
            "request.unhandled_error",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "error_code": type(exc).__name__,
                "status": 500,
            },
        )
        return _error_response(
            request=request,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred",
            status_code=500,
        )

    fastapi_app.include_router(health_router)
    fastapi_app.include_router(account_router)
    fastapi_app.include_router(profiles_router)
    fastapi_app.include_router(sessions_router)
    fastapi_app.include_router(jobs_router)
    fastapi_app.include_router(ws_router)
    return fastapi_app


app = create_app()
