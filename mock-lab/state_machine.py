"""State machine mock.

Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §9.

LINK_INVALID, RETRY_WAIT và CLAIM_REJECTED tồn tại trong
backend/app/jobs/state_machine.py nhưng đã bị loại khỏi mock theo §9.1.1:
mock không có provider thật nên không có producer nào sinh ra chúng, và giữ
lại sẽ tạo ra state chỉ tồn tại trên giấy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from errors import ApiError

FETCHED = "FETCHED"
VALIDATED = "VALIDATED"
OPENING = "OPENING"
OPENED = "OPENED"
WAITING_ACTION = "WAITING_ACTION"
ACTION_VERIFIED = "ACTION_VERIFIED"
CLAIM_PENDING = "CLAIM_PENDING"
CLAIMING = "CLAIMING"
CLAIMED = "CLAIMED"
OPEN_FAILED = "OPEN_FAILED"
ACCOUNT_PROTECTION_STOP = "ACCOUNT_PROTECTION_STOP"
CANCELLED = "CANCELLED"

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    FETCHED: {VALIDATED, CANCELLED},
    VALIDATED: {OPENING, CANCELLED},
    OPENING: {OPENED, OPEN_FAILED, CANCELLED},
    OPENED: {WAITING_ACTION, OPEN_FAILED, CANCELLED},
    WAITING_ACTION: {
        ACTION_VERIFIED,
        OPEN_FAILED,
        ACCOUNT_PROTECTION_STOP,
        CANCELLED,
    },
    ACTION_VERIFIED: {CLAIM_PENDING, CANCELLED},
    CLAIM_PENDING: {CLAIMING, CANCELLED},
    CLAIMING: {CLAIMED, CANCELLED},
    OPEN_FAILED: set(),
    CLAIMED: set(),
    ACCOUNT_PROTECTION_STOP: set(),
    CANCELLED: set(),
}

JOB_STATES = frozenset(ALLOWED_TRANSITIONS)

TERMINAL_STATES = frozenset(
    state for state, targets in ALLOWED_TRANSITIONS.items() if not targets
)

ACTIVE_STATES = JOB_STATES - TERMINAL_STATES

RUNNING = "RUNNING"
PAUSED_SAFETY = "PAUSED_SAFETY"
STOPPED = "STOPPED"

SESSION_TRANSITIONS: dict[str, set[str]] = {
    RUNNING: {PAUSED_SAFETY, STOPPED},
    PAUSED_SAFETY: {RUNNING, STOPPED},
    STOPPED: set(),
}


def can_transition(source: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source, set())


def transition(job: dict[str, Any], target: str) -> str:
    """Chuyển job sang state mới, mutate job tại chỗ.

    Raise JOB_INVALID_STATE nếu transition không nằm trong ALLOWED_TRANSITIONS.
    """
    source = job["state"]
    if not can_transition(source, target):
        raise ApiError(
            "JOB_INVALID_STATE",
            f"Cannot transition job from {source} to {target}.",
            details={"from": source, "to": target},
        )
    job["state"] = target
    return target


def can_transition_session(source: str, target: str) -> bool:
    return target in SESSION_TRANSITIONS.get(source, set())


def transition_session(session: dict[str, Any], target: str) -> str:
    source = session["status"]
    if not can_transition_session(source, target):
        raise ApiError(
            "SESSION_NOT_RUNNING",
            f"Cannot transition session from {source} to {target}.",
            details={"from": source, "to": target},
        )
    session["status"] = target
    return target


def serialize_datetime(value: datetime | None) -> str | None:
    """Serialize tại HTTP/log boundary. Store luôn giữ datetime (§5.2)."""
    return value.isoformat() if value else None
