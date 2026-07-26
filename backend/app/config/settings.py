from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_ENV: str = "development"
    APP_NAME: str = "Facebook TDS Job Assistant"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://tds:tds@localhost:5432/tds_assistant"
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

    TDS_BASE_URL: AnyHttpUrl = "https://traodoisub.com/api/"
    TDS_ACCESS_TOKEN: str
    TDS_REQUEST_TIMEOUT_SECONDS: float = 15
    TDS_MAX_RETRIES: int = 3

    FETCH_MODE: Literal["manual"] = "manual"
    AUTO_POLL_ENABLED: bool = False
    LINK_OPENER_MODE: Literal["frontend_manual", "local_browser"] = "frontend_manual"
    AUTO_OPEN_ENABLED: bool = False
    AUTO_OPEN_INTERVAL_SECONDS: int = 20

    MIN_SECONDS_BEFORE_CONFIRM: int = 2
    MIN_SECONDS_BEFORE_CLAIM: int = 3
    MAX_JOBS_PER_SESSION: int = 20
    MAX_SESSION_DURATION_MINUTES: int = 30

    REQUIRE_MANUAL_CONFIRMATION: bool = True
    AUTO_CLAIM_WITHOUT_CONFIRMATION: bool = False

    HONOR_RETRY_AFTER: bool = True
    STOP_ON_FACEBOOK_WARNING: bool = True
    STOP_ON_CHECKPOINT: bool = True
    STOP_ON_TEMPORARY_BLOCK: bool = True
    STOP_ON_IDENTITY_VERIFICATION: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        for origin in value:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid CORS origin: {origin}")
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "postgresql+asyncpg" or not parsed.netloc:
            raise ValueError("DATABASE_URL must be a valid postgresql+asyncpg URL")
        return value

    @model_validator(mode="after")
    def fail_fast(self) -> Settings:
        token = self.TDS_ACCESS_TOKEN.strip()
        if not token or token == "replace_me":
            raise ValueError("TDS_ACCESS_TOKEN must be provided and cannot be replace_me")
        if str(self.TDS_BASE_URL).lower().startswith("http://"):
            raise ValueError("TDS_BASE_URL must use HTTPS")
        if self.TDS_REQUEST_TIMEOUT_SECONDS <= 0:
            raise ValueError("TDS_REQUEST_TIMEOUT_SECONDS must be > 0")
        if not 0 <= self.TDS_MAX_RETRIES <= 5:
            raise ValueError("TDS_MAX_RETRIES must be between 0 and 5")
        if self.AUTO_POLL_ENABLED:
            raise ValueError("AUTO_POLL_ENABLED must be false in MVP")
        if self.AUTO_OPEN_ENABLED and self.LINK_OPENER_MODE != "local_browser":
            raise ValueError(
                "AUTO_OPEN_ENABLED requires LINK_OPENER_MODE=local_browser"
            )
        if (
            self.LINK_OPENER_MODE == "local_browser"
            and self.APP_ENV.casefold() not in {"development", "local", "test"}
        ):
            raise ValueError(
                "LINK_OPENER_MODE=local_browser is only valid for a local backend"
            )
        if self.AUTO_OPEN_INTERVAL_SECONDS <= 0:
            raise ValueError("AUTO_OPEN_INTERVAL_SECONDS must be > 0")
        if self.MAX_JOBS_PER_SESSION <= 0:
            raise ValueError("MAX_JOBS_PER_SESSION must be > 0")
        if self.MAX_SESSION_DURATION_MINUTES <= 0:
            raise ValueError("MAX_SESSION_DURATION_MINUTES must be > 0")
        if not self.REQUIRE_MANUAL_CONFIRMATION:
            raise ValueError("REQUIRE_MANUAL_CONFIRMATION must be true")
        if self.AUTO_CLAIM_WITHOUT_CONFIRMATION:
            raise ValueError("AUTO_CLAIM_WITHOUT_CONFIRMATION must be false")
        if not self.HONOR_RETRY_AFTER:
            raise ValueError("HONOR_RETRY_AFTER must be true")
        if not self.STOP_ON_FACEBOOK_WARNING:
            raise ValueError("STOP_ON_FACEBOOK_WARNING must be true")
        if not self.STOP_ON_CHECKPOINT:
            raise ValueError("STOP_ON_CHECKPOINT must be true")
        if not self.STOP_ON_TEMPORARY_BLOCK:
            raise ValueError("STOP_ON_TEMPORARY_BLOCK must be true")
        if not self.STOP_ON_IDENTITY_VERIFICATION:
            raise ValueError("STOP_ON_IDENTITY_VERIFICATION must be true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
