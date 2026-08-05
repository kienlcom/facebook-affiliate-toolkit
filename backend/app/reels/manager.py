"""Quản lý một lượt chạy reel runner trong thread nền.

Selenium là API đồng bộ và blocking nên không chạy được trực tiếp trong event
loop của FastAPI. Mỗi lượt chạy là một thread daemon; frontend poll
``GET /api/reels/run`` để lấy trạng thái và event.

Chỉ cho phép một lượt chạy tại một thời điểm — hai Chrome cùng lướt sẽ tranh
nhau focus và làm log vô nghĩa.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ConflictError, NotFoundError
from app.reels.browser import ReelBrowser, ReelTarget, build_driver, safe_quit

logger = logging.getLogger(__name__)

MAX_EVENTS = 500

ACTIVE_STATUSES = frozenset({"PENDING", "RUNNING"})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ReelRun:
    def __init__(
        self,
        run_id: str,
        targets: list[ReelTarget],
        *,
        dwell_seconds: float,
        selector_timeout_seconds: float,
        max_images_per_link: int,
        headed: bool,
        driver_factory: Callable[[bool], Any],
    ) -> None:
        self.run_id = run_id
        self.targets = targets
        self.dwell_seconds = dwell_seconds
        self.selector_timeout_seconds = selector_timeout_seconds
        self.max_images_per_link = max_images_per_link
        self.headed = headed
        self.status = "PENDING"
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.stop_event = threading.Event()

        self.driver_factory = driver_factory
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f"reel-run-{run_id}", daemon=True)

    # ------------------------------------------------------------------ public

    def start(self) -> None:
        self.started_at = _now()
        self.status = "RUNNING"
        self.emit(
            "INFO",
            "run.started",
            {"links": len(self.targets), "dwell_seconds": self.dwell_seconds},
        )
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.emit("INFO", "run.stop_requested", {})

    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES and self._thread.is_alive()

    def emit(self, level: str, event: str, data: dict[str, Any]) -> None:
        record = {"ts": _now(), "level": level, "event": event, "data": data}
        with self._lock:
            self._events.append(record)
            if len(self._events) > MAX_EVENTS:
                del self._events[: len(self._events) - MAX_EVENTS]

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "headed": self.headed,
            "dwell_seconds": self.dwell_seconds,
            "link_count": len(self.targets),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "result": self.result,
            "error": self.error,
        }

    # --------------------------------------------------------------- internals

    def _run(self) -> None:
        driver = None
        try:
            driver = self.driver_factory(self.headed)
            browser = ReelBrowser(
                driver,
                dwell_seconds=self.dwell_seconds,
                selector_timeout_seconds=self.selector_timeout_seconds,
                max_images_per_link=self.max_images_per_link,
                emit=self.emit,
                stop_event=self.stop_event,
            )
            result = browser.browse(self.targets)
            self.result = result.to_dict()
            self.status = "STOPPED" if result.stopped else "COMPLETED"
        except Exception as exc:  # noqa: BLE001
            self.error = repr(exc)
            self.status = "FAILED"
            logger.error(
                "reels.run_failed",
                extra={"run_id": self.run_id, "error_code": type(exc).__name__},
            )
            self.emit("ERROR", "run.failed", {"error": type(exc).__name__})
        finally:
            safe_quit(driver)
            self.ended_at = _now()


class ReelRunManager:
    def __init__(self, driver_factory: Callable[[bool], Any] = build_driver) -> None:
        self._lock = threading.Lock()
        self._current: ReelRun | None = None
        self.driver_factory = driver_factory

    def start(
        self,
        targets: list[ReelTarget],
        *,
        dwell_seconds: float,
        selector_timeout_seconds: float,
        max_images_per_link: int,
        headed: bool,
    ) -> dict[str, Any]:
        with self._lock:
            if self._current is not None and self._current.is_active():
                raise ConflictError(
                    "REEL_RUN_ALREADY_RUNNING",
                    "A reel run is already in progress",
                    details={"run_id": self._current.run_id},
                )
            run = ReelRun(
                str(uuid.uuid4()),
                targets,
                dwell_seconds=dwell_seconds,
                selector_timeout_seconds=selector_timeout_seconds,
                max_images_per_link=max_images_per_link,
                headed=headed,
                driver_factory=self.driver_factory,
            )
            self._current = run
        run.start()
        return run.payload()

    def current(self) -> ReelRun:
        with self._lock:
            run = self._current
        if run is None:
            raise NotFoundError("REEL_RUN_NOT_FOUND", "No reel run has been started yet")
        return run

    def status(self) -> dict[str, Any]:
        run = self.current()
        return {**run.payload(), "events": run.events()}

    def stop(self) -> dict[str, Any]:
        run = self.current()
        if not run.is_active():
            raise ConflictError(
                "REEL_RUN_NOT_RUNNING",
                "The reel run has already finished",
                details={"run_id": run.run_id, "status": run.status},
            )
        run.stop()
        return run.payload()

    def shutdown(self) -> None:
        with self._lock:
            run = self._current
        if run is not None and run.is_active():
            run.stop()
