"""A03 — atomic claim dưới contention.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §5.4.

Test tuần tự KHÔNG bắt được race condition. Bắt buộc dùng threading.Barrier
để mọi thread cùng chạm claim tại một thời điểm.
"""

from __future__ import annotations

import threading
from collections import Counter

import pytest
import requests

import state_machine as sm
from errors import ApiError

THREADS = 20
ROUNDS = 50
DELAY_ROUNDS = 10

ACCEPTED_LOSER_CODES = {"JOB_ALREADY_CLAIMING", "ALREADY_CLAIMED"}


def _drive_store_job_to_verified(store, session_id: str) -> str:
    job = store.reserve_next_job(session_id, "http://127.0.0.1:0")
    assert job is not None, "seed hết job — tăng số job trong jobs_concurrent.json"
    store.mark_opened(job["id"])
    store.set_follow(job["target_id"])
    store.verify_action(job["id"], job["target_id"], "mock_status_api")
    return job["id"]


def _run_barrier(worker, thread_count: int) -> list:
    barrier = threading.Barrier(thread_count)
    results: list = [None] * thread_count
    lock = threading.Lock()

    def _target(index: int) -> None:
        barrier.wait()
        outcome = worker()
        with lock:
            results[index] = outcome

    threads = [
        threading.Thread(target=_target, args=(i,), name=f"claimer-{i}")
        for i in range(thread_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "có thread bị treo"
    return results


def _tally(outcomes: list) -> Counter:
    return Counter(outcomes)


# ------------------------------------------------------------- store-level


def test_a03_store_level_single_winner(server):
    """Đo race thuần trên Store, không lẫn nhiễu HTTP."""
    store = server.store
    session = store.create_session("jobs_concurrent.json")
    session_id = session["id"]

    for round_index in range(ROUNDS):
        job_id = _drive_store_job_to_verified(store, session_id)

        def worker(job_id=job_id):
            try:
                store.claim(job_id)
                return "OK"
            except ApiError as exc:
                return exc.code

        tally = _tally(_run_barrier(worker, THREADS))

        assert tally["OK"] == 1, f"vòng {round_index}: {tally}"
        assert tally["ACTION_NOT_VERIFIED"] == 0, f"vòng {round_index}: {tally}"
        losers = sum(count for code, count in tally.items() if code != "OK")
        assert losers == THREADS - 1
        assert set(tally) - {"OK"} <= ACCEPTED_LOSER_CODES, tally
        assert store.get_job(job_id)["state"] == sm.CLAIMED

    summary = store.summary(session_id)
    assert summary["jobs_claimed"] == ROUNDS, "double claim làm lệch counter"
    assert summary["points_earned"] == 0, "claim không được cộng điểm"
    assert summary["pending_points"] == ROUNDS * 100


# -------------------------------------------------------------- HTTP-level


def test_a03_http_level_single_winner(server):
    """Đo đúng contract mà runner dùng."""
    api = server.api
    session_id = api.create_session("jobs_concurrent.json").unwrap()["id"]
    claim_url_base = f"{server.base_url}/api/jobs"

    for round_index in range(ROUNDS):
        job = api.next_job(session_id).unwrap()["job"]
        api.mark_opened(job["id"]).unwrap()
        api.follow(job["target_id"]).unwrap()
        api.verify_action(job["id"], job["target_id"]).unwrap()

        def worker(job_id=job["id"]):
            # Mỗi thread mở connection riêng để không chia sẻ connection pool.
            response = requests.post(f"{claim_url_base}/{job_id}/claim", timeout=30)
            if response.status_code == 200:
                return "OK"
            return (response.json().get("error") or {}).get("code", "UNKNOWN")

        tally = _tally(_run_barrier(worker, THREADS))

        assert tally["OK"] == 1, f"vòng {round_index}: {tally}"
        assert tally["ACTION_NOT_VERIFIED"] == 0, f"vòng {round_index}: {tally}"
        assert set(tally) - {"OK"} <= ACCEPTED_LOSER_CODES, tally

    assert api.summary(session_id).unwrap()["jobs_claimed"] == ROUNDS


# -------------------------------------------------- A03b: claim_delay knob


def test_a03b_claiming_branch_is_actually_covered(server):
    """§5.4.1.

    Không có knob claim_delay thì cửa sổ CLAIMING gần bằng 0 và nhánh
    JOB_ALREADY_CLAIMING không bao giờ được cover — trong khi NO-GO §14.2
    lại yêu cầu chứng minh chính nhánh này.
    """
    api = server.api
    store = server.store
    session_id = api.create_session("jobs_concurrent.json").unwrap()["id"]
    api.set_fault("claim_delay", ms=50).unwrap()

    seen: Counter = Counter()
    for _ in range(DELAY_ROUNDS):
        job_id = _drive_store_job_to_verified(store, session_id)

        def worker(job_id=job_id):
            response = requests.post(
                f"{server.base_url}/api/jobs/{job_id}/claim", timeout=30
            )
            if response.status_code == 200:
                return "OK"
            return (response.json().get("error") or {}).get("code", "UNKNOWN")

        tally = _tally(_run_barrier(worker, THREADS))
        assert tally["OK"] == 1
        seen.update(tally)

    assert seen["JOB_ALREADY_CLAIMING"] > 0, (
        "nhánh JOB_ALREADY_CLAIMING không được cover — "
        f"phân bố thực tế: {dict(seen)}"
    )
    assert seen["ACTION_NOT_VERIFIED"] == 0, (
        "NO-GO §14.2: thread thứ hai không được trả nhầm ACTION_NOT_VERIFIED "
        "khi job đang CLAIMING"
    )
    assert seen["OK"] == DELAY_ROUNDS


@pytest.mark.parametrize("attempt", range(3))
def test_a03c_repeatable(server, attempt):
    """DoD: chạy lặp nhiều lần, không lần nào double claim."""
    store = server.store
    session_id = store.create_session("jobs_concurrent.json")["id"]
    job_id = _drive_store_job_to_verified(store, session_id)

    def worker():
        try:
            store.claim(job_id)
            return "OK"
        except ApiError as exc:
            return exc.code

    tally = _tally(_run_barrier(worker, THREADS))
    assert tally["OK"] == 1
    assert store.summary(session_id)["jobs_claimed"] == 1
