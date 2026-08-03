from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from errors import ApiError
from logging_setup import RunLogger
from runner import run


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RunnerJob:
    def __init__(self, run_id: str, seed_file: str, base_url: str, headed: bool) -> None:
        self.run_id = run_id
        self.seed_file = seed_file
        self.base_url = base_url
        self.headed = headed
        self.status = "PENDING"
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.logger = RunLogger(run_id=run_id)
        self.thread = threading.Thread(target=self._run, name=f"runner-{run_id}", daemon=True)

    def start(self) -> None:
        self.started_at = _now()
        self.status = "RUNNING"
        self.thread.start()

    def _run(self) -> None:
        try:
            result = run(
                self.base_url,
                self.seed_file,
                headed=self.headed,
                debug=True,
                logger=self.logger,
            )
            self.result = result.to_dict()
            self.status = "COMPLETED" if result.exit_code == 0 else "STOPPED"
        except Exception as exc:  # noqa: BLE001
            self.error = repr(exc)
            self.status = "FAILED"
            self.logger.error("runner.failed", data={"error": self.error})
        finally:
            self.ended_at = _now()

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "seed_file": self.seed_file,
            "base_url": self.base_url,
            "headed": self.headed,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "result": self.result,
            "error": self.error,
            "log_path": str(self.logger.path),
        }

    def events(self) -> list[dict[str, Any]]:
        paths = []
        bootstrap_path = getattr(self.logger, "_bootstrap_path", None)
        if isinstance(bootstrap_path, Path):
            paths.append(bootstrap_path)
        if self.logger.path not in paths:
            paths.append(self.logger.path)

        records: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    records.append(
                        {
                            "ts": _now(),
                            "level": "ERROR",
                            "event": "runner.log_parse_failed",
                            "data": {"path": str(path)},
                        }
                    )
        return records


class RunnerManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, RunnerJob] = {}

    def start(self, base_url: str, seed_file: str, headed: bool = True) -> dict[str, Any]:
        with self._lock:
            active = [
                job
                for job in self._jobs.values()
                if job.status in {"PENDING", "RUNNING"} and job.thread.is_alive()
            ]
            if active:
                raise ApiError(
                    "RUNNER_ALREADY_RUNNING",
                    details={"run_id": active[-1].run_id},
                )
            run_id = str(uuid.uuid4())
            job = RunnerJob(run_id, seed_file, base_url, headed)
            self._jobs[run_id] = job
            job.start()
            return job.payload()

    def get(self, run_id: str) -> RunnerJob:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                raise ApiError("RUNNER_NOT_FOUND", details={"run_id": run_id})
            return job

    def status(self, run_id: str) -> dict[str, Any]:
        return self.get(run_id).payload()

    def logs(self, run_id: str) -> dict[str, Any]:
        job = self.get(run_id)
        return {**job.payload(), "events": job.events()}
