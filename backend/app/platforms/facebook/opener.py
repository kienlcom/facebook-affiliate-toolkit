from __future__ import annotations

import logging
import webbrowser
from typing import Protocol

import httpx

from app.platforms.facebook.urls import validate_facebook_url

logger = logging.getLogger(__name__)


class LinkOpener(Protocol):
    def open(self, url: str) -> bool:
        """Open one already validated URL and report whether dispatch succeeded."""


class LocalBrowserLinkOpener:
    def open(self, url: str) -> bool:
        validated_url = validate_facebook_url(url)
        return bool(webbrowser.open(validated_url, new=2, autoraise=True))


class HostCompanionLinkOpener:
    def __init__(
        self,
        *,
        endpoint: str,
        token: str,
        timeout_seconds: float,
    ) -> None:
        self._endpoint = endpoint
        self._token = token
        self._timeout_seconds = timeout_seconds

    def open(self, url: str) -> bool:
        validated_url = validate_facebook_url(url)
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    self._endpoint,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"url": validated_url},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning(
                "facebook.host_companion_open_failed",
                extra={"error_code": type(error).__name__},
            )
            return False
        return (
            isinstance(payload, dict)
            and payload.get("status") == "opened"
        )
