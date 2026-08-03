from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest


def load_companion_module() -> ModuleType:
    script_path = (
        Path(__file__).parents[3] / "scripts" / "host_link_opener.py"
    )
    spec = importlib.util.spec_from_file_location("host_link_opener", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Host Link Opener script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


companion = load_companion_module()


@pytest.mark.parametrize(
    "url",
    [
        "http://facebook.com/123",
        "https://example.com/123",
        "file:///tmp/untrusted",
        "https://user:password@facebook.com/123",
        "https://facebook.com:444/123",
    ],
)
def test_companion_url_validator_rejects_untrusted_url(url: str) -> None:
    with pytest.raises(ValueError):
        companion.validate_facebook_url(url)


def test_companion_requires_auth_and_dispatches_valid_url() -> None:
    token = "s" * 64
    server = companion.HostLinkOpenerServer(("127.0.0.1", 0), token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/open"
    body = json.dumps({"url": "https://www.facebook.com/123"}).encode()

    try:
        unauthorized = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(unauthorized, timeout=2)
        assert error.value.code == 401

        authorized = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with patch.object(
            companion.webbrowser,
            "open",
            return_value=True,
        ) as browser_open:
            with urllib.request.urlopen(authorized, timeout=2) as response:
                payload = json.loads(response.read())

        assert payload == {"status": "opened"}
        browser_open.assert_called_once_with(
            "https://www.facebook.com/123",
            new=2,
            autoraise=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
