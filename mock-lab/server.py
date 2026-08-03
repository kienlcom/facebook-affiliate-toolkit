"""HTTP layer cho mock lab.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §7.

File này chỉ làm routing và serialization. Toàn bộ domain logic nằm ở store.py
(§4.1), để concurrency test gọi thẳng được Store mà không lẫn nhiễu HTTP.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from errors import ApiError
from runner_service import RunnerManager
from store import SCENARIOS, Store

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"

MAX_DELAY_MS = 60_000


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Not JSON serializable: {type(value)!r}")


def dumps(payload: Any) -> bytes:
    return json.dumps(payload, default=_json_default, ensure_ascii=False).encode("utf-8")


class Route:
    """Ba mức guard, xem §7.15.1 và §7.16.

    operation=None      read-only/control-plane: không guard gì.
    use_circuit=False   chỉ chặn bởi api_offline. Dùng cho stop/pause/resume —
                        cleanup phải chạy được kể cả khi circuit đang mở.
    use_circuit=True    thêm circuit breaker. Chỉ fetch/claim/settle.
    """

    __slots__ = ("method", "pattern", "handler", "operation", "use_circuit")

    def __init__(
        self,
        method: str,
        pattern: str,
        handler: str,
        operation: str | None = None,
        use_circuit: bool = False,
    ) -> None:
        self.method = method
        self.pattern = re.compile(pattern)
        self.handler = handler
        self.operation = operation
        self.use_circuit = use_circuit


ROUTES: list[Route] = [
    Route("GET", r"^/health$", "health"),
    Route("GET", r"^/api/circuit$", "circuit"),
    Route("POST", r"^/api/runner/start$", "runner_start"),
    Route("GET", r"^/api/runner/status$", "runner_status"),
    Route("GET", r"^/api/runner/logs$", "runner_logs"),
    Route("POST", r"^/api/reset$", "reset"),
    Route("POST", r"^/api/_fault/(?P<mode>[a-z_]+)$", "set_fault"),
    Route("POST", r"^/api/sessions$", "create_session", operation="create_session"),
    Route("GET", r"^/api/jobs/next$", "next_job", operation="fetch", use_circuit=True),
    Route("GET", r"^/api/jobs/(?P<job_id>[0-9a-f-]+)$", "get_job"),
    Route(
        "POST",
        r"^/api/jobs/(?P<job_id>[0-9a-f-]+)/opened$",
        "mark_opened",
        operation="opened",
    ),
    Route(
        "POST",
        r"^/api/jobs/(?P<job_id>[0-9a-f-]+)/open-failed$",
        "mark_open_failed",
        operation="open_failed",
    ),
    Route("POST", r"^/api/mock-facebook/follow$", "follow", operation="follow"),
    Route("GET", r"^/api/mock-facebook/status$", "follow_status"),
    Route(
        "POST",
        r"^/api/jobs/(?P<job_id>[0-9a-f-]+)/verify-action$",
        "verify_action",
        operation="verify",
    ),
    Route(
        "POST",
        r"^/api/jobs/(?P<job_id>[0-9a-f-]+)/claim$",
        "claim",
        operation="claim",
        use_circuit=True,
    ),
    Route("POST", r"^/api/claims/settle$", "settle", operation="settle", use_circuit=True),
    Route(
        "POST",
        r"^/api/sessions/(?P<session_id>[0-9a-f-]+)/pause-for-safety$",
        "pause_for_safety",
        operation="pause",
    ),
    Route(
        "POST",
        r"^/api/sessions/(?P<session_id>[0-9a-f-]+)/resume$",
        "resume",
        operation="resume",
    ),
    Route(
        "POST",
        r"^/api/sessions/(?P<session_id>[0-9a-f-]+)/stop$",
        "stop",
        operation="stop",  # circuit-exempt nhưng vẫn chặn bởi api_offline
    ),
    Route("GET", r"^/api/sessions/(?P<session_id>[0-9a-f-]+)/summary$", "summary"),
    Route("GET", r"^/profiles/(?P<target_id>[^/?]+)$", "profile_page"),
    Route("GET", r"^/static/(?P<name>[a-zA-Z0-9_.-]+)$", "static_file"),
]


class MockHandler(BaseHTTPRequestHandler):
    server_version = "MockLab/1.3"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Tắt access log để không nhiễu output pytest."""

    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    @property
    def runner_manager(self) -> RunnerManager:
        return self.server.runner_manager  # type: ignore[attr-defined]

    @property
    def app_env(self) -> str:
        return self.server.app_env  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        self.query = parse_qs(parsed.query)
        # Body PHẢI được đọc hết trước khi trả response. Với HTTP/1.1 keep-alive,
        # bỏ sót body sẽ khiến byte thừa bị parse thành request line kế tiếp và
        # server trả 501 cho request sau đó.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        self.raw_body = self.rfile.read(length) if length > 0 else b""

        for route in ROUTES:
            if route.method != method:
                continue
            match = route.pattern.match(parsed.path)
            if match is None:
                continue
            try:
                handler: Callable[..., None] = getattr(self, f"h_{route.handler}")
                if route.operation is None:
                    handler(**match.groupdict())
                else:
                    with self.store.operation(route.operation, route.use_circuit):
                        handler(**match.groupdict())
            except ApiError as exc:
                self._send_error(exc)
            except BrokenPipeError:
                return
            except Exception as exc:  # noqa: BLE001
                self._send_error(
                    ApiError("INTERNAL_ERROR", repr(exc), details={"path": parsed.path})
                )
            return
        self._send_error(ApiError("NOT_FOUND", f"No route for {method} {parsed.path}"))

    # ------------------------------------------------------------ responses

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        if self.store.fault["mode"] == "invalid_json":
            self._send(status, b'{"broken": ', "application/json; charset=utf-8")
            return
        self._send(status, dumps(payload), "application/json; charset=utf-8")

    def _send_error(self, error: ApiError) -> None:
        self._send(
            error.http_status,
            dumps(error.to_payload()),
            "application/json; charset=utf-8",
        )

    def _send_html(self, html: str, status: int = 200) -> None:
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        raw = getattr(self, "raw_body", b"")
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("INVALID_REQUEST", "Body is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ApiError("INVALID_REQUEST", "Body must be a JSON object.")
        return payload

    def _query_one(self, name: str, required: bool = True) -> str | None:
        values = self.query.get(name)
        if not values:
            if required:
                raise ApiError(
                    "INVALID_REQUEST",
                    f"Query parameter {name} is required.",
                    details={"field": name},
                )
            return None
        return values[0]

    def _require_test_env(self) -> None:
        if self.app_env != "test":
            raise ApiError("TEST_ENDPOINT_DISABLED", details={"app_env": self.app_env})

    def _origin(self) -> str:
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_address[1]}"
        return f"http://{host}"

    # ------------------------------------------------------------- handlers

    def h_health(self) -> None:
        self._send_json(
            {
                "status": "ok",
                "app_env": self.app_env,
                "circuit_state": self.store.circuit_state(),
            }
        )

    def h_circuit(self) -> None:
        self._send_json(self.store.circuit_payload())

    def h_runner_start(self) -> None:
        self._require_test_env()
        body = self._body()
        seed_file = body.get("seed_file")
        if not isinstance(seed_file, str) or not seed_file:
            raise ApiError(
                "INVALID_REQUEST",
                "seed_file is required.",
                details={"field": "seed_file"},
            )
        headed = body.get("headed", True)
        if not isinstance(headed, bool):
            raise ApiError(
                "INVALID_REQUEST",
                "headed must be a boolean.",
                details={"field": "headed"},
            )
        self._send_json(self.runner_manager.start(self._origin(), seed_file, headed))

    def h_runner_status(self) -> None:
        self._require_test_env()
        run_id = self._query_one("run_id")
        self._send_json(self.runner_manager.status(run_id))

    def h_runner_logs(self) -> None:
        self._require_test_env()
        run_id = self._query_one("run_id")
        self._send_json(self.runner_manager.logs(run_id))

    def h_reset(self) -> None:
        self._require_test_env()
        self.store.reset()
        self._send_json({"status": "reset"})

    def h_set_fault(self, mode: str) -> None:
        self._require_test_env()
        params = self._body()
        self._send_json(self.store.set_fault(mode, params))

    def h_create_session(self) -> None:
        body = self._body()
        seed_file = body.get("seed_file")
        if not isinstance(seed_file, str):
            raise ApiError(
                "INVALID_REQUEST",
                "seed_file is required.",
                details={"field": "seed_file"},
            )
        self._send_json(self._session_payload(self.store.create_session(seed_file)))

    def h_next_job(self) -> None:
        session_id = self._query_one("session_id")
        job = self.store.reserve_next_job(session_id, self._origin())
        if job is None:
            self._send_json({"job": None})
            return
        payload = self._job_payload(job)
        payload["url"] = job["url"]
        self._send_json({"job": payload})

    def h_get_job(self, job_id: str) -> None:
        self._send_json(self._job_payload(self.store.get_job(job_id)))

    def h_mark_opened(self, job_id: str) -> None:
        job = self.store.mark_opened(job_id)
        self._send_json(
            {
                "job_id": job["id"],
                "state": job["state"],
                "opened_at": job["opened_at"],
                "claim_eligible_at": self.store.claim_eligible_at(job),
            }
        )

    def h_mark_open_failed(self, job_id: str) -> None:
        body = self._body()
        reason = body.get("reason", "UNKNOWN")
        job = self.store.mark_open_failed(job_id, reason, body.get("details"))
        self._send_json({"job_id": job["id"], "state": job["state"], "reason": reason})

    def h_follow(self) -> None:
        body = self._body()
        target_id = body.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ApiError(
                "INVALID_REQUEST",
                "target_id is required.",
                details={"field": "target_id"},
            )
        self._send_json(self.store.set_follow(target_id))

    def h_follow_status(self) -> None:
        self._send_json(self.store.get_follow(self._query_one("target_id")))

    def h_verify_action(self, job_id: str) -> None:
        body = self._body()
        target_id = body.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ApiError(
                "INVALID_REQUEST",
                "target_id is required.",
                details={"field": "target_id"},
            )
        job = self.store.verify_action(
            job_id, target_id, body.get("verification_source", "mock_status_api")
        )
        self._send_json(
            {
                "job_id": job["id"],
                "state": job["state"],
                "action_verified_at": job["action_verified_at"],
                "verification_receipt_id": job["verification_receipt_id"],
                # §9.5: receipt tự phát hành, không phải trusted evidence.
                "verification_receipt_trust": "SELF_ISSUED_MOCK",
                "claim_eligible_at": self.store.claim_eligible_at(job),
            }
        )

    def h_claim(self, job_id: str) -> None:
        self._send_json(self.store.claim(job_id))

    def h_settle(self) -> None:
        body = self._body()
        session_id = body.get("session_id")
        if not isinstance(session_id, str):
            raise ApiError(
                "INVALID_REQUEST",
                "session_id is required.",
                details={"field": "session_id"},
            )
        self._send_json(self.store.settle(session_id))

    def h_pause_for_safety(self, session_id: str) -> None:
        body = self._body()
        session = self.store.pause_for_safety(
            session_id,
            body.get("reason", "RATE_LIMITED"),
            body.get("retry_after_seconds"),
            body.get("operation"),
        )
        self._send_json(self._session_payload(session))

    def h_resume(self, session_id: str) -> None:
        self._send_json(self._session_payload(self.store.resume(session_id)))

    def h_stop(self, session_id: str) -> None:
        body = self._body()
        session = self.store.stop(
            session_id,
            body.get("reason", "USER_REQUESTED"),
            body.get("warning_type"),
            body.get("note"),
        )
        self._send_json(self._session_payload(session))

    def h_summary(self, session_id: str) -> None:
        self._send_json(self._session_payload(self.store.summary(session_id)))

    # ------------------------------------------------------------ HTML mock

    def h_profile_page(self, target_id: str) -> None:
        scenario = (self._query_one("scenario", required=False) or "success").strip()
        if scenario not in SCENARIOS:
            self._send_html(self._error_page("INVALID_SCENARIO", scenario), status=400)
            return

        delay_raw = self._query_one("delay_ms", required=False)
        delay_ms = 0
        if scenario == "slow_render":
            if delay_raw is None:
                self._send_html(
                    self._error_page("INVALID_SCENARIO", "slow_render requires delay_ms"),
                    status=400,
                )
                return
            try:
                delay_ms = int(delay_raw)
            except ValueError:
                self._send_html(
                    self._error_page("INVALID_SCENARIO", f"delay_ms={delay_raw!r}"),
                    status=400,
                )
                return
            if not 0 <= delay_ms <= MAX_DELAY_MS:
                self._send_html(
                    self._error_page("INVALID_SCENARIO", f"delay_ms={delay_ms}"),
                    status=400,
                )
                return

        already = self.store.get_follow(target_id)["following"]
        config = {
            "targetId": target_id,
            "scenario": scenario,
            "delayMs": delay_ms,
            "following": bool(already) or scenario == "already_following",
        }
        template = (WEB_DIR / "profile.html").read_text(encoding="utf-8")
        html = template.replace(
            "/*__MOCK_CONFIG__*/null",
            json.dumps(config, ensure_ascii=False),
        )
        self._send_html(html)

    @staticmethod
    def _error_page(code: str, detail: str) -> str:
        detail = escape(detail)
        return (
            '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
            "<title>Mock error</title></head><body>"
            f'<section data-testid="error-panel" data-error-code="{code}">'
            f"<h1>{code}</h1><p>{detail}</p></section>"
            "</body></html>"
        )

    def h_static_file(self, name: str) -> None:
        path = WEB_DIR / name
        if not path.is_file():
            raise ApiError("NOT_FOUND", f"No static file {name}")
        content_type = {
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), content_type)

    # ----------------------------------------------------------- serializers

    def _job_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job["id"],
            "session_id": job["session_id"],
            "external_id": job["external_id"],
            "target_id": job["target_id"],
            "action": job["action"],
            "state": job["state"],
            "points": job["points"],
            "minimum_claim_wait_seconds": job["minimum_claim_wait_seconds"],
            "opened_at": job["opened_at"],
            "claim_eligible_at": self.store.claim_eligible_at(job),
            "action_verified_at": job["action_verified_at"],
            "verification_receipt_id": job["verification_receipt_id"],
            "claim_started_at": job["claim_started_at"],
            "claimed_at": job["claimed_at"],
            "settled": job["settled"],
            "last_error_code": job["last_error_code"],
        }

    @staticmethod
    def _session_payload(session: dict[str, Any]) -> dict[str, Any]:
        payload = dict(session)
        payload.pop("job_ids", None)
        payload.pop("created_at", None)
        return payload


class MockHTTPServer(ThreadingHTTPServer):
    """Nuốt lỗi socket do client đóng keep-alive.

    Chrome và requests thường reset connection khi kết thúc; traceback mặc định
    của socketserver sẽ làm nhiễu output pytest mà không mang thông tin gì.
    """

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def build_server(
    host: str = "127.0.0.1",
    port: int = 0,
    app_env: str = "test",
    data_dir: Path | str = DATA_DIR,
    env_minimum_claim_wait_seconds: int | None = None,
    env_settlement_wait_seconds: int | None = None,
) -> ThreadingHTTPServer:
    """§4.3: app_env là tham số, không đọc os.environ lúc runtime."""
    httpd = MockHTTPServer((host, port), MockHandler)
    httpd.daemon_threads = True
    httpd.app_env = app_env  # type: ignore[attr-defined]
    httpd.runner_manager = RunnerManager()  # type: ignore[attr-defined]
    httpd.store = Store(  # type: ignore[attr-defined]
        data_dir,
        app_env=app_env,
        env_minimum_claim_wait_seconds=env_minimum_claim_wait_seconds,
        env_settlement_wait_seconds=env_settlement_wait_seconds,
    )
    return httpd


def _int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock lab HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--app-env", default=os.environ.get("APP_ENV", "test"))
    args = parser.parse_args(argv)

    httpd = build_server(
        args.host,
        args.port,
        app_env=args.app_env,
        env_minimum_claim_wait_seconds=_int_env("MINIMUM_CLAIM_WAIT_SECONDS"),
        env_settlement_wait_seconds=_int_env("SETTLEMENT_WAIT_SECONDS"),
    )
    host, port = httpd.server_address[:2]
    print(f"mock-lab listening on http://{host}:{port} (app_env={args.app_env})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
