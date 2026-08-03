"""Unit test cho state machine mock (§9.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import state_machine as sm
from errors import ApiError


def test_terminal_states_have_no_outgoing_transitions():
    assert sm.TERMINAL_STATES == {
        sm.CLAIMED,
        sm.OPEN_FAILED,
        sm.ACCOUNT_PROTECTION_STOP,
        sm.CANCELLED,
    }


def test_every_target_state_is_declared():
    """Không có state đích nào nằm ngoài bảng — chống typo."""
    for source, targets in sm.ALLOWED_TRANSITIONS.items():
        for target in targets:
            assert target in sm.ALLOWED_TRANSITIONS, f"{source} -> {target}"


def test_production_only_states_are_absent():
    """§9.1.1: ba state này thuộc production, không thuộc mock."""
    for state in ("LINK_INVALID", "RETRY_WAIT", "CLAIM_REJECTED"):
        assert state not in sm.JOB_STATES


def test_happy_path_chain_is_walkable():
    job = {"state": sm.FETCHED}
    for target in (
        sm.VALIDATED,
        sm.OPENING,
        sm.OPENED,
        sm.WAITING_ACTION,
        sm.ACTION_VERIFIED,
        sm.CLAIM_PENDING,
        sm.CLAIMING,
        sm.CLAIMED,
    ):
        sm.transition(job, target)
    assert job["state"] == sm.CLAIMED


def test_no_self_transition_on_waiting_action():
    """§7.5: idempotent opened phải bỏ qua transition, không gọi lại nó."""
    assert not sm.can_transition(sm.WAITING_ACTION, sm.WAITING_ACTION)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (sm.FETCHED, sm.CLAIMED),
        (sm.WAITING_ACTION, sm.CLAIMING),
        (sm.ACTION_VERIFIED, sm.CLAIMED),
        (sm.CLAIMED, sm.CLAIMING),
        (sm.OPEN_FAILED, sm.WAITING_ACTION),
    ],
)
def test_illegal_transitions_raise(source, target):
    job = {"state": source}
    with pytest.raises(ApiError) as exc:
        sm.transition(job, target)
    assert exc.value.code == "JOB_INVALID_STATE"
    assert job["state"] == source, "state không được đổi khi transition thất bại"


def test_claim_cannot_skip_claim_pending():
    """Claim gate phải đi qua CLAIM_PENDING, không nhảy thẳng sang CLAIMING."""
    assert not sm.can_transition(sm.ACTION_VERIFIED, sm.CLAIMING)


def test_active_state_can_always_be_cancelled():
    for state in sm.ACTIVE_STATES:
        assert sm.can_transition(state, sm.CANCELLED), state


def test_session_transitions():
    session = {"status": sm.RUNNING}
    sm.transition_session(session, sm.PAUSED_SAFETY)
    sm.transition_session(session, sm.RUNNING)
    sm.transition_session(session, sm.STOPPED)
    with pytest.raises(ApiError):
        sm.transition_session(session, sm.RUNNING)


def test_serialize_datetime():
    assert sm.serialize_datetime(None) is None
    value = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    assert sm.serialize_datetime(value) == "2026-07-28T10:00:00+00:00"
