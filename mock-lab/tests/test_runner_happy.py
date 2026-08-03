"""Nhóm B — happy path E2E với Selenium.

§13.2: B01–B04 dùng MỘT server + MỘT lần chạy runner, rồi bốn assertion trên
cùng kết quả. Không spin browser riêng cho từng assertion.
"""

from __future__ import annotations

import threading

import pytest

from helpers import event_names, read_events
from runner import EXIT_OK, run
from server import build_server

pytestmark = pytest.mark.selenium


@pytest.fixture(scope="module")
def happy_run():
    """Một server, một run, dùng lại cho B01–B04."""
    from pathlib import Path

    data_dir = Path(__file__).resolve().parent.parent / "data"
    httpd = build_server("127.0.0.1", 0, app_env="test", data_dir=data_dir)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        result = run(base_url, "jobs_happy.json", headed=False)
        yield result, httpd.store
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_b01_two_jobs_claimed(happy_run):
    result, _ = happy_run
    assert result.exit_code == EXIT_OK, result.error_code
    summary = result.summary
    assert summary["jobs_claimed"] == 2
    assert [job["state"] for job in summary["jobs"]] == ["CLAIMED", "CLAIMED"]


def test_b02_already_following_job_is_not_clicked_again(happy_run):
    result, _ = happy_run
    # Seed có 1 job success + 1 job already_following.
    assert result.summary["jobs_clicked"] == 1, "job already-following bị click lại"

    events = event_names(read_events(result.log_path))
    assert events.count("job.follow_clicked") == 1
    assert events.count("job.already_following") == 1


def test_b03_points_credited_once_at_settlement(happy_run):
    """NO-GO §14.2: điểm không được cộng ở cả claim lẫn settle."""
    result, _ = happy_run
    summary = result.summary

    assert summary["points_earned"] == 1200, "phải là 1200, không phải 2400"
    assert summary["pending_points"] == 0
    assert summary["settlement_pending_count"] == 0
    assert summary["settlement_eligible_at"] is None

    events = read_events(result.log_path)
    claimed = [e for e in events if e["event"] == "job.claimed"]
    assert len(claimed) == 2
    assert all(e["data"]["points_added"] == 0 for e in claimed), (
        "claim response không được báo points_added > 0"
    )
    settled = [e for e in events if e["event"] == "settlement.completed"]
    assert len(settled) == 1, "settlement phải chạy đúng một lần cho một batch"
    assert settled[0]["data"]["points_earned"] == 1200


def test_b04_queue_exhaustion_stops_session(happy_run):
    result, _ = happy_run
    assert result.summary["status"] == "STOPPED"
    assert result.summary["stop_reason"] == "COMPLETED_NO_MORE_JOBS"


def test_b04b_log_contract(happy_run):
    """§12.1: mọi event sau khi có session phải mang session_id non-null."""
    result, _ = happy_run
    events = read_events(result.log_path)
    assert events, "log rỗng"
    for event in events:
        assert event["ts"]
        assert event["level"] in {"INFO", "WARN", "ERROR"}
        assert event["event"]
        assert isinstance(event["data"], dict)
        assert event["session_id"] == result.session_id
        assert event["session_id"] is not None


def test_b05_runner_waits_out_minimum_claim_wait(server):
    """B05: seed 15 giây khiến CLAIM_TOO_EARLY xảy ra deterministic."""
    result = run(server.base_url, "jobs_min_wait.json", headed=False)

    assert result.exit_code == EXIT_OK, result.error_code
    assert result.summary["jobs_claimed"] == 1
    assert result.summary["points_earned"] == 600

    events = read_events(result.log_path)
    too_early = [e for e in events if e["event"] == "job.claim_too_early"]
    assert too_early, "runner không hề gặp CLAIM_TOO_EARLY — seed quá ngắn?"
    assert too_early[0]["data"]["retry_after_seconds"] > 0

    # Claim thành công phải xảy ra SAU khi hết wait, không phải nhờ bỏ qua gate.
    job = result.summary["jobs"][0]
    assert job["state"] == "CLAIMED"
