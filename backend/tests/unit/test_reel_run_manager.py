from __future__ import annotations

import threading

import pytest
from selenium.common.exceptions import NoSuchElementException

from app.core.errors import ConflictError, NotFoundError
from app.reels.browser import ReelTarget
from app.reels.manager import ReelRunManager

JOIN_TIMEOUT_SECONDS = 5


class BlockingDriver:
    """Treo ở ``get`` cho tới khi test thả ra — giữ run ở trạng thái RUNNING."""

    def __init__(self, release: threading.Event, entered: threading.Event) -> None:
        self._release = release
        self._entered = entered

    def get(self, url: str) -> None:
        self._entered.set()
        self._release.wait(JOIN_TIMEOUT_SECONDS)

    def find_element(self, by: str, selector: str) -> None:
        raise NoSuchElementException(selector)

    def quit(self) -> None:
        pass


def targets() -> list[ReelTarget]:
    return [ReelTarget(id="1", slug="a", title="a", url="http://x/a", image_count=1)]


def start(manager: ReelRunManager) -> dict[str, object]:
    return manager.start(
        targets(),
        dwell_seconds=0.01,
        selector_timeout_seconds=0.05,
        max_images_per_link=10,
        headed=False,
    )


def test_status_before_any_run_is_not_found() -> None:
    manager = ReelRunManager(driver_factory=lambda headed: None)
    with pytest.raises(NotFoundError):
        manager.status()
    with pytest.raises(NotFoundError):
        manager.stop()


def test_second_start_is_rejected_while_a_run_is_active() -> None:
    release = threading.Event()
    entered = threading.Event()
    manager = ReelRunManager(driver_factory=lambda headed: BlockingDriver(release, entered))

    try:
        first = start(manager)
        assert entered.wait(JOIN_TIMEOUT_SECONDS)

        with pytest.raises(ConflictError) as excinfo:
            start(manager)
        assert excinfo.value.code == "REEL_RUN_ALREADY_RUNNING"
        assert excinfo.value.details["run_id"] == first["run_id"]
    finally:
        release.set()

    manager.current()._thread.join(JOIN_TIMEOUT_SECONDS)
    assert manager.status()["status"] in {"COMPLETED", "STOPPED"}


def test_stop_after_the_run_finished_is_a_conflict() -> None:
    release = threading.Event()
    release.set()
    entered = threading.Event()
    manager = ReelRunManager(driver_factory=lambda headed: BlockingDriver(release, entered))

    start(manager)
    manager.current()._thread.join(JOIN_TIMEOUT_SECONDS)

    with pytest.raises(ConflictError) as excinfo:
        manager.stop()
    assert excinfo.value.code == "REEL_RUN_NOT_RUNNING"
