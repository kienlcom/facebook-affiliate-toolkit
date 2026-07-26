from __future__ import annotations

import webbrowser
from typing import Protocol

from app.platforms.facebook.urls import validate_facebook_url


class LinkOpener(Protocol):
    def open(self, url: str) -> bool:
        """Open one already validated URL and report whether dispatch succeeded."""


class LocalBrowserLinkOpener:
    def open(self, url: str) -> bool:
        validated_url = validate_facebook_url(url)
        return bool(webbrowser.open(validated_url, new=2, autoraise=True))
