"""Selenium orchestrator cho mock lab.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §5.8, §5.10, §16.

Quy tắc Selenium bắt buộc (§5.7): không giữ WebElement qua DOM mutation.
Mọi lần đọc thuộc tính sau khi DOM có thể đã đổi đều phải re-find selector.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
import urllib3
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)

# Khi driver process bị giết, Selenium không ném WebDriverException mà để lọt
# lỗi kết nối urllib3 tới chromedriver. Cả hai đều là "browser crash".
BROWSER_FAILURES = (WebDriverException, urllib3.exceptions.HTTPError)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from api_client import ApiClient
from logging_setup import RunLogger, take_screenshot

FOLLOW_SELECTOR = '[data-testid="follow-button"]'
CAPTCHA_SELECTOR = '[data-testid="captcha-panel"]'
CHECKPOINT_SELECTOR = '[data-testid="checkpoint-panel"]'
ERROR_SELECTOR = '[data-testid="error-panel"]'

SELECTOR_TIMEOUT_SECONDS = int(os.environ.get("SELECTOR_TIMEOUT_SECONDS", "5"))
SESSION_TIMEOUT_SECONDS = int(os.environ.get("SESSION_TIMEOUT_SECONDS", "120"))
API_TIMEOUT_SECONDS = int(os.environ.get("API_TIMEOUT_SECONDS", "10"))
RATE_LIMIT_BEHAVIOR = os.environ.get("RATE_LIMIT_BEHAVIOR", "pause")

MAX_CLAIM_RETRIES = 10
MAX_SETTLE_RETRIES = 10

# Exit code contract — test dùng để phân biệt nhánh kết thúc.
EXIT_OK = 0
EXIT_STOPPED = 1
EXIT_BROWSER_CRASH = 2
EXIT_UNHANDLED = 3
EXIT_PAUSED_SAFETY = 4


class RunnerStop(Exception):
    def __init__(self, code: str, note: str | None = None) -> None:
        self.code = code
        self.note = note
        super().__init__(code)


@dataclass
class RunResult:
    exit_code: int = EXIT_OK
    error_code: str | None = None
    summary: dict[str, Any] | None = None
    session_id: str | None = None
    log_path: str | None = None
    events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "error_code": self.error_code,
            "session_id": self.session_id,
            "log_path": self.log_path,
            "summary": self.summary,
        }


@dataclass
class RunnerContext:
    driver: Any
    session_id: str | None = None
    current_job: dict[str, Any] | None = None

    @property
    def current_job_id(self) -> str | None:
        return self.current_job["id"] if self.current_job else None


# --------------------------------------------------------------- driver

def build_selenium_driver(headed: bool = False) -> webdriver.Chrome:
    options = Options()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    return webdriver.Chrome(options=options)


def safe_quit(driver: Any) -> None:
    """Idempotent — gọi được kể cả khi driver đã đóng (§5.10)."""
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------- selectors

def exists(driver: Any, selector: str) -> bool:
    try:
        driver.find_element(By.CSS_SELECTOR, selector)
        return True
    except NoSuchElementException:
        return False


def find_follow(driver: Any, timeout_seconds: int):
    return WebDriverWait(driver, timeout_seconds).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, FOLLOW_SELECTOR))
    )


def wait_following(driver: Any, timeout_seconds: int) -> None:
    """Re-find selector trong mỗi lần poll — không dùng lại WebElement cũ."""
    WebDriverWait(driver, timeout_seconds).until(
        lambda d: d.find_element(By.CSS_SELECTOR, FOLLOW_SELECTOR).get_attribute(
            "data-following"
        )
        == "true"
    )


# ------------------------------------------------------------------ run

def run(
    base_url: str,
    seed_file: str,
    headed: bool = False,
    driver_factory: Callable[[bool], Any] = build_selenium_driver,
    debug: bool = False,
    logger: RunLogger | None = None,
) -> RunResult:
    log = logger or RunLogger()
    api = ApiClient(base_url, timeout=API_TIMEOUT_SECONDS)
    result = RunResult()
    driver = None
    context = RunnerContext(driver=None)
    started_at = time.monotonic()

    try:
        session = api.create_session(seed_file).unwrap()
    except Exception as exc:  # noqa: BLE001
        log.error("run.bootstrap_failed", data={"error": repr(exc)})
        api.close()
        result.exit_code = EXIT_UNHANDLED
        result.error_code = "BOOTSTRAP_FAILED"
        result.log_path = str(log.path)
        return result

    session_id = session["id"]
    log.bind_session(session_id)
    context.session_id = session_id
    result.session_id = session_id
    log.event("session.started", data={"seed_file": seed_file, "base_url": base_url})

    try:
        driver = driver_factory(headed)
        context.driver = driver

        while True:
            if time.monotonic() - started_at > SESSION_TIMEOUT_SECONDS:
                raise RunnerStop("SESSION_TIMEOUT")

            fetched = api.next_job(session_id)
            if not fetched.ok:
                _handle_api_failure(api, log, context, fetched, "fetch")

            job = fetched.unwrap()["job"]
            if job is None:
                api.stop_session(session_id, "COMPLETED_NO_MORE_JOBS")
                log.event("session.stopped", data={"reason": "COMPLETED_NO_MORE_JOBS"})
                break

            context.current_job = job
            log.event("job.opening", job=job, data={"url": job["url"]})
            driver.get(job["url"])

            opened = api.mark_opened(job["id"])
            if not opened.ok:
                _handle_api_failure(api, log, context, opened, "opened")
            log.event("job.opened", job=job, data={"opened_at": opened.unwrap()["opened_at"]})

            if exists(driver, ERROR_SELECTOR):
                take_screenshot(driver, session_id, job["id"], "invalid_scenario", log)
                api.open_failed(job["id"], "INVALID_SCENARIO")
                log.error("job.invalid_scenario", job=job)
                raise RunnerStop("UI_AUTOMATION_FAILED", "error-panel detected")

            protection = _detect_protection(driver)
            if protection is not None:
                take_screenshot(driver, session_id, job["id"], protection.lower(), log)
                api.stop_session(
                    session_id,
                    "ACCOUNT_PROTECTION_STOP",
                    warning_type=protection,
                    note=f"{protection.lower()}-panel detected",
                )
                log.error(
                    "session.stopped",
                    job=job,
                    data={"reason": "ACCOUNT_PROTECTION_STOP", "warning_type": protection},
                )
                result.exit_code = EXIT_STOPPED
                result.error_code = f"ACCOUNT_PROTECTION_STOP:{protection}"
                break

            try:
                button = find_follow(driver, SELECTOR_TIMEOUT_SECONDS)
            except TimeoutException:
                take_screenshot(driver, session_id, job["id"], "follow_button_timeout", log)
                api.open_failed(
                    job["id"],
                    "FOLLOW_BUTTON_TIMEOUT",
                    {"selector": FOLLOW_SELECTOR, "timeout_seconds": SELECTOR_TIMEOUT_SECONDS},
                )
                log.error("job.follow_button_timeout", job=job)
                raise RunnerStop("UI_AUTOMATION_FAILED", "follow button not found") from None

            if button.get_attribute("data-following") != "true":
                # Re-find ngay trước click; reference ở trên có thể đã stale.
                find_follow(driver, SELECTOR_TIMEOUT_SECONDS).click()
                wait_following(driver, SELECTOR_TIMEOUT_SECONDS)
                log.event("job.follow_clicked", job=job)
            else:
                log.event("job.already_following", job=job)

            status = api.follow_status(job["target_id"]).unwrap()
            if not status["following"]:
                log.error("job.verification_failed", job=job, data=status)
                raise RunnerStop("VERIFICATION_FAILED")

            verified = api.verify_action(job["id"], job["target_id"])
            if not verified.ok:
                _handle_api_failure(api, log, context, verified, "verify")
            log.event(
                "job.action_verified",
                job=job,
                data={
                    "receipt_id": verified.unwrap()["verification_receipt_id"],
                    "receipt_trust": verified.unwrap()["verification_receipt_trust"],
                },
            )

            claim_payload = _claim_with_retry(api, log, context, job)
            log.event(
                "job.claimed",
                job=job,
                data={
                    "points_pending": claim_payload["points_pending"],
                    "points_added": claim_payload["points_added"],
                },
            )

            if claim_payload["settlement_required"]:
                settled = _settle_with_retry(api, log, context, session_id)
                log.event(
                    "settlement.completed",
                    data={
                        "settled_count": settled["settled_count"],
                        "points_earned": settled["points_earned"],
                    },
                )

    except _PausedSafety as exc:
        result.exit_code = EXIT_PAUSED_SAFETY
        result.error_code = exc.code
        log.warn("session.paused_for_safety", data={"reason": exc.code, "operation": exc.operation})

    except BROWSER_FAILURES as exc:
        result.exit_code = EXIT_BROWSER_CRASH
        result.error_code = "BROWSER_CRASH"
        take_screenshot(driver, session_id, context.current_job_id, "browser_crash", log)
        log.error("session.browser_crash", data={"error": type(exc).__name__})
        api.best_effort_stop(
            session_id,
            reason="UNHANDLED_ERROR",
            warning_type="BROWSER_CRASH",
            note=type(exc).__name__,
        )
        if debug:
            traceback.print_exc()

    except RunnerStop as exc:
        result.exit_code = EXIT_STOPPED
        result.error_code = exc.code
        log.error("session.stopped", data={"reason": exc.code, "note": exc.note})
        api.best_effort_stop(session_id, reason=_map_stop_reason(exc.code), note=exc.note)
        if debug:
            traceback.print_exc()

    except requests.RequestException as exc:
        # API không reachable: best_effort_stop cũng sẽ thất bại theo đúng
        # thiết kế. §14.1 chấp nhận session RUNNING mồ côi ở nhánh này.
        result.exit_code = EXIT_UNHANDLED
        result.error_code = "NETWORK_ERROR"
        log.error("session.network_error", data={"error": type(exc).__name__})
        api.best_effort_stop(session_id, reason="UNHANDLED_ERROR", note=type(exc).__name__)
        if debug:
            traceback.print_exc()

    except Exception as exc:  # noqa: BLE001
        result.exit_code = EXIT_UNHANDLED
        result.error_code = "UNHANDLED_ERROR"
        take_screenshot(driver, session_id, context.current_job_id, "unhandled_error", log)
        log.error("session.unhandled_error", data={"error": repr(exc)})
        api.best_effort_stop(session_id, reason="UNHANDLED_ERROR", note=repr(exc))
        if debug:
            traceback.print_exc()

    finally:
        safe_quit(driver)

    result.summary = api.best_effort_summary(session_id)
    result.log_path = str(log.path)
    log.event("run.summary", data={"exit_code": result.exit_code, "summary": result.summary})
    api.close()
    return result


# ------------------------------------------------------------- internals

class _PausedSafety(Exception):
    def __init__(self, code: str, operation: str) -> None:
        self.code = code
        self.operation = operation
        super().__init__(code)


def _detect_protection(driver: Any) -> str | None:
    if exists(driver, CAPTCHA_SELECTOR):
        return "CAPTCHA"
    if exists(driver, CHECKPOINT_SELECTOR):
        return "CHECKPOINT"
    return None


def _handle_api_failure(
    api: ApiClient,
    log: RunLogger,
    context: RunnerContext,
    result: Any,
    operation: str,
) -> None:
    """Chuyển lỗi API thành nhánh dừng/pause đúng, không nuốt lỗi."""
    code = result.error_code
    if code == "RATE_LIMITED":
        _pause_for_safety(api, log, context, result, operation)
    log.error(
        "api.failed",
        job=context.current_job,
        data={"operation": operation, "error_code": code, "status": result.status},
    )
    raise RunnerStop(code or "API_ERROR", f"operation={operation}")


def _pause_for_safety(
    api: ApiClient,
    log: RunLogger,
    context: RunnerContext,
    result: Any,
    operation: str,
) -> None:
    log.warn(
        "api.rate_limited",
        job=context.current_job,
        data={"operation": operation, "details": result.details},
    )
    if RATE_LIMIT_BEHAVIOR == "stop":
        api.best_effort_stop(context.session_id, reason="RATE_LIMIT_STOP", note=operation)
        raise RunnerStop("RATE_LIMIT_STOP", operation)
    api.pause_for_safety(
        context.session_id,
        reason="RATE_LIMITED",
        retry_after_seconds=result.details.get("retry_after_seconds"),
        operation=operation,
    )
    raise _PausedSafety("RATE_LIMITED", operation)


def _claim_with_retry(
    api: ApiClient, log: RunLogger, context: RunnerContext, job: dict[str, Any]
) -> dict[str, Any]:
    for _ in range(MAX_CLAIM_RETRIES):
        result = api.claim(job["id"])
        if result.ok:
            return result.payload
        if result.error_code == "CLAIM_TOO_EARLY":
            wait = max(1, int(result.details.get("retry_after_seconds", 1)))
            log.event("job.claim_too_early", job=job, data={"retry_after_seconds": wait})
            time.sleep(wait)
            continue
        _handle_api_failure(api, log, context, result, "claim")
    raise RunnerStop("CLAIM_RETRY_EXHAUSTED")


def _settle_with_retry(
    api: ApiClient, log: RunLogger, context: RunnerContext, session_id: str
) -> dict[str, Any]:
    for _ in range(MAX_SETTLE_RETRIES):
        result = api.settle(session_id)
        if result.ok:
            return result.payload
        if result.error_code == "SETTLEMENT_TOO_EARLY":
            wait = max(1, int(result.details.get("retry_after_seconds", 1)))
            log.event("settlement.too_early", data={"retry_after_seconds": wait})
            time.sleep(wait)
            continue
        _handle_api_failure(api, log, context, result, "settle")
    raise RunnerStop("SETTLE_RETRY_EXHAUSTED")


def _map_stop_reason(code: str) -> str:
    return {
        "UI_AUTOMATION_FAILED": "UI_AUTOMATION_FAILED",
        "VERIFICATION_FAILED": "UI_AUTOMATION_FAILED",
        "RATE_LIMIT_STOP": "RATE_LIMIT_STOP",
        "SESSION_TIMEOUT": "UNHANDLED_ERROR",
    }.get(code, "UNHANDLED_ERROR")


# ------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock lab Selenium runner")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--seed-file", default="jobs_happy.json")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    result = run(
        args.base_url,
        args.seed_file,
        headed=args.headed,
        debug=args.debug,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
