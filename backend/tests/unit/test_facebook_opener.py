from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from app.platforms.facebook.opener import (
    HostCompanionLinkOpener,
    LocalBrowserLinkOpener,
)

COMPANION_URL = "http://host.docker.internal:18765/open"


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


def test_host_companion_opener_sends_authenticated_validated_request() -> None:
    opener = HostCompanionLinkOpener(
        endpoint=COMPANION_URL,
        token="bridge-secret",
        timeout_seconds=2,
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.post(COMPANION_URL).mock(
            return_value=httpx.Response(200, json={"status": "opened"})
        )

        assert opener.open("https://www.facebook.com/123456") is True

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer bridge-secret"
    assert request.content == b'{"url":"https://www.facebook.com/123456"}'


def test_host_companion_opener_fails_closed_on_transport_error() -> None:
    opener = HostCompanionLinkOpener(
        endpoint=COMPANION_URL,
        token="bridge-secret",
        timeout_seconds=2,
    )
    with respx.mock(assert_all_called=True) as router:
        router.post(COMPANION_URL).mock(
            side_effect=httpx.ConnectError("companion unavailable")
        )

        assert opener.open("https://facebook.com/123456") is False


def test_host_companion_opener_validates_before_network_call() -> None:
    opener = HostCompanionLinkOpener(
        endpoint=COMPANION_URL,
        token="bridge-secret",
        timeout_seconds=2,
    )
    with respx.mock(assert_all_called=False) as router:
        route = router.post(COMPANION_URL)
        with pytest.raises(ValueError):
            opener.open("file:///tmp/untrusted")

    assert route.called is False
