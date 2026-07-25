from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    FETCHED = "FETCHED"
    VALIDATED = "VALIDATED"
    OPENING = "OPENING"
    OPENED = "OPENED"
    WAITING_USER = "WAITING_USER"
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_SKIPPED = "USER_SKIPPED"
    LINK_INVALID = "LINK_INVALID"
    OPEN_FAILED = "OPEN_FAILED"
    CLAIM_PENDING = "CLAIM_PENDING"
    CLAIMING = "CLAIMING"
    CLAIMED = "CLAIMED"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    RETRY_WAIT = "RETRY_WAIT"
    AUTH_FAILED = "AUTH_FAILED"
    ACCOUNT_PROTECTION_STOP = "ACCOUNT_PROTECTION_STOP"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {
    JobState.USER_SKIPPED,
    JobState.LINK_INVALID,
    JobState.OPEN_FAILED,
    JobState.CLAIMED,
    JobState.CLAIM_REJECTED,
    JobState.AUTH_FAILED,
    JobState.ACCOUNT_PROTECTION_STOP,
    JobState.CANCELLED,
}

ACTIVE_STATES = set(JobState) - TERMINAL_STATES

ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.FETCHED: {JobState.VALIDATED, JobState.LINK_INVALID, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
    JobState.VALIDATED: {JobState.OPENING, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
    JobState.OPENING: {JobState.OPENED, JobState.OPEN_FAILED, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
    JobState.OPENED: {JobState.WAITING_USER, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
    JobState.WAITING_USER: {
        JobState.USER_CONFIRMED,
        JobState.USER_SKIPPED,
        JobState.LINK_INVALID,
        JobState.ACCOUNT_PROTECTION_STOP,
        JobState.CANCELLED,
    },
    JobState.USER_CONFIRMED: {JobState.CLAIM_PENDING, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
    JobState.CLAIM_PENDING: {JobState.CLAIMING, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
    JobState.CLAIMING: {
        JobState.CLAIMED,
        JobState.RETRY_WAIT,
        JobState.CLAIM_REJECTED,
        JobState.AUTH_FAILED,
        JobState.ACCOUNT_PROTECTION_STOP,
        JobState.CANCELLED,
    },
    JobState.RETRY_WAIT: {JobState.CLAIMING, JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED},
}


class InvalidTransitionError(ValueError):
    def __init__(self, source: JobState, target: JobState) -> None:
        super().__init__(f"Cannot transition job from {source} to {target}")
        self.source = source
        self.target = target


class StateConflictError(RuntimeError):
    def __init__(self, expected: JobState, actual: JobState) -> None:
        super().__init__(f"Job state changed from expected {expected} to {actual}")
        self.expected = expected
        self.actual = actual
        self.status_code = 409


def can_transition(source: JobState, target: JobState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source, set())


def transition(current: JobState, expected: JobState, target: JobState) -> JobState:
    if current != expected:
        raise StateConflictError(expected=expected, actual=current)
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
    return target


def ensure_can_claim(state: JobState) -> None:
    if state != JobState.USER_CONFIRMED:
        raise InvalidTransitionError(state, JobState.CLAIM_PENDING)
