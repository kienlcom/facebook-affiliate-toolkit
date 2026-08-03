"""Nhóm A — API contract test. Không chạy Selenium.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §13.1.
"""

from __future__ import annotations

import time

import pytest
import requests

from conftest import drive_job_to_verified


def test_health(api):
    payload = api.health().unwrap()
    assert payload["status"] == "ok"
    assert payload["app_env"] == "test"
    assert payload["circuit_state"] == "CLOSED"


# --------------------------------------------------------------------- A01


def test_a01_claim_before_verify_is_rejected(api):
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    api.mark_opened(job["id"]).unwrap()

    result = api.claim(job["id"])

    assert result.status == 409
    assert result.error_code == "ACTION_NOT_VERIFIED"
    # P0-1: đọc lại job để chứng minh state không bị đổi.
    assert api.get_job(job["id"]).unwrap()["state"] == "WAITING_ACTION"


# --------------------------------------------------------------------- A02


def test_a02_verify_without_follow_fails(api):
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    api.mark_opened(job["id"]).unwrap()

    result = api.verify_action(job["id"], job["target_id"])

    assert result.status == 409
    assert result.error_code == "VERIFICATION_FAILED"
    assert result.details["following"] is False
    assert api.get_job(job["id"]).unwrap()["state"] == "WAITING_ACTION"


def test_a02b_verification_receipt_is_marked_self_issued(api):
    """§9.5: receipt của mock phải tự khai là SELF_ISSUED_MOCK."""
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    api.mark_opened(job["id"]).unwrap()
    api.follow(job["target_id"]).unwrap()

    payload = api.verify_action(job["id"], job["target_id"]).unwrap()

    assert payload["state"] == "ACTION_VERIFIED"
    assert payload["verification_receipt_id"]
    assert payload["verification_receipt_trust"] == "SELF_ISSUED_MOCK"
    # Verify hai lần không hợp lệ — job đã rời WAITING_ACTION.
    assert api.verify_action(job["id"], job["target_id"]).error_code == "JOB_INVALID_STATE"


# --------------------------------------------------------------------- A04


def test_a04_claim_before_minimum_wait(api):
    session = api.create_session("jobs_min_wait.json").unwrap()
    job = drive_job_to_verified(api, session["id"])

    started = time.monotonic()
    result = api.claim(job["id"])
    elapsed = time.monotonic() - started

    assert elapsed < 15, "claim phải được gọi trước khi hết minimum wait"
    assert result.status == 409
    assert result.error_code == "CLAIM_TOO_EARLY"
    assert result.details["retry_after_seconds"] > 0
    assert "eligible_at" in result.details
    assert api.get_job(job["id"]).unwrap()["state"] == "ACTION_VERIFIED"


def test_a04b_zero_minimum_wait_allows_immediate_claim(api):
    """§6.5: minimum_claim_wait_seconds = 0 là giá trị hợp lệ."""
    session = api.create_session("jobs_concurrent.json").unwrap()
    job = drive_job_to_verified(api, session["id"])
    assert api.claim(job["id"]).unwrap()["state"] == "CLAIMED"


# --------------------------------------------------------------------- A05


def test_a05_opened_is_idempotent(api):
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]

    first = api.mark_opened(job["id"]).unwrap()
    time.sleep(0.05)
    second = api.mark_opened(job["id"]).unwrap()

    assert first["opened_at"] == second["opened_at"], "wait clock bị reset"
    assert second["state"] == "WAITING_ACTION"
    assert api.summary(session["id"]).unwrap()["jobs_opened"] == 1


# --------------------------------------------------------------------- A06


def test_a06_test_endpoints_disabled_outside_test_env(server_factory):
    handle = server_factory(app_env="development")

    reset = handle.api.reset()
    fault = handle.api.set_fault("api_offline")

    assert reset.status == 403
    assert reset.error_code == "TEST_ENDPOINT_DISABLED"
    assert fault.status == 403
    # Endpoint nghiệp vụ vẫn hoạt động bình thường.
    assert handle.api.health().unwrap()["app_env"] == "development"


# --------------------------------------------------------------------- A07


def test_a07_invalid_scenario_returns_html_error_panel(server):
    response = requests.get(f"{server.base_url}/profiles/page-x?scenario=nope", timeout=10)

    assert response.status_code == 400
    assert "text/html" in response.headers["Content-Type"]
    assert 'data-testid="error-panel"' in response.text
    assert 'data-error-code="INVALID_SCENARIO"' in response.text


def test_a07b_slow_render_requires_delay_ms(server):
    response = requests.get(
        f"{server.base_url}/profiles/page-x?scenario=slow_render", timeout=10
    )
    assert response.status_code == 400
    assert 'data-testid="error-panel"' in response.text


def test_a07c_delay_ms_out_of_range(server):
    response = requests.get(
        f"{server.base_url}/profiles/page-x?scenario=slow_render&delay_ms=99999",
        timeout=10,
    )
    assert response.status_code == 400


# --------------------------------------------------------------------- A08


def test_a08_rate_limited_claim_opens_circuit(api):
    session = api.create_session("jobs_concurrent.json").unwrap()
    job = drive_job_to_verified(api, session["id"])
    api.set_fault("rate_limit_claim").unwrap()

    result = api.claim(job["id"])

    assert result.status == 429
    assert result.error_code == "RATE_LIMITED"
    assert result.details["operation"] == "claim"
    assert result.details["retry_after_seconds"] > 0
    assert api.circuit().unwrap()["state"] == "OPEN"


def test_a08b_open_circuit_blocks_further_operations(api):
    session = api.create_session("jobs_concurrent.json").unwrap()
    job = drive_job_to_verified(api, session["id"])
    api.set_fault("rate_limit_claim").unwrap()
    api.claim(job["id"])
    api.set_fault("none").unwrap()

    # Circuit vẫn OPEN cho tới khi hết retry-after, kể cả khi fault đã clear.
    blocked = api.claim(job["id"])
    assert blocked.error_code == "RATE_LIMITED"
    assert api.circuit().unwrap()["state"] == "OPEN"


# --------------------------------------------------------------------- A09/A10/A11


def test_a09_settle_before_threshold(api):
    session = api.create_session("jobs_happy.json").unwrap()
    job = drive_job_to_verified(api, session["id"])
    time.sleep(job["minimum_claim_wait_seconds"])
    api.claim(job["id"]).unwrap()

    result = api.settle(session["id"])

    assert result.status == 409
    assert result.error_code == "SETTLEMENT_NOT_READY"
    assert result.details["settlement_pending_count"] == 1
    assert result.details["settlement_threshold"] == 2


def test_a10_settle_before_settlement_wait(api):
    session = api.create_session("jobs_two_batch.json").unwrap()
    for _ in range(2):
        job = drive_job_to_verified(api, session["id"])
        api.claim(job["id"]).unwrap()

    result = api.settle(session["id"])

    assert result.status == 409
    assert result.error_code == "SETTLEMENT_TOO_EARLY"
    assert result.details["retry_after_seconds"] > 0


def test_a11_two_batches_settle_independently(api):
    """P0-2: batch thứ hai vẫn phải bị chặn bởi settlement wait.

    Seed một batch không phát hiện được lỗi thiếu reset settlement_eligible_at.
    """
    session_id = api.create_session("jobs_two_batch.json").unwrap()["id"]

    # --- batch 1
    for _ in range(2):
        job = drive_job_to_verified(api, session_id)
        claim = api.claim(job["id"]).unwrap()
        assert claim["points_added"] == 0, "claim không được cộng điểm (§7.10)"
    assert api.settle(session_id).error_code == "SETTLEMENT_TOO_EARLY"
    time.sleep(1.2)
    first = api.settle(session_id).unwrap()
    assert first["settled_count"] == 2
    assert first["points_settled"] == 200
    assert first["points_earned"] == 200
    assert first["settlement_pending_count"] == 0
    assert first["pending_points"] == 0

    # --- batch 2: nếu settlement_eligible_at không được reset về None thì
    # lần settle này sẽ đi lọt ngay lập tức thay vì bị chặn.
    for _ in range(2):
        job = drive_job_to_verified(api, session_id)
        api.claim(job["id"]).unwrap()
    assert api.settle(session_id).error_code == "SETTLEMENT_TOO_EARLY"
    time.sleep(1.2)
    second = api.settle(session_id).unwrap()
    assert second["settled_count"] == 2
    assert second["points_earned"] == 400, "điểm phải cộng dồn đúng một lần mỗi batch"

    summary = api.summary(session_id).unwrap()
    assert summary["points_earned"] == 400
    assert summary["pending_points"] == 0


def test_a11b_settle_twice_is_rejected(api):
    session_id = api.create_session("jobs_two_batch.json").unwrap()["id"]
    for _ in range(2):
        job = drive_job_to_verified(api, session_id)
        api.claim(job["id"]).unwrap()
    time.sleep(1.2)
    api.settle(session_id).unwrap()

    assert api.settle(session_id).error_code == "SETTLEMENT_NOT_READY"
    assert api.summary(session_id).unwrap()["points_earned"] == 200


# --------------------------------------------------------------------- A12/A13


def test_a12_api_offline_is_503_and_spares_readonly(api):
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    api.set_fault("api_offline").unwrap()

    blocked = api.mark_opened(job["id"])
    assert blocked.status == 503
    assert blocked.error_code == "MOCK_API_OFFLINE"

    # §7.16: read-only và fault endpoint không bị chặn, nếu không test sẽ
    # không còn cách nào tắt fault hoặc quan sát trạng thái cuối.
    assert api.get_job(job["id"]).ok
    assert api.summary(session["id"]).ok
    assert api.circuit().ok
    assert api.set_fault("none").ok


def test_a13_connection_refused_raises_network_error(closed_port):
    from api_client import ApiClient

    client = ApiClient(f"http://127.0.0.1:{closed_port}", timeout=3)
    with pytest.raises(requests.RequestException):
        client.health()


# --------------------------------------------------------------------- A14


def test_a14_invalid_seed_schema(api):
    result = api.create_session("jobs_invalid_schema.json")

    assert result.status == 400
    assert result.error_code == "INVALID_REQUEST"
    assert result.details["field"] == "jobs[0].target_id"


def test_a14b_unknown_seed_file(api):
    result = api.create_session("does_not_exist.json")
    assert result.status == 400
    assert result.details["field"] == "seed_file"


def test_a14c_seed_path_traversal_is_rejected(api):
    result = api.create_session("../server.py")
    assert result.status == 400
    assert result.error_code == "INVALID_REQUEST"


# --------------------------------------------------------------------- A15


def _force_retry_after_elapsed(server) -> None:
    """Đẩy opened_at về quá khứ thay vì sleep 30 giây thật."""
    from datetime import timedelta

    store = server.store
    with store.lock:
        if store.circuit["opened_at"] is not None:
            store.circuit["opened_at"] -= timedelta(
                seconds=store.circuit["retry_after_seconds"] + 1
            )


def test_a15_circuit_probe_closes_after_success(api, server):
    """§7.15.1: OPEN → HALF_OPEN → (probe thành công) → CLOSED."""
    session = api.create_session("jobs_concurrent.json").unwrap()
    job = drive_job_to_verified(api, session["id"])

    api.set_fault("rate_limit_claim").unwrap()
    assert api.claim(job["id"]).error_code == "RATE_LIMITED"
    assert api.circuit().unwrap()["state"] == "OPEN"

    # Test PHẢI clear fault trước khi probe, nếu không probe luôn thất bại.
    api.set_fault("none").unwrap()
    _force_retry_after_elapsed(server)
    assert api.circuit().unwrap()["state"] == "HALF_OPEN"

    # Probe = request business đầu tiên khi circuit HALF_OPEN.
    assert api.claim(job["id"]).unwrap()["state"] == "CLAIMED"
    assert api.circuit().unwrap()["state"] == "CLOSED"


def test_a15b_probe_failure_reopens_circuit(api, server):
    session = api.create_session("jobs_concurrent.json").unwrap()
    job = drive_job_to_verified(api, session["id"])

    api.set_fault("rate_limit_claim").unwrap()
    api.claim(job["id"])
    _force_retry_after_elapsed(server)
    assert api.circuit().unwrap()["state"] == "HALF_OPEN"

    # Fault vẫn bật → probe thất bại → circuit mở lại.
    assert api.claim(job["id"]).error_code == "RATE_LIMITED"
    assert api.circuit().unwrap()["state"] == "OPEN"


def test_a15c_session_pause_and_resume(api, server):
    session_id = api.create_session("jobs_concurrent.json").unwrap()["id"]
    api.pause_for_safety(session_id, "RATE_LIMITED", 30, "claim").unwrap()

    paused = api.summary(session_id).unwrap()
    assert paused["status"] == "PAUSED_SAFETY"
    assert paused["pause_reason"] == "RATE_LIMITED"
    # Session paused thì không cấp job mới.
    assert api.next_job(session_id).error_code == "SESSION_PAUSED"

    resumed = api.resume(session_id).unwrap()
    assert resumed["status"] == "RUNNING"
    assert api.next_job(session_id).ok


def test_a15d_resume_blocked_while_circuit_open(api, server):
    session = api.create_session("jobs_concurrent.json").unwrap()
    job = drive_job_to_verified(api, session["id"])
    api.set_fault("rate_limit_claim").unwrap()
    api.claim(job["id"])
    api.pause_for_safety(session["id"], "RATE_LIMITED", 30, "claim").unwrap()

    blocked = api.resume(session["id"])
    assert blocked.error_code == "RATE_LIMITED"

    api.set_fault("none").unwrap()
    _force_retry_after_elapsed(server)
    assert api.resume(session["id"]).unwrap()["status"] == "RUNNING"


# ------------------------------------------------------------ stop cascade


def test_stop_cascades_job_states(api):
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    api.mark_opened(job["id"]).unwrap()

    api.stop_session(session["id"], "ACCOUNT_PROTECTION_STOP", "CAPTCHA").unwrap()

    summary = api.summary(session["id"]).unwrap()
    assert summary["status"] == "STOPPED"
    assert summary["stop_reason"] == "ACCOUNT_PROTECTION_STOP"
    states = {row["external_id"]: row["state"] for row in summary["jobs"]}
    assert states["mock-follow-001"] == "ACCOUNT_PROTECTION_STOP"
    assert states["mock-follow-002"] == "CANCELLED"


def test_open_failed_sets_terminal_state(api):
    session = api.create_session("jobs_fault_no_button.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    api.mark_opened(job["id"]).unwrap()

    api.open_failed(job["id"], "FOLLOW_BUTTON_TIMEOUT", {"timeout_seconds": 5}).unwrap()

    stored = api.get_job(job["id"]).unwrap()
    assert stored["state"] == "OPEN_FAILED"
    assert stored["last_error_code"] == "FOLLOW_BUTTON_TIMEOUT"


def test_runtime_url_uses_request_origin_not_seed(api, server):
    """B1 của review v1.0: seed chỉ giữ path, port là runtime."""
    session = api.create_session("jobs_happy.json").unwrap()
    job = api.next_job(session["id"]).unwrap()["job"]
    assert job["url"] == f"{server.base_url}/profiles/page-anna?scenario=success"
    assert str(server.port) in job["url"]


def test_already_following_seed_preloads_follow_state(api):
    """§6.6: không preload thì verify-action sẽ VERIFICATION_FAILED."""
    session = api.create_session("jobs_happy.json").unwrap()
    assert api.follow_status("page-ben").unwrap()["following"] is True
    assert api.follow_status("page-anna").unwrap()["following"] is False
    assert session["settlement_threshold"] == 2
