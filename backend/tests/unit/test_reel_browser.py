from __future__ import annotations

import threading
from typing import Any

import pytest
from selenium.common.exceptions import NoSuchElementException

from app.reels.browser import NEXT_SELECTOR, ReelBrowser, ReelTarget


class FakeNextButton:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    def get_attribute(self, name: str) -> str | None:
        if name == "aria-disabled":
            return "true" if self._page.at_last_image else "false"
        return None

    def is_enabled(self) -> bool:
        return not self._page.at_last_image

    def click(self) -> None:
        if self._page.at_last_image:
            raise AssertionError("clicked next on the last image")
        self._page.index += 1


class FakePage:
    def __init__(self, url: str, image_count: int) -> None:
        self.url = url
        self.image_count = image_count
        self.index = 1

    @property
    def at_last_image(self) -> bool:
        return self.index >= self.image_count


class FakeDriver:
    """Driver tối thiểu: chỉ hiểu selector nút next của trang viewer."""

    def __init__(self, pages: dict[str, int], *, missing_nav: set[str] | None = None) -> None:
        self._pages = pages
        self._missing_nav = missing_nav or set()
        self.visited: list[str] = []
        self.current: FakePage | None = None

    def get(self, url: str) -> None:
        self.visited.append(url)
        self.current = FakePage(url, self._pages.get(url, 1))

    def find_element(self, by: str, selector: str) -> FakeNextButton:
        assert selector == NEXT_SELECTOR
        if self.current is None or self.current.url in self._missing_nav:
            raise NoSuchElementException(selector)
        return FakeNextButton(self.current)

    def quit(self) -> None:
        pass


def make_browser(
    driver: FakeDriver,
    events: list[tuple[str, str, dict[str, Any]]],
    *,
    stop_event: threading.Event | None = None,
    max_images_per_link: int = 50,
    sleeps: list[float] | None = None,
) -> ReelBrowser:
    def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return ReelBrowser(
        driver,
        dwell_seconds=5,
        selector_timeout_seconds=0.2,
        max_images_per_link=max_images_per_link,
        emit=lambda level, event, data: events.append((level, event, data)),
        stop_event=stop_event,
        sleep=sleep,
    )


def target(slug: str, url: str, image_count: int) -> ReelTarget:
    return ReelTarget(id=slug, slug=slug, title=slug, url=url, image_count=image_count)


def test_browses_every_image_then_moves_to_next_link() -> None:
    driver = FakeDriver({"http://x/reels/viewer-1": 7, "http://x/reels/viewer-2": 3})
    events: list[tuple[str, str, dict[str, Any]]] = []
    browser = make_browser(driver, events)

    result = browser.browse(
        [
            target("viewer-1", "http://x/reels/viewer-1", 7),
            target("viewer-2", "http://x/reels/viewer-2", 3),
        ]
    )

    assert driver.visited == ["http://x/reels/viewer-1", "http://x/reels/viewer-2"]
    assert result.links_completed == 2
    assert result.links_failed == 0
    assert result.images_viewed == 10
    assert result.stopped is False

    viewed_per_link = [
        (data["slug"], data["images_viewed"])
        for _, event, data in events
        if event == "link.completed"
    ]
    assert viewed_per_link == [("viewer-1", 7), ("viewer-2", 3)]


def test_waits_dwell_seconds_before_each_advance() -> None:
    driver = FakeDriver({"http://x/a": 3})
    sleeps: list[float] = []
    browser = make_browser(driver, [], sleeps=sleeps)

    browser.browse([target("a", "http://x/a", 3)])

    # 3 ảnh -> 3 lần chờ (2 lần trước khi click, 1 lần trước khi phát hiện ảnh cuối).
    assert sum(sleeps) == pytest.approx(15.0)
    assert all(value <= 0.5 for value in sleeps)


def test_stop_event_aborts_between_images() -> None:
    driver = FakeDriver({"http://x/a": 10, "http://x/b": 10})
    events: list[tuple[str, str, dict[str, Any]]] = []
    stop_event = threading.Event()
    stop_event.set()
    browser = make_browser(driver, events, stop_event=stop_event)

    result = browser.browse([target("a", "http://x/a", 10), target("b", "http://x/b", 10)])

    assert driver.visited == []
    assert result.stopped is True
    assert result.links_completed == 0


def test_missing_navigation_marks_link_failed_and_continues() -> None:
    driver = FakeDriver(
        {"http://x/broken": 5, "http://x/ok": 2},
        missing_nav={"http://x/broken"},
    )
    events: list[tuple[str, str, dict[str, Any]]] = []
    browser = make_browser(driver, events)

    result = browser.browse(
        [target("broken", "http://x/broken", 5), target("ok", "http://x/ok", 2)]
    )

    assert result.links_failed == 1
    assert result.links_completed == 1
    assert result.images_viewed == 2
    assert any(event == "link.nav_timeout" for _, event, _ in events)


def test_image_cap_stops_a_page_that_never_disables_next() -> None:
    driver = FakeDriver({"http://x/endless": 10_000})
    events: list[tuple[str, str, dict[str, Any]]] = []
    browser = make_browser(driver, events, max_images_per_link=4)

    result = browser.browse([target("endless", "http://x/endless", 10_000)])

    assert result.images_viewed == 4
    assert any(event == "link.image_cap_reached" for _, event, _ in events)
