"""Nhóm C — fault scenario E2E với Selenium.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §13.3.

Nguyên tắc: không dùng sleep cố định để đồng bộ với runner. Mọi lần can thiệp
giữa chừng đều poll store cho tới khi job đạt state mong muốn (helpers.wait_for).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import DriverHolder, RunnerThread, event_names, job_in_state, read_events, wait_for
from logging_setup import screenshot_path
from runner import (
    EXIT_BROWSER_CRASH,
    EXIT_OK,
    EXIT_PAUSED_SAFETY,
    EXIT_STOPPED,
    EXIT_UNHANDLED,
    build_selenium_driver,
    run,
)

pytestmark = pytest.mark.selenium


# --------------------------------------------------------------- C01 / C02


@pytest.mark.parametrize(
    ("seed", "warning_type"),
    [
        ("jobs_fault_captcha.json", "CAPTCHA"),
        ("jobs_fault_checkpoint.json", "CHECKPOINT"),
    ],
    ids=["c01_captcha", "c02_checkpoint"],
)
def test_c01_c02_protection_stops_before_click(server, seed, warning_type):
    result = run(server.base_url, seed, headed=False)

    assert result.exit_code == EXIT_STOPPED
    assert result.error_code == f"ACCOUNT_PROTECTION_STOP:{warning_type}"

    summary = result.summary
    assert summary["status"] == "STOPPED"
    assert summary["stop_reason"] == "ACCOUNT_PROTECTION_STOP"
    # Bằng chứng dừng TRƯỚC click, không chỉ là dừng.
    assert summary["jobs_clicked"] == 0
    assert summary["jobs_action_verified"] == 0
    assert summary["jobs_claimed"] == 0
    assert summary["points_earned"] == 0
    assert summary["jobs"][0]["state"] == "ACCOUNT_PROTECTION_STOP"

    events = event_names(read_events(result.log_path))
    assert "job.follow_clicked" not in events
    assert "job.action_verified" not in events
    assert "job.claimed" not in events

    shot = screenshot_path(result.session_id, None, warning_type.lower())
    assert list(shot.parent.glob(f"*-{warning_type.lower()}.png")), "thiếu screenshot"


# --------------------------------------------------------------- C03 / C05


@pytest.mark.parametrize(
    "seed",
    ["jobs_fault_no_button.json", "jobs_fault_slow_timeout.json"],
    ids=["c03_no_button", "c05_slow_timeout"],
)
def test_c03_c05_missing_selector_maps_to_open_failed(server, seed):
    """NO-GO §14.2: selector thiếu KHÔNG được map sang UNHANDLED_ERROR."""
    result = run(server.base_url, seed, headed=False)

    assert result.exit_code == EXIT_STOPPED
    assert result.error_code == "UI_AUTOMATION_FAILED"

    summary = result.summary
    assert summary["stop_reason"] == "UI_AUTOMATION_FAILED"
    assert summary["jobs"][0]["state"] == "OPEN_FAILED"
    assert summary["jobs_claimed"] == 0

    job_id = summary["jobs"][0]["id"]
    shot = screenshot_path(result.session_id, job_id, "follow_button_timeout")
    assert shot.is_file(), f"thiếu screenshot tại {shot}"
    assert shot.stat().st_size > 0


# --------------------------------------------------------------------- C04


def test_c04_slow_render_within_timeout_succeeds(server):
    """delay 3000ms < timeout 5s. Delay phải ở client, không phải server."""
    result = run(server.base_url, "jobs_fault_slow_ok.json", headed=False)

    assert result.exit_code == EXIT_OK, result.error_code
    summary = result.summary
    assert summary["jobs_clicked"] == 1
    assert summary["jobs_claimed"] == 1
    assert summary["points_earned"] == 600, "seed threshold=1 nên phải settle luôn"
    assert summary["stop_reason"] == "COMPLETED_NO_MORE_JOBS"


# --------------------------------------------------------------------- C06


def test_c06_api_offline_midrun_is_fatal(server):
    """P0-3: API unreachable thì runner KHÔNG dọn được session.

    Test assert đúng điều đó thay vì đòi hỏi một hành vi bất khả thi.
    """
    api = server.api
    store = server.store

    runner = RunnerThread(lambda: run(server.base_url, "jobs_happy.json", headed=False))
    with runner:
        wait_for(
            job_in_state(store, "ACTION_VERIFIED"),
            message="job chưa tới ACTION_VERIFIED",
        )
        api.set_fault("api_offline").unwrap()
        result = runner.join()

    assert result.exit_code != EXIT_OK
    assert result.error_code == "MOCK_API_OFFLINE"

    # Read-only endpoint vẫn sống nên test quan sát được trạng thái cuối.
    api.set_fault("none").unwrap()
    summary = api.summary(result.session_id).unwrap()
    assert summary["status"] == "RUNNING", (
        "session RUNNING mồ côi là kết quả HỢP LỆ khi API unreachable (§14.1)"
    )
    assert summary["points_earned"] == 0

    events = event_names(read_events(result.log_path))
    assert "api.failed" in events
    assert "run.summary" in events


# --------------------------------------------------------------------- C07


def test_c07_connection_refused_is_fatal(closed_port):
    result = run(f"http://127.0.0.1:{closed_port}", "jobs_happy.json", headed=False)

    assert result.exit_code == EXIT_UNHANDLED
    assert result.error_code == "BOOTSTRAP_FAILED"
    assert result.session_id is None
    # §12.1: lỗi trước khi có session đi vào bootstrap log dùng run_id.
    events = read_events(result.log_path)
    assert Path(result.log_path).name.startswith("bootstrap-")
    assert events[0]["event"] == "run.bootstrap_failed"
    assert "run_id" in events[0]
    assert "session_id" not in events[0]


# --------------------------------------------------------- C08 / C09 / C10


def test_c08_rate_limit_on_fetch_pauses_session(server):
    server.api.set_fault("rate_limit_fetch").unwrap()

    result = run(server.base_url, "jobs_single.json", headed=False)

    assert result.exit_code == EXIT_PAUSED_SAFETY
    assert result.error_code == "RATE_LIMITED"
    assert result.summary["status"] == "PAUSED_SAFETY"
    assert result.summary["pause_reason"] == "RATE_LIMITED"
    assert result.summary["jobs_fetched"] == 0
    assert server.api.circuit().unwrap()["state"] == "OPEN"


def test_c09_rate_limit_on_claim_pauses_without_double_claim(server):
    server.api.set_fault("rate_limit_claim").unwrap()

    result = run(server.base_url, "jobs_single.json", headed=False)

    assert result.exit_code == EXIT_PAUSED_SAFETY
    summary = result.summary
    assert summary["status"] == "PAUSED_SAFETY"
    assert summary["jobs_claimed"] == 0
    assert summary["points_earned"] == 0
    assert summary["jobs"][0]["state"] == "ACTION_VERIFIED", "job không được kẹt CLAIMING"
    assert server.api.circuit().unwrap()["state"] == "OPEN"


def test_c10_rate_limit_on_settle_keeps_pending_intact(server):
    server.api.set_fault("rate_limit_settle").unwrap()

    result = run(server.base_url, "jobs_single.json", headed=False)

    assert result.exit_code == EXIT_PAUSED_SAFETY
    summary = result.summary
    assert summary["status"] == "PAUSED_SAFETY"
    assert summary["jobs_claimed"] == 1, "claim phải thành công, chỉ settle bị chặn"
    assert summary["points_earned"] == 0, "điểm chưa được cộng vì settle thất bại"
    assert summary["pending_points"] == 600
    assert summary["settlement_pending_count"] == 1


def test_c08b_resume_requires_clearing_fault_first(server):
    """§7.15.1: probe luôn thất bại nếu fault chưa được tắt."""
    from datetime import timedelta

    server.api.set_fault("rate_limit_claim").unwrap()
    result = run(server.base_url, "jobs_single.json", headed=False)
    session_id = result.session_id

    assert server.api.resume(session_id).error_code == "RATE_LIMITED"

    server.api.set_fault("none").unwrap()
    with server.store.lock:
        server.store.circuit["opened_at"] -= timedelta(
            seconds=server.store.circuit["retry_after_seconds"] + 1
        )
    assert server.api.resume(session_id).unwrap()["status"] == "RUNNING"


# --------------------------------------------------------------------- C11


def test_c11_browser_crash_is_caught_and_cleaned_up(server):
    """§11.4: test giữ handle driver qua injected factory rồi quit() cưỡng bức."""
    holder = DriverHolder(build_selenium_driver)
    store = server.store

    runner = RunnerThread(
        lambda: run(
            server.base_url,
            "jobs_happy.json",
            headed=False,
            driver_factory=holder,
        )
    )
    with runner:
        holder.wait_ready()
        wait_for(
            job_in_state(store, "WAITING_ACTION"),
            message="job chưa tới WAITING_ACTION",
        )
        holder.driver.quit()
        result = runner.join()

    assert result.exit_code == EXIT_BROWSER_CRASH
    assert result.error_code == "BROWSER_CRASH"

    summary = result.summary
    assert summary["status"] == "STOPPED", "API còn reachable nên session PHẢI được dọn"
    assert summary["stop_reason"] == "UNHANDLED_ERROR"
    assert summary["points_earned"] == 0

    events = event_names(read_events(result.log_path))
    assert "session.browser_crash" in events
    # safe_quit phải idempotent — driver đã đóng rồi vẫn không được ném lỗi.
    assert runner.exception is None
