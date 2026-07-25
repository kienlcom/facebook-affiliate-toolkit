from __future__ import annotations

from urllib.parse import urlparse

FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
    "fb.watch",
}


def is_valid_facebook_url(value: str) -> bool:
    if not value or not value.strip():
        return False
    parsed = urlparse(value.strip())
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in FACEBOOK_HOSTS or host.endswith(".facebook.com")


def validate_facebook_url(value: str) -> str:
    if not is_valid_facebook_url(value):
        raise ValueError("URL must be an HTTPS Facebook URL")
    return value.strip()
