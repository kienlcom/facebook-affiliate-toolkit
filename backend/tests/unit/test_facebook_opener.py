from __future__ import annotations

from unittest.mock import patch

import pytest

from app.platforms.facebook.opener import LocalBrowserLinkOpener


def test_local_browser_opener_validates_and_opens_a_new_tab() -> None:
    opener = LocalBrowserLinkOpener()

    with patch("app.platforms.facebook.opener.webbrowser.open", return_value=True) as opened:
        assert opener.open("https://www.facebook.com/123456") is True

    opened.assert_called_once_with(
        "https://www.facebook.com/123456",
        new=2,
        autoraise=True,
    )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://example.com/123",
    ],
)
def test_local_browser_opener_rejects_untrusted_urls(url: str) -> None:
    opener = LocalBrowserLinkOpener()

    with patch("app.platforms.facebook.opener.webbrowser.open") as opened:
        with pytest.raises(ValueError):
            opener.open(url)

    opened.assert_not_called()
