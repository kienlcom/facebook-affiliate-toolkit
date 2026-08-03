"""HTTP client cho mock lab, dùng chung bởi runner và test.

Quy ước:
  - Lỗi HTTP có error envelope (§8) KHÔNG raise; trả ``ApiResult`` với ``ok=False``.
    Runner cần đọc ``error_code``/``details`` để quyết định retry, pause hay stop.
  - Lỗi network (connection refused, timeout) thì raise ``requests`` exception,
    vì đó là tình huống fatal khác hẳn về bản chất (§13.1 A13, §13.3 C07).
"""

from __future__ import annotations

from typing import Any

import requests

from errors import ApiError

DEFAULT_TIMEOUT_SECONDS = 10


class ApiResult:
    __slots__ = ("ok", "status", "payload", "error_code", "error_message", "details")

    def __init__(self, response: requests.Response) -> None:
        self.status = response.status_code
        self.ok = 200 <= response.status_code < 300
        self.error_code: str | None = None
        self.error_message: str | None = None
        self.details: dict[str, Any] = {}
        try:
            self.payload: Any = response.json()
        except ValueError:
            self.payload = None
            if not self.ok:
                self.error_code = "INVALID_RESPONSE_BODY"
            return
        if not self.ok and isinstance(self.payload, dict):
            error = self.payload.get("error") or {}
            self.error_code = error.get("code")
            self.error_message = error.get("message")
            self.details = error.get("details") or {}

    def json(self) -> Any:
        return self.payload

    def unwrap(self) -> Any:
        if not self.ok:
            raise ApiError(
                self.error_code or "INTERNAL_ERROR",
                self.error_message,
                self.details,
            )
        return self.payload

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        if self.ok:
            return f"<ApiResult {self.status} ok>"
        return f"<ApiResult {self.status} {self.error_code}>"


class ApiClient:
    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def close(self) -> None:
        self.session.close()

    # ------------------------------------------------------------- plumbing

    def _get(self, path: str, params: dict[str, Any] | None = None) -> ApiResult:
        return ApiResult(
            self.session.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout
            )
        )

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> ApiResult:
        return ApiResult(
            self.session.post(
                f"{self.base_url}{path}", json=payload or {}, timeout=self.timeout
            )
        )

    # ------------------------------------------------------------ endpoints

    def health(self) -> ApiResult:
        return self._get("/health")

    def circuit(self) -> ApiResult:
        return self._get("/api/circuit")

    def reset(self) -> ApiResult:
        return self._post("/api/reset")

    def set_fault(self, mode: str, **params: Any) -> ApiResult:
        return self._post(f"/api/_fault/{mode}", params)

    def create_session(self, seed_file: str) -> ApiResult:
        return self._post("/api/sessions", {"seed_file": seed_file})

    def next_job(self, session_id: str) -> ApiResult:
        return self._get("/api/jobs/next", {"session_id": session_id})

    def get_job(self, job_id: str) -> ApiResult:
        return self._get(f"/api/jobs/{job_id}")

    def mark_opened(self, job_id: str) -> ApiResult:
        return self._post(f"/api/jobs/{job_id}/opened")

    def open_failed(
        self, job_id: str, reason: str, details: dict[str, Any] | None = None
    ) -> ApiResult:
        return self._post(
            f"/api/jobs/{job_id}/open-failed",
            {"reason": reason, "details": details or {}},
        )

    def follow(self, target_id: str) -> ApiResult:
        return self._post("/api/mock-facebook/follow", {"target_id": target_id})

    def follow_status(self, target_id: str) -> ApiResult:
        return self._get("/api/mock-facebook/status", {"target_id": target_id})

    def verify_action(
        self, job_id: str, target_id: str, verification_source: str = "mock_status_api"
    ) -> ApiResult:
        return self._post(
            f"/api/jobs/{job_id}/verify-action",
            {"target_id": target_id, "verification_source": verification_source},
        )

    def claim(self, job_id: str) -> ApiResult:
        return self._post(f"/api/jobs/{job_id}/claim")

    def settle(self, session_id: str) -> ApiResult:
        return self._post("/api/claims/settle", {"session_id": session_id})

    def pause_for_safety(
        self,
        session_id: str,
        reason: str = "RATE_LIMITED",
        retry_after_seconds: int | None = None,
        operation: str | None = None,
    ) -> ApiResult:
        return self._post(
            f"/api/sessions/{session_id}/pause-for-safety",
            {
                "reason": reason,
                "retry_after_seconds": retry_after_seconds,
                "operation": operation,
            },
        )

    def resume(self, session_id: str) -> ApiResult:
        return self._post(f"/api/sessions/{session_id}/resume")

    def stop_session(
        self,
        session_id: str,
        reason: str,
        warning_type: str | None = None,
        note: str | None = None,
    ) -> ApiResult:
        return self._post(
            f"/api/sessions/{session_id}/stop",
            {"reason": reason, "warning_type": warning_type, "note": note},
        )

    def summary(self, session_id: str) -> ApiResult:
        return self._get(f"/api/sessions/{session_id}/summary")

    # --------------------------------------------------------- best effort

    def best_effort_stop(self, session_id: str, **kwargs: Any) -> ApiResult | None:
        """Dùng ở nhánh cleanup. Server không reachable thì trả None (§14.1)."""
        try:
            return self.stop_session(session_id, **kwargs)
        except requests.RequestException:
            return None

    def best_effort_summary(self, session_id: str) -> dict[str, Any] | None:
        try:
            result = self.summary(session_id)
        except requests.RequestException:
            return None
        return result.payload if result.ok else None
