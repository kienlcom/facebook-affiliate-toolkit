from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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
    LINK_OPENER_TRANSPORT: Literal["direct", "host_companion"] = "direct"
    AUTO_OPEN_ENABLED: bool = False
    AUTO_OPEN_INTERVAL_SECONDS: int = 20
    HOST_LINK_OPENER_URL: str = "http://host.docker.internal:18765/open"
    HOST_LINK_OPENER_TOKEN: SecretStr | None = None
    HOST_LINK_OPENER_TIMEOUT_SECONDS: float = 5

    # Reel runner — lướt ảnh trên các trang trong bảng reel_links.
    # REEL_BASE_URL phải là origin của chính backend: Selenium mở URL này trực
    # tiếp, không đi qua vite proxy nên không suy ra được từ header Host.
    REEL_BASE_URL: str = "http://127.0.0.1:8000"
    REEL_DWELL_SECONDS: float = 5
    REEL_SELECTOR_TIMEOUT_SECONDS: float = 10
    REEL_MAX_IMAGES_PER_LINK: int = 200
    REEL_RUNNER_HEADED: bool = True
    REEL_IMAGE_DIRS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["image", "image2"]
    )

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

    @field_validator("REEL_IMAGE_DIRS", mode="before")
    @classmethod
    def parse_reel_image_dirs(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("REEL_IMAGE_DIRS")
    @classmethod
    def validate_reel_image_dirs(cls, value: list[str]) -> list[str]:
        for name in value:
            if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
                raise ValueError(f"REEL_IMAGE_DIRS entry must be a bare directory name: {name}")
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
        if self.HOST_LINK_OPENER_TIMEOUT_SECONDS <= 0:
            raise ValueError("HOST_LINK_OPENER_TIMEOUT_SECONDS must be > 0")
        if self.LINK_OPENER_TRANSPORT == "host_companion":
            if self.LINK_OPENER_MODE != "local_browser":
                raise ValueError(
                    "LINK_OPENER_TRANSPORT=host_companion requires "
                    "LINK_OPENER_MODE=local_browser"
                )
            opener_url = urlparse(self.HOST_LINK_OPENER_URL)
            if (
                opener_url.scheme != "http"
                or opener_url.hostname
                not in {"host.docker.internal", "127.0.0.1", "localhost"}
                or opener_url.path != "/open"
            ):
                raise ValueError(
                    "HOST_LINK_OPENER_URL must be a local HTTP /open endpoint"
                )
            opener_token = (
                self.HOST_LINK_OPENER_TOKEN.get_secret_value().strip()
                if self.HOST_LINK_OPENER_TOKEN is not None
                else ""
            )
            if len(opener_token) < 32:
                raise ValueError(
                    "HOST_LINK_OPENER_TOKEN must contain at least 32 characters"
                )
        reel_base = urlparse(self.REEL_BASE_URL)
        if reel_base.scheme not in {"http", "https"} or not reel_base.netloc:
            raise ValueError("REEL_BASE_URL must be a valid http(s) origin")
        if self.REEL_DWELL_SECONDS <= 0:
            raise ValueError("REEL_DWELL_SECONDS must be > 0")
        if self.REEL_SELECTOR_TIMEOUT_SECONDS <= 0:
            raise ValueError("REEL_SELECTOR_TIMEOUT_SECONDS must be > 0")
        if self.REEL_MAX_IMAGES_PER_LINK <= 0:
            raise ValueError("REEL_MAX_IMAGES_PER_LINK must be > 0")
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
