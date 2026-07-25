from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "cookie",
    "set-cookie",
    "code",
    "refresh_token",
    "client_secret",
    "token",
    "tds_access_token",
}


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {item.replace("-", "_") for item in SENSITIVE_KEYS}


def redact_url(value: str) -> str:
    split = urlsplit(value)
    if not split.scheme or not split.netloc:
        return value
    query = [
        (key, REDACTED if is_sensitive_key(key) else item_value)
        for key, item_value in parse_qsl(split.query, keep_blank_values=True)
    ]
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_url(value)
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_sensitive_key(key):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value
