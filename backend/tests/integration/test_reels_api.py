from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient
from selenium.common.exceptions import NoSuchElementException

from app.main import app
from app.reels.browser import NEXT_SELECTOR
from app.reels.pages import REPO_ROOT

RUN_TIMEOUT_SECONDS = 15


class FakePage:
    def __init__(self, url: str, image_count: int) -> None:
        self.url = url
        self.image_count = image_count
        self.index = 1

    @property
    def at_last_image(self) -> bool:
        return self.index >= self.image_count


class FakeNextButton:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    def get_attribute(self, name: str) -> str | None:
        return "true" if name == "aria-disabled" and self._page.at_last_image else "false"

    def is_enabled(self) -> bool:
        return not self._page.at_last_image

    def click(self) -> None:
        self._page.index += 1


class FakeDriver:
    """Đứng thay Chrome: mọi trang có đúng 3 ảnh."""

    visited: list[str] = []

    def __init__(self) -> None:
        self.current: FakePage | None = None

    def get(self, url: str) -> None:
        FakeDriver.visited.append(url)
        self.current = FakePage(url, 3)

    def find_element(self, by: str, selector: str) -> FakeNextButton:
        assert selector == NEXT_SELECTOR
        if self.current is None:
            raise NoSuchElementException(selector)
        return FakeNextButton(self.current)

    def quit(self) -> None:
        pass


def wait_for_finish(client: TestClient) -> dict[str, Any]:
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        payload = client.get("/api/reels/run").json()
        if payload["status"] not in {"PENDING", "RUNNING"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("reel run did not finish in time")


def test_seeded_links_are_listed_with_absolute_urls() -> None:
    with TestClient(app) as client:
        links = client.get("/api/reels").json()

    assert [link["slug"] for link in links] == ["viewer-1", "viewer-2"]
    assert links[0]["url"] == "/reels/viewer-1"
    assert links[0]["absolute_url"].endswith("/reels/viewer-1")
    assert all(link["enabled"] for link in links)


def test_reel_page_and_its_images_are_served() -> None:
    image_name = next(path.name for path in sorted((REPO_ROOT / "image").iterdir()))

    with TestClient(app) as client:
        page = client.get("/reels/viewer-1")
        # Trang tham chiếu ảnh tương đối; từ /reels/viewer-1 nó phân giải vào
        # mount /reels/image, nên hai thứ này phải khớp nhau.
        image = client.get(f"/reels/image/{image_name}")
        traversal = client.get("/reels/image/../../backend/.env")
        missing = client.get("/reels/nope")

    assert page.status_code == 200
    assert NEXT_SELECTOR in page.text
    assert f'"image/{image_name}"' in page.text

    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"

    assert traversal.status_code == 404
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REEL_LINK_NOT_FOUND"


def test_run_browses_every_seeded_link_then_reports_totals() -> None:
    FakeDriver.visited = []
    with TestClient(app) as client:
        app.state.reel_run_manager.driver_factory = lambda headed: FakeDriver()

        started = client.post("/api/reels/run", json={"dwell_seconds": 0.01})
        assert started.status_code == 200
        assert started.json()["link_count"] == 2

        finished = wait_for_finish(client)

    assert finished["status"] == "COMPLETED"
    assert finished["result"] == {
        "links_completed": 2,
        "links_failed": 0,
        "images_viewed": 6,
        "stopped": False,
    }
    assert [url.rsplit("/", 1)[-1] for url in FakeDriver.visited] == ["viewer-1", "viewer-2"]

    events = [event["event"] for event in finished["events"]]
    assert events.count("link.completed") == 2
    assert events[-1] == "run.finished"
