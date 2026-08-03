from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
    "fb.watch",
}
MAX_REQUEST_BYTES = 4096

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("host_link_opener")


def validate_facebook_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("URL is required")
    url = value.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("URL port is invalid") from error
    if (
        parsed.scheme != "https"
        or (host not in FACEBOOK_HOSTS and not host.endswith(".facebook.com"))
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise ValueError("Only HTTPS Facebook URLs are allowed")
    return url


class HostLinkOpenerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str) -> None:
        super().__init__(address, HostLinkOpenerHandler)
        self.token = token


class HostLinkOpenerHandler(BaseHTTPRequestHandler):
    server: HostLinkOpenerServer

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
            return
        self._send_json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/open":
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "not_found"})
            return
        if not self._is_authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"status": "unauthorized"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"status": "invalid_request"})
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"status": "invalid_request"},
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            url = validate_facebook_url(
                payload.get("url") if isinstance(payload, dict) else None
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"status": "invalid_url"})
            return

        try:
            opened = bool(webbrowser.open(url, new=2, autoraise=True))
        except webbrowser.Error as error:
            logger.error(
                "browser dispatch failed",
                extra={"error_code": type(error).__name__},
            )
            opened = False

        if not opened:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"status": "open_failed"},
            )
            return
        logger.info("validated Facebook URL dispatched to default browser")
        self._send_json(HTTPStatus.OK, {"status": "opened"})

    def _is_authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.token}"
        return hmac.compare_digest(supplied, expected)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        logger.info(
            "request client=%s status=%s",
            self.client_address[0],
            args[1] if len(args) > 1 else "unknown",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Facebook URL opener")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get("HOST_LINK_OPENER_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError(
            "HOST_LINK_OPENER_TOKEN must contain at least 32 characters"
        )
    server = HostLinkOpenerServer((args.host, args.port), token)
    logger.info("host link opener listening on port %s", args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("host link opener stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
