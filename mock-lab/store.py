"""In-memory store cho mock lab.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §5.2, §5.3, §6, §7.

Bất biến:
  - Mọi timestamp trong store là ``datetime`` timezone-aware UTC (§5.2).
    Serialize chỉ diễn ra ở HTTP/log boundary.
  - Mọi mutate đi qua ``self.lock``.
  - Chỉ ``settle()`` được tăng ``points_earned`` (§6.7).
"""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import state_machine as sm
from errors import ApiError

DEFAULT_MINIMUM_CLAIM_WAIT_SECONDS = 3
DEFAULT_SETTLEMENT_WAIT_SECONDS = 3
DEFAULT_SETTLEMENT_THRESHOLD = 1

SCENARIOS = frozenset(
    {
        "success",
        "already_following",
        "captcha",
        "checkpoint",
        "no_button",
        "slow_render",
    }
)

FAULT_MODES = frozenset(
    {
        "none",
        "api_offline",
        "rate_limit_fetch",
        "rate_limit_claim",
        "rate_limit_settle",
        "invalid_json",
        "claim_delay",
    }
)

CIRCUIT_OPERATIONS = frozenset({"fetch", "claim", "settle"})

RATE_LIMIT_RETRY_AFTER_SECONDS = 30


def utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class Store:
    """Toàn bộ domain logic. Không import gì từ ``http.server``."""

    def __init__(
        self,
        data_dir: Path | str,
        app_env: str = "test",
        env_minimum_claim_wait_seconds: int | None = None,
        env_settlement_wait_seconds: int | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.data_dir = Path(data_dir)
        self.app_env = app_env
        self.env_minimum_claim_wait_seconds = env_minimum_claim_wait_seconds
        self.env_settlement_wait_seconds = env_settlement_wait_seconds
        self.sessions: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.follow_state: dict[str, bool] = {}
        self.circuit: dict[str, Any] = {}
        self.fault: dict[str, Any] = {}
        self.reset()

    # ------------------------------------------------------------------ reset

    def reset(self) -> None:
        with self.lock:
            self.sessions.clear()
            self.jobs.clear()
            self.follow_state.clear()
            self.circuit = {
                "state": "CLOSED",
                "opened_at": None,
                "retry_after_seconds": 0,
                "blocked_operation": None,
                "probe_in_flight": False,
            }
            self.fault = {"mode": "none", "claim_delay_ms": 0}

    # ------------------------------------------------------------- seed load

    def load_seed(self, seed_file: str) -> dict[str, Any]:
        if not seed_file or "/" in seed_file or "\\" in seed_file or ".." in seed_file:
            raise ApiError(
                "INVALID_REQUEST",
                "seed_file must be a bare file name inside data/.",
                details={"field": "seed_file", "value": seed_file},
            )
        path = self.data_dir / seed_file
        if not path.is_file():
            raise ApiError(
                "INVALID_REQUEST",
                f"Seed file {seed_file} does not exist.",
                details={"field": "seed_file", "value": seed_file},
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(
                "INVALID_REQUEST",
                f"Seed file {seed_file} is not valid JSON.",
                details={"field": "seed_file", "error": str(exc)},
            ) from exc
        return self._validate_seed(raw)

    def _validate_seed(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ApiError(
                "INVALID_REQUEST", "Seed root must be an object.", details={"field": "<root>"}
            )
        jobs = raw.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            raise ApiError(
                "INVALID_REQUEST",
                "Seed must contain a non-empty jobs array.",
                details={"field": "jobs"},
            )

        threshold = self._require_int(
            raw, "settlement_threshold", DEFAULT_SETTLEMENT_THRESHOLD, minimum=1
        )
        settlement_wait = raw.get("settlement_wait_seconds")
        if settlement_wait is None:
            settlement_wait = (
                self.env_settlement_wait_seconds
                if self.env_settlement_wait_seconds is not None
                else DEFAULT_SETTLEMENT_WAIT_SECONDS
            )
        elif not isinstance(settlement_wait, int) or settlement_wait < 0:
            raise ApiError(
                "INVALID_REQUEST",
                "settlement_wait_seconds must be a non-negative integer.",
                details={"field": "settlement_wait_seconds"},
            )

        seen_external_ids: set[str] = set()
        validated_jobs: list[dict[str, Any]] = []
        for index, job in enumerate(jobs):
            validated_jobs.append(
                self._validate_seed_job(job, index, seen_external_ids)
            )

        return {
            "settlement_threshold": threshold,
            "settlement_wait_seconds": settlement_wait,
            "jobs": validated_jobs,
        }

    def _validate_seed_job(
        self, job: Any, index: int, seen_external_ids: set[str]
    ) -> dict[str, Any]:
        if not isinstance(job, dict):
            raise ApiError(
                "INVALID_REQUEST",
                "Each job must be an object.",
                details={"field": f"jobs[{index}]"},
            )
        for field in ("external_id", "target_id", "path"):
            value = job.get(field)
            if not isinstance(value, str) or not value:
                raise ApiError(
                    "INVALID_REQUEST",
                    f"jobs[{index}].{field} is required and must be a non-empty string.",
                    details={"field": f"jobs[{index}].{field}"},
                )

        external_id = job["external_id"]
        if external_id in seen_external_ids:
            raise ApiError(
                "INVALID_REQUEST",
                f"Duplicate external_id {external_id}.",
                details={"field": f"jobs[{index}].external_id"},
            )
        seen_external_ids.add(external_id)

        path = self._validate_path(job["path"], index)

        state = job.get("state", sm.FETCHED)
        if state != sm.FETCHED:
            raise ApiError(
                "INVALID_REQUEST",
                "Seed jobs must start in FETCHED.",
                details={"field": f"jobs[{index}].state", "value": state},
            )

        points = job.get("points", 0)
        if not isinstance(points, int) or points < 0:
            raise ApiError(
                "INVALID_REQUEST",
                "points must be a non-negative integer.",
                details={"field": f"jobs[{index}].points"},
            )

        minimum_wait = job.get("minimum_claim_wait_seconds")
        if minimum_wait is None:
            minimum_wait = (
                self.env_minimum_claim_wait_seconds
                if self.env_minimum_claim_wait_seconds is not None
                else DEFAULT_MINIMUM_CLAIM_WAIT_SECONDS
            )
        elif not isinstance(minimum_wait, int) or minimum_wait < 0:
            # 0 là giá trị hợp lệ (§6.5) — claim_eligible_at == opened_at.
            raise ApiError(
                "INVALID_REQUEST",
                "minimum_claim_wait_seconds must be a non-negative integer.",
                details={"field": f"jobs[{index}].minimum_claim_wait_seconds"},
            )

        return {
            "external_id": external_id,
            "target_id": job["target_id"],
            "action": job.get("action", "FOLLOW"),
            "path": path,
            "points": points,
            "minimum_claim_wait_seconds": minimum_wait,
        }

    @staticmethod
    def _validate_path(path: str, index: int) -> str:
        """§6.4: path tương đối, bắt đầu /profiles/, không scheme/host, không '..'."""
        field = f"jobs[{index}].path"
        if "://" in path or path.startswith("//"):
            raise ApiError(
                "INVALID_REQUEST",
                "path must not contain a scheme or host.",
                details={"field": field, "value": path},
            )
        if ".." in path:
            raise ApiError(
                "INVALID_REQUEST",
                "path must not contain '..'.",
                details={"field": field, "value": path},
            )
        if not path.startswith("/profiles/"):
            raise ApiError(
                "INVALID_REQUEST",
                "path must start with /profiles/.",
                details={"field": field, "value": path},
            )
        parsed = urlsplit(path)
        scenario = parse_qs(parsed.query).get("scenario", ["success"])[0]
        if scenario not in SCENARIOS:
            raise ApiError(
                "INVALID_REQUEST",
                f"Unknown scenario {scenario}.",
                details={"field": field, "scenario": scenario},
            )
        if scenario == "slow_render":
            delay = parse_qs(parsed.query).get("delay_ms")
            if not delay:
                raise ApiError(
                    "INVALID_REQUEST",
                    "scenario=slow_render requires delay_ms.",
                    details={"field": field},
                )
        return path

    @staticmethod
    def _require_int(
        raw: dict[str, Any], field: str, default: int, minimum: int = 0
    ) -> int:
        value = raw.get(field, default)
        if not isinstance(value, int) or value < minimum:
            raise ApiError(
                "INVALID_REQUEST",
                f"{field} must be an integer >= {minimum}.",
                details={"field": field, "value": value},
            )
        return value

    # -------------------------------------------------------------- sessions

    def create_session(self, seed_file: str) -> dict[str, Any]:
        seed = self.load_seed(seed_file)
        now = utc_now()
        with self.lock:
            session_id = _new_id()
            session = {
                "id": session_id,
                "status": sm.RUNNING,
                "stop_reason": None,
                "pause_reason": None,
                "seed_file": seed_file,
                "created_at": now,
                "jobs_fetched": 0,
                "jobs_opened": 0,
                "jobs_clicked": 0,
                "jobs_action_verified": 0,
                "jobs_claimed": 0,
                "pending_points": 0,
                "points_earned": 0,
                "settlement_threshold": seed["settlement_threshold"],
                "settlement_wait_seconds": seed["settlement_wait_seconds"],
                "settlement_pending_count": 0,
                "settlement_eligible_at": None,
                "settled_at": None,
                "job_ids": [],
            }
            self.sessions[session_id] = session

            for spec in seed["jobs"]:
                job_id = _new_id()
                self.jobs[job_id] = {
                    "id": job_id,
                    "session_id": session_id,
                    "external_id": spec["external_id"],
                    "target_id": spec["target_id"],
                    "action": spec["action"],
                    "state": sm.FETCHED,
                    "path": spec["path"],
                    "points": spec["points"],
                    "minimum_claim_wait_seconds": spec["minimum_claim_wait_seconds"],
                    "opened_at": None,
                    "action_verified_at": None,
                    "verification_receipt_id": None,
                    "claim_started_at": None,
                    "claimed_at": None,
                    "settled": False,
                    "last_error_code": None,
                }
                session["job_ids"].append(job_id)

                # §6.6: scenario already_following phải có follow state sẵn,
                # nếu không verify-action sẽ trả VERIFICATION_FAILED.
                query = parse_qs(urlsplit(spec["path"]).query)
                if query.get("scenario", ["success"])[0] == "already_following":
                    self.follow_state[spec["target_id"]] = True

            return dict(session)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise ApiError("SESSION_NOT_FOUND")
            return session

    def _require_running(self, session: dict[str, Any]) -> None:
        if session["status"] == sm.PAUSED_SAFETY:
            raise ApiError(
                "SESSION_PAUSED",
                details={"pause_reason": session["pause_reason"]},
            )
        if session["status"] != sm.RUNNING:
            raise ApiError(
                "SESSION_NOT_RUNNING",
                details={"status": session["status"]},
            )

    # ------------------------------------------------------------------ jobs

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ApiError("JOB_NOT_FOUND")
            return job

    def claim_eligible_at(self, job: dict[str, Any]) -> datetime | None:
        if job["opened_at"] is None:
            return None
        return job["opened_at"] + timedelta(seconds=job["minimum_claim_wait_seconds"])

    def reserve_next_job(self, session_id: str, origin: str) -> dict[str, Any] | None:
        """FETCHED → VALIDATED → OPENING. Trả None khi hết queue."""
        with self.lock:
            session = self.get_session(session_id)
            self._require_running(session)
            for job_id in session["job_ids"]:
                job = self.jobs[job_id]
                if job["state"] != sm.FETCHED:
                    continue
                sm.transition(job, sm.VALIDATED)
                sm.transition(job, sm.OPENING)
                session["jobs_fetched"] += 1
                result = dict(job)
                result["url"] = origin.rstrip("/") + job["path"]
                return result
            return None

    def mark_opened(self, job_id: str) -> dict[str, Any]:
        """§7.5. Idempotent: state đã là WAITING_ACTION thì KHÔNG gọi transition()."""
        now = utc_now()
        with self.lock:
            job = self.get_job(job_id)
            session = self.get_session(job["session_id"])

            if job["state"] == sm.WAITING_ACTION:
                return dict(job)

            if job["state"] not in (sm.OPENING, sm.OPENED):
                raise ApiError(
                    "JOB_INVALID_STATE",
                    "Job must be OPENING, OPENED or WAITING_ACTION to be marked opened.",
                    details={"state": job["state"]},
                )

            if job["state"] == sm.OPENING:
                sm.transition(job, sm.OPENED)
            sm.transition(job, sm.WAITING_ACTION)

            if job["opened_at"] is None:
                job["opened_at"] = now
                session["jobs_opened"] += 1
            return dict(job)

    def mark_open_failed(
        self, job_id: str, reason: str, details: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self.lock:
            job = self.get_job(job_id)
            if job["state"] not in (sm.OPENING, sm.OPENED, sm.WAITING_ACTION):
                raise ApiError(
                    "JOB_INVALID_STATE",
                    details={"state": job["state"]},
                )
            sm.transition(job, sm.OPEN_FAILED)
            job["last_error_code"] = reason
            job["last_error_details"] = details or {}
            return dict(job)

    # ---------------------------------------------------------- follow state

    def set_follow(self, target_id: str) -> dict[str, Any]:
        """§6.7: đây là nơi duy nhất tăng ``jobs_clicked``."""
        with self.lock:
            self.follow_state[target_id] = True
            job = self._find_active_job_by_target(target_id)
            if job is not None:
                self.sessions[job["session_id"]]["jobs_clicked"] += 1
            return {"target_id": target_id, "following": True}

    def _find_active_job_by_target(self, target_id: str) -> dict[str, Any] | None:
        candidates = [
            job
            for job in self.jobs.values()
            if job["target_id"] == target_id
            and job["state"] in (sm.OPENING, sm.OPENED, sm.WAITING_ACTION)
        ]
        return candidates[-1] if candidates else None

    def get_follow(self, target_id: str) -> dict[str, Any]:
        with self.lock:
            return {
                "target_id": target_id,
                "following": bool(self.follow_state.get(target_id, False)),
                "source": "mock-server",
            }

    # ------------------------------------------------------- verify + claim

    def verify_action(
        self, job_id: str, target_id: str, verification_source: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self.lock:
            job = self.get_job(job_id)
            session = self.get_session(job["session_id"])
            self._require_running(session)

            if job["target_id"] != target_id:
                raise ApiError(
                    "INVALID_REQUEST",
                    "target_id does not match the job.",
                    details={"field": "target_id", "expected": job["target_id"]},
                )
            if job["state"] != sm.WAITING_ACTION:
                raise ApiError(
                    "JOB_INVALID_STATE",
                    "Job must be WAITING_ACTION to verify.",
                    details={"state": job["state"]},
                )
            if not self.follow_state.get(target_id, False):
                raise ApiError(
                    "VERIFICATION_FAILED",
                    "Mock status API does not report the target as followed.",
                    details={"target_id": target_id, "following": False},
                )

            sm.transition(job, sm.ACTION_VERIFIED)
            job["action_verified_at"] = now
            # §9.5: receipt do chính mock server phát hành — SELF_ISSUED_MOCK.
            job["verification_receipt_id"] = _new_id()
            job["verification_source"] = verification_source
            session["jobs_action_verified"] += 1
            return dict(job)

    def reserve_claim_atomic(self, job_id: str, now: datetime | None = None) -> dict[str, Any]:
        """§5.3. Thứ tự check là bắt buộc: CLAIMED → CLAIMING → ACTION_VERIFIED."""
        now = now or utc_now()
        with self.lock:
            job = self.get_job(job_id)
            session = self.get_session(job["session_id"])
            self._require_running(session)

            if job["state"] == sm.CLAIMED:
                raise ApiError("ALREADY_CLAIMED")

            if job["state"] == sm.CLAIMING or job["state"] == sm.CLAIM_PENDING:
                raise ApiError("JOB_ALREADY_CLAIMING")

            if job["state"] != sm.ACTION_VERIFIED:
                raise ApiError(
                    "ACTION_NOT_VERIFIED",
                    details={"state": job["state"]},
                )

            eligible_at = self.claim_eligible_at(job)
            if eligible_at is not None and now < eligible_at:
                raise ApiError(
                    "CLAIM_TOO_EARLY",
                    details={
                        "eligible_at": eligible_at.isoformat(),
                        "retry_after_seconds": max(
                            1, math.ceil((eligible_at - now).total_seconds())
                        ),
                    },
                )

            sm.transition(job, sm.CLAIM_PENDING)
            sm.transition(job, sm.CLAIMING)
            job["claim_started_at"] = now
            return dict(job)

    def finalize_claim_atomic(
        self, job_id: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """§5.3. Không cộng ``points_earned`` — chỉ settle() làm việc đó."""
        now = now or utc_now()
        with self.lock:
            job = self.get_job(job_id)
            session = self.get_session(job["session_id"])

            if job["state"] == sm.CLAIMED:
                raise ApiError("ALREADY_CLAIMED")
            if job["state"] != sm.CLAIMING:
                raise ApiError("JOB_INVALID_STATE", details={"state": job["state"]})

            sm.transition(job, sm.CLAIMED)
            job["claimed_at"] = now

            session["jobs_claimed"] += 1
            session["settlement_pending_count"] += 1
            session["pending_points"] += job["points"]

            if (
                session["settlement_pending_count"] >= session["settlement_threshold"]
                and session["settlement_eligible_at"] is None
            ):
                session["settlement_eligible_at"] = now + timedelta(
                    seconds=session["settlement_wait_seconds"]
                )

            return dict(job)

    def claim(self, job_id: str) -> dict[str, Any]:
        """Reserve → (xử lý ngoài lock) → finalize.

        §5.3.1: trong mock, đoạn giữa không có I/O và không thể ném exception,
        nên job không thể kẹt ở CLAIMING và không cần lease timeout.
        Fault ``claim_delay`` (§5.4.1) cố tình mở rộng cửa sổ này để test
        cover được nhánh JOB_ALREADY_CLAIMING.
        """
        self.reserve_claim_atomic(job_id)

        delay_ms = self.fault.get("claim_delay_ms", 0) if self.fault["mode"] == "claim_delay" else 0
        if delay_ms:
            time.sleep(delay_ms / 1000.0)

        job = self.finalize_claim_atomic(job_id)
        with self.lock:
            session = self.get_session(job["session_id"])
            threshold_reached = (
                session["settlement_pending_count"] >= session["settlement_threshold"]
            )
            return {
                "job_id": job["id"],
                "state": job["state"],
                "points_pending": job["points"],
                "points_added": 0,
                "settlement_pending_count": session["settlement_pending_count"],
                "settlement_required": threshold_reached,
                "settlement_eligible_at": session["settlement_eligible_at"],
            }

    # ------------------------------------------------------------ settlement

    def settle(self, session_id: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or utc_now()
        with self.lock:
            session = self.get_session(session_id)
            self._require_running(session)

            if session["settlement_pending_count"] < session["settlement_threshold"]:
                raise ApiError(
                    "SETTLEMENT_NOT_READY",
                    details={
                        "settlement_pending_count": session["settlement_pending_count"],
                        "settlement_threshold": session["settlement_threshold"],
                    },
                )

            eligible_at = session["settlement_eligible_at"]
            if eligible_at is not None and now < eligible_at:
                raise ApiError(
                    "SETTLEMENT_TOO_EARLY",
                    details={
                        "eligible_at": eligible_at.isoformat(),
                        "retry_after_seconds": max(
                            1, math.ceil((eligible_at - now).total_seconds())
                        ),
                    },
                )

            if self.circuit_state(now) != "CLOSED":
                raise ApiError(
                    "RATE_LIMITED",
                    "Settlement requires a closed circuit.",
                    details={
                        "retry_after_seconds": self.circuit["retry_after_seconds"],
                        "operation": "settle",
                    },
                )

            pending_jobs = [
                self.jobs[job_id]
                for job_id in session["job_ids"]
                if self.jobs[job_id]["state"] == sm.CLAIMED and not self.jobs[job_id]["settled"]
            ]
            points_settled = sum(job["points"] for job in pending_jobs)
            for job in pending_jobs:
                job["settled"] = True

            # §7.11: năm thay đổi bắt buộc. Thiếu settlement_eligible_at = None
            # sẽ khiến batch sau bỏ qua settlement wait.
            session["points_earned"] += points_settled
            session["pending_points"] = 0
            session["settlement_pending_count"] = 0
            session["settlement_eligible_at"] = None
            session["settled_at"] = now

            return {
                "session_id": session_id,
                "settled_count": len(pending_jobs),
                "points_settled": points_settled,
                "pending_points": session["pending_points"],
                "points_earned": session["points_earned"],
                "settlement_pending_count": session["settlement_pending_count"],
                "settled_at": now,
            }

    # ------------------------------------------------------- pause/stop/resume

    def pause_for_safety(
        self,
        session_id: str,
        reason: str,
        retry_after_seconds: int | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            session = self.get_session(session_id)
            if session["status"] == sm.PAUSED_SAFETY:
                return dict(session)
            sm.transition_session(session, sm.PAUSED_SAFETY)
            session["pause_reason"] = reason
            session["pause_retry_after_seconds"] = retry_after_seconds
            session["pause_operation"] = operation
            return dict(session)

    def resume(self, session_id: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or utc_now()
        with self.lock:
            session = self.get_session(session_id)
            if session["status"] != sm.PAUSED_SAFETY:
                raise ApiError(
                    "SESSION_NOT_RUNNING",
                    "Session is not paused.",
                    details={"status": session["status"]},
                )
            state = self.circuit_state(now)
            if state == "OPEN":
                raise ApiError(
                    "RATE_LIMITED",
                    "Circuit is still open; retry-after has not elapsed.",
                    details={
                        "retry_after_seconds": self._remaining_retry_after(now),
                        "operation": self.circuit["blocked_operation"],
                    },
                )
            sm.transition_session(session, sm.RUNNING)
            session["pause_reason"] = None
            return dict(session)

    def stop(
        self,
        session_id: str,
        reason: str,
        warning_type: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            session = self.get_session(session_id)
            if session["status"] == sm.STOPPED:
                return dict(session)
            sm.transition_session(session, sm.STOPPED)
            session["stop_reason"] = reason
            session["warning_type"] = warning_type
            session["note"] = note

            # §9.2: cascade job states khi session dừng.
            target = (
                sm.ACCOUNT_PROTECTION_STOP
                if reason == "ACCOUNT_PROTECTION_STOP"
                else sm.CANCELLED
            )
            for job_id in session["job_ids"]:
                job = self.jobs[job_id]
                if job["state"] in sm.TERMINAL_STATES:
                    continue
                if sm.can_transition(job["state"], target):
                    sm.transition(job, target)
                else:
                    sm.transition(job, sm.CANCELLED)
            return dict(session)

    # ---------------------------------------------------------------- summary

    def summary(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            session = self.get_session(session_id)
            payload = dict(session)
            payload["jobs"] = [
                {
                    "id": job_id,
                    "external_id": self.jobs[job_id]["external_id"],
                    "state": self.jobs[job_id]["state"],
                }
                for job_id in session["job_ids"]
            ]
            payload.pop("job_ids", None)
            return payload

    # ------------------------------------------------------- circuit breaker

    def circuit_state(self, now: datetime | None = None) -> str:
        """Đọc state, tự chuyển OPEN → HALF_OPEN khi hết retry-after (§7.15)."""
        now = now or utc_now()
        with self.lock:
            if self.circuit["state"] == "OPEN":
                opened_at = self.circuit["opened_at"]
                retry_after = self.circuit["retry_after_seconds"]
                if opened_at is not None and now >= opened_at + timedelta(seconds=retry_after):
                    self.circuit["state"] = "HALF_OPEN"
            return self.circuit["state"]

    def _remaining_retry_after(self, now: datetime) -> int:
        opened_at = self.circuit["opened_at"]
        retry_after = self.circuit["retry_after_seconds"]
        if opened_at is None:
            return retry_after
        remaining = (opened_at + timedelta(seconds=retry_after) - now).total_seconds()
        return max(0, math.ceil(remaining))

    def open_circuit(
        self, operation: str, retry_after_seconds: int, now: datetime | None = None
    ) -> None:
        now = now or utc_now()
        with self.lock:
            self.circuit["state"] = "OPEN"
            self.circuit["opened_at"] = now
            self.circuit["retry_after_seconds"] = retry_after_seconds
            self.circuit["blocked_operation"] = operation
            self.circuit["probe_in_flight"] = False

    def circuit_payload(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or utc_now()
        state = self.circuit_state(now)
        with self.lock:
            return {
                "state": state,
                "opened_at": self.circuit["opened_at"],
                "retry_after_seconds": self._remaining_retry_after(now),
                "blocked_operation": self.circuit["blocked_operation"],
                "probe_in_flight": self.circuit["probe_in_flight"],
            }

    # ------------------------------------------------------ fault + operation

    def set_fault(self, mode: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if mode not in FAULT_MODES:
            raise ApiError(
                "INVALID_REQUEST",
                f"Unknown fault mode {mode}.",
                details={"field": "mode", "allowed": sorted(FAULT_MODES)},
            )
        params = params or {}
        with self.lock:
            self.fault = {"mode": mode, "claim_delay_ms": 0}
            if mode == "claim_delay":
                ms = params.get("ms", 50)
                if not isinstance(ms, int) or ms < 0 or ms > 5000:
                    raise ApiError(
                        "INVALID_REQUEST",
                        "ms must be an integer in [0, 5000].",
                        details={"field": "ms"},
                    )
                self.fault["claim_delay_ms"] = ms
            if mode == "none":
                # Clear fault cũng reset circuit về CLOSED để probe kế tiếp đóng được.
                self.circuit["probe_in_flight"] = False
            return dict(self.fault)

    @contextmanager
    def operation(self, name: str, use_circuit: bool = False) -> Iterator[None]:
        """Guard cho business endpoint: offline fault, circuit, rate-limit fault.

        Ba mức guard (§7.15.1, §7.16):
          - Read-only/control-plane: không gọi hàm này.
          - ``use_circuit=False``: chỉ chặn bởi ``api_offline``. Dùng cho stop,
            pause, resume — cleanup phải chạy được kể cả khi circuit đang mở.
          - ``use_circuit=True``: thêm circuit breaker. Chỉ fetch/claim/settle.
        """
        now = utc_now()
        is_probe = False
        with self.lock:
            if self.fault["mode"] == "api_offline":
                raise ApiError("MOCK_API_OFFLINE", details={"operation": name})

            if use_circuit and name in CIRCUIT_OPERATIONS:
                state = self.circuit_state(now)
                if state == "OPEN":
                    raise ApiError(
                        "RATE_LIMITED",
                        details={
                            "retry_after_seconds": self._remaining_retry_after(now),
                            "operation": name,
                        },
                    )
                if state == "HALF_OPEN":
                    if self.circuit["probe_in_flight"]:
                        raise ApiError(
                            "SESSION_PAUSED",
                            "A circuit probe is already in flight.",
                            details={"operation": name},
                        )
                    self.circuit["probe_in_flight"] = True
                    is_probe = True

            if self.fault["mode"] == f"rate_limit_{name}":
                self.open_circuit(name, RATE_LIMIT_RETRY_AFTER_SECONDS, now)
                raise ApiError(
                    "RATE_LIMITED",
                    details={
                        "retry_after_seconds": RATE_LIMIT_RETRY_AFTER_SECONDS,
                        "operation": name,
                    },
                )

        try:
            yield
        except ApiError as exc:
            self._exit_circuit(is_probe, ok=exc.code != "RATE_LIMITED", operation=name)
            raise
        except Exception:
            self._exit_circuit(is_probe, ok=False, operation=name)
            raise
        else:
            self._exit_circuit(is_probe, ok=True, operation=name)

    def _exit_circuit(self, is_probe: bool, ok: bool, operation: str) -> None:
        if not is_probe:
            return
        with self.lock:
            self.circuit["probe_in_flight"] = False
            if ok:
                self.circuit["state"] = "CLOSED"
                self.circuit["opened_at"] = None
                self.circuit["retry_after_seconds"] = 0
                self.circuit["blocked_operation"] = None
            else:
                self.open_circuit(operation, RATE_LIMIT_RETRY_AFTER_SECONDS)
