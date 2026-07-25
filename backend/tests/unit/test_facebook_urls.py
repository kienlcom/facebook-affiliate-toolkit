from __future__ import annotations

import pytest

from app.platforms.facebook.urls import is_valid_facebook_url, validate_facebook_url


@pytest.mark.parametrize(
    "url",
    [
        "https://facebook.com/example",
        "https://www.facebook.com/example",
        "https://m.facebook.com/example",
        "https://business.facebook.com/example",
        "https://fb.watch/example",
    ],
)
def test_valid_facebook_https_urls(url: str) -> None:
    assert is_valid_facebook_url(url)
    assert validate_facebook_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://facebook.com/example",
        "https://example.com/facebook",
        "javascript:alert(1)",
        "file:///tmp/a",
        "",
        "not a url",
    ],
)
def test_invalid_facebook_urls(url: str) -> None:
    assert not is_valid_facebook_url(url)
    with pytest.raises(ValueError):
        validate_facebook_url(url)
