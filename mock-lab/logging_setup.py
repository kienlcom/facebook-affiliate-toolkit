"""JSONL logging và screenshot cho runner.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §12.

§12.1: sau khi session được tạo, mọi event bắt buộc có ``session_id`` non-null.
Lỗi xảy ra trước đó đi vào bootstrap log riêng dùng ``run_id`` — không bịa
``session_id=null``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
RUNS_DIR = LOG_DIR / "runs"
SCREENSHOTS_DIR = LOG_DIR / "screenshots"

SCREENSHOT_REASONS = frozenset(
    {
        "captcha",
        "checkpoint",
        "invalid_scenario",
        "follow_button_timeout",
        "browser_crash",
        "unhandled_error",
    }
)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe(part: str) -> str:
    return _UNSAFE.sub("_", part or "unknown")


def _ts() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RunLogger:
    """Ghi JSONL. Trước khi có session thì ghi vào bootstrap log."""

    def __init__(self, run_id: str | None = None, log_dir: Path | None = None) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.session_id: str | None = None
        base = log_dir or RUNS_DIR
        base.mkdir(parents=True, exist_ok=True)
        self._bootstrap_path = base / f"bootstrap-{self.run_id}.jsonl"
        self._run_path: Path | None = None
        self._base = base

    def bind_session(self, session_id: str) -> None:
        self.session_id = session_id
        self._run_path = self._base / f"run-{_safe(session_id)}.jsonl"

    @property
    def path(self) -> Path:
        return self._run_path or self._bootstrap_path

    def event(
        self,
        event: str,
        level: str = "INFO",
        job: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": _ts(),
            "level": level,
            "event": event,
            "data": data or {},
        }
        if self.session_id is None:
            record["run_id"] = self.run_id
        else:
            record["session_id"] = self.session_id
        if job:
            record["job_id"] = job.get("id")
            record["external_id"] = job.get("external_id")

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def warn(self, event: str, **kwargs: Any) -> dict[str, Any]:
        return self.event(event, level="WARN", **kwargs)

    def error(self, event: str, **kwargs: Any) -> dict[str, Any]:
        return self.event(event, level="ERROR", **kwargs)


def screenshot_path(session_id: str | None, job_id: str | None, reason: str) -> Path:
    """§12.2: logs/screenshots/{session_id}/{job_id}-{reason}.png"""
    folder = SCREENSHOTS_DIR / _safe(session_id or "no-session")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_safe(job_id or 'no-job')}-{_safe(reason)}.png"


def take_screenshot(
    driver: Any,
    session_id: str | None,
    job_id: str | None,
    reason: str,
    logger: RunLogger | None = None,
) -> Path | None:
    """Best-effort: driver có thể đã chết ở nhánh browser crash."""
    path = screenshot_path(session_id, job_id, reason)
    try:
        driver.save_screenshot(str(path))
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            logger.warn(
                "diagnostic.screenshot_failed",
                data={"reason": reason, "error": repr(exc)},
            )
        return None
    if logger is not None:
        logger.event(
            "diagnostic.screenshot",
            data={"reason": reason, "path": str(path)},
        )
    return path
