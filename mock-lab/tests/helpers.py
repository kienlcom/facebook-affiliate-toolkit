"""Helper dùng chung cho E2E test."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_TIMEOUT = 30.0
POLL_INTERVAL = 0.05


def wait_for(
    predicate: Callable[[], Any],
    timeout: float = DEFAULT_TIMEOUT,
    message: str = "điều kiện không xảy ra",
) -> Any:
    """Poll thay vì sleep cố định — sleep cố định là nguồn gốc của flaky test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(POLL_INTERVAL)
    raise AssertionError(f"{message} (timeout {timeout}s)")


def job_in_state(store: Any, state: str) -> Callable[[], dict[str, Any] | None]:
    def _check() -> dict[str, Any] | None:
        with store.lock:
            for job in store.jobs.values():
                if job["state"] == state:
                    return dict(job)
        return None

    return _check


class RunnerThread:
    """Chạy runner nền để test can thiệp giữa chừng (fault, browser crash)."""

    def __init__(self, target: Callable[[], Any]) -> None:
        self._target = target
        self.result: Any = None
        self.exception: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name="runner", daemon=True)

    def _run(self) -> None:
        try:
            self.result = self._target()
        except BaseException as exc:  # noqa: BLE001
            self.exception = exc

    def __enter__(self) -> RunnerThread:
        self.thread.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.thread.join(timeout=90)

    def join(self, timeout: float = 90) -> Any:
        self.thread.join(timeout=timeout)
        assert not self.thread.is_alive(), "runner thread bị treo"
        if self.exception is not None:
            raise self.exception
        return self.result


class DriverHolder:
    """Factory ghi lại driver instance để test mô phỏng browser crash (§11.4)."""

    def __init__(self, factory: Callable[[bool], Any]) -> None:
        self._factory = factory
        self.driver: Any = None
        self._ready = threading.Event()

    def __call__(self, headed: bool) -> Any:
        self.driver = self._factory(headed)
        self._ready.set()
        return self.driver

    def wait_ready(self, timeout: float = 60) -> Any:
        assert self._ready.wait(timeout), "driver chưa được tạo"
        return self.driver


def read_events(log_path: str | Path) -> list[dict[str, Any]]:
    path = Path(log_path)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def event_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["event"] for event in events]
