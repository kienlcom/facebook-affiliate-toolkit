from __future__ import annotations

import pytest

from app.jobs.state_machine import InvalidTransitionError, JobState, StateConflictError, transition


def test_valid_transition() -> None:
    assert transition(JobState.FETCHED, JobState.FETCHED, JobState.VALIDATED) == JobState.VALIDATED


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (JobState.FETCHED, JobState.CLAIMED),
        (JobState.OPENED, JobState.CLAIMING),
        (JobState.WAITING_USER, JobState.CLAIMING),
        (JobState.USER_SKIPPED, JobState.CLAIMING),
        (JobState.LINK_INVALID, JobState.CLAIMING),
        (JobState.CLAIMED, JobState.CLAIMING),
        (JobState.CANCELLED, JobState.CLAIMING),
        (JobState.ACCOUNT_PROTECTION_STOP, JobState.CLAIMING),
    ],
)
def test_invalid_transitions(source: JobState, target: JobState) -> None:
    with pytest.raises(InvalidTransitionError):
        transition(source, source, target)


def test_state_conflict_reports_409() -> None:
    with pytest.raises(StateConflictError) as exc_info:
        transition(JobState.OPENED, JobState.WAITING_USER, JobState.USER_CONFIRMED)
    assert exc_info.value.status_code == 409


def test_confirmed_can_move_to_claim_pending() -> None:
    assert transition(JobState.USER_CONFIRMED, JobState.USER_CONFIRMED, JobState.CLAIM_PENDING) == JobState.CLAIM_PENDING


@pytest.mark.parametrize(
    "target",
    [JobState.ACCOUNT_PROTECTION_STOP, JobState.CANCELLED],
)
def test_claiming_can_be_stopped_for_safety(target: JobState) -> None:
    assert transition(JobState.CLAIMING, JobState.CLAIMING, target) is target
