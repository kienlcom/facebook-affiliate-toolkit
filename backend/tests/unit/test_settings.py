from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"TDS_ACCESS_TOKEN": "secret-token"}
    values.update(overrides)
    return Settings(**values)


def test_valid_settings_pass() -> None:
    settings = make_settings()
    assert settings.FETCH_MODE == "manual"
    assert settings.LINK_OPENER_MODE == "frontend_manual"
    assert settings.AUTO_OPEN_ENABLED is False
    assert settings.AUTO_OPEN_INTERVAL_SECONDS == 20


@pytest.mark.parametrize("token", ["", "replace_me", "   "])
def test_missing_token_fails(token: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(TDS_ACCESS_TOKEN=token)


def test_http_tds_base_url_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(TDS_BASE_URL="http://traodoisub.com/api/")


def test_invalid_retry_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(TDS_MAX_RETRIES=6)


def test_auto_poll_true_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(AUTO_POLL_ENABLED=True)


def test_local_browser_auto_open_settings_pass_for_local_backend() -> None:
    settings = make_settings(
        APP_ENV="local",
        LINK_OPENER_MODE="local_browser",
        AUTO_OPEN_ENABLED=True,
        AUTO_OPEN_INTERVAL_SECONDS=20,
    )

    assert settings.LINK_OPENER_MODE == "local_browser"
    assert settings.AUTO_OPEN_ENABLED is True


def test_auto_open_enabled_with_manual_opener_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(
            LINK_OPENER_MODE="frontend_manual",
            AUTO_OPEN_ENABLED=True,
        )


def test_local_browser_fails_closed_for_hosted_environment() -> None:
    with pytest.raises(ValidationError):
        make_settings(
            APP_ENV="production",
            LINK_OPENER_MODE="local_browser",
        )


def test_non_positive_auto_open_interval_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(AUTO_OPEN_INTERVAL_SECONDS=0)


def test_auto_claim_true_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(AUTO_CLAIM_WITHOUT_CONFIRMATION=True)


def test_manual_confirmation_false_fails() -> None:
    with pytest.raises(ValidationError):
        make_settings(REQUIRE_MANUAL_CONFIRMATION=False)


def test_missing_finite_session_limits_fail() -> None:
    with pytest.raises(ValidationError):
        make_settings(MAX_JOBS_PER_SESSION=0)
    with pytest.raises(ValidationError):
        make_settings(MAX_SESSION_DURATION_MINUTES=0)


@pytest.mark.parametrize(
    "flag",
    [
        "HONOR_RETRY_AFTER",
        "STOP_ON_FACEBOOK_WARNING",
        "STOP_ON_CHECKPOINT",
        "STOP_ON_TEMPORARY_BLOCK",
        "STOP_ON_IDENTITY_VERIFICATION",
    ],
)
def test_required_safety_flags_cannot_be_disabled(flag: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{flag: False})
