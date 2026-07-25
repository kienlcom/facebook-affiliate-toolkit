from __future__ import annotations

import logging

from app.core.logging import configure_logging
from app.core.redaction import REDACTED, redact, redact_url


def test_redacts_query_token() -> None:
    assert redact_url("https://example.test/api?access_token=abc&x=1") == "https://example.test/api?access_token=%5BREDACTED%5D&x=1"


def test_redacts_authorization_and_cookie_headers() -> None:
    payload = {"Authorization": "Bearer abc", "Cookie": "session=abc", "ok": "yes"}
    assert redact(payload) == {"Authorization": REDACTED, "Cookie": REDACTED, "ok": "yes"}


def test_redacts_nested_json_secrets() -> None:
    payload = {"outer": [{"refresh_token": "abc"}, {"client_secret": "xyz"}]}
    assert redact(payload) == {"outer": [{"refresh_token": REDACTED}, {"client_secret": REDACTED}]}


def test_redacts_oauth_code() -> None:
    payload = {"code": "oauth-code"}
    assert redact(payload) == {"code": REDACTED}


def test_configure_logging_suppresses_http_client_request_urls() -> None:
    configure_logging("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
