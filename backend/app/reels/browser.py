"""Selenium reel browser: mở từng link, lướt hết ảnh rồi sang link kế tiếp.

Quy tắc Selenium giống mock-lab runner: không giữ lại ``WebElement`` qua một
DOM mutation. Mỗi lần đọc trạng thái nút hoặc click đều re-find selector.

Vòng lặp dừng lướt một trang khi nút next bị disable (``aria-disabled="true"``)
— đó là tín hiệu trang phát ra ở ảnh cuối cùng — chứ không dựa vào
``image_count`` trong DB, nên số ảnh thực tế đổi cũng không cần sửa DB.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

NEXT_SELECTOR = '[data-e2e="feed-navigation-next"]'
STAGE_IMAGE_SELECTOR = ".stage img"

# Lát cắt sleep đủ nhỏ để nút Stop phản hồi trong ~nửa giây.
STOP_POLL_SECONDS = 0.5

EventEmitter = Callable[[str, str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class ReelTarget:
    """Một hàng reel_links đã được phân giải thành URL tuyệt đối."""

    id: str
    slug: str
    title: str
    url: str
    image_count: int


@dataclass(frozen=True, slots=True)
class BrowseResult:
    links_completed: int = 0
    links_failed: int = 0
    images_viewed: int = 0
    stopped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "links_completed": self.links_completed,
            "links_failed": self.links_failed,
            "images_viewed": self.images_viewed,
            "stopped": self.stopped,
        }


def build_driver(headed: bool = True) -> webdriver.Chrome:
    options = Options()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    return webdriver.Chrome(options=options)


def safe_quit(driver: Any) -> None:
    """Idempotent — gọi được cả khi driver đã đóng."""
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:  # noqa: BLE001
        pass


class ReelBrowser:
    def __init__(
        self,
        driver: Any,
        *,
        dwell_seconds: float,
        selector_timeout_seconds: float,
        max_images_per_link: int,
        emit: EventEmitter,
        stop_event: threading.Event | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._driver = driver
        self._dwell_seconds = dwell_seconds
        self._selector_timeout_seconds = selector_timeout_seconds
        self._max_images_per_link = max_images_per_link
        self._emit = emit
        self._stop_event = stop_event or threading.Event()
        self._sleep = sleep

    # ------------------------------------------------------------------ public

    def browse(self, targets: list[ReelTarget]) -> BrowseResult:
        links_completed = 0
        links_failed = 0
        images_viewed = 0

        for target in targets:
            if self._stopped():
                break
            self._emit("INFO", "link.opening", self._target_data(target))
            self._driver.get(target.url)

            if not self._wait_for_navigation(target):
                links_failed += 1
                continue

            self._emit("INFO", "link.opened", self._target_data(target))
            viewed = self._browse_one(target)
            images_viewed += viewed
            links_completed += 1
            self._emit(
                "INFO",
                "link.completed",
                {**self._target_data(target), "images_viewed": viewed},
            )

        stopped = self._stopped()
        self._emit(
            "INFO",
            "run.finished",
            {
                "links_completed": links_completed,
                "links_failed": links_failed,
                "images_viewed": images_viewed,
                "stopped": stopped,
            },
        )
        return BrowseResult(
            links_completed=links_completed,
            links_failed=links_failed,
            images_viewed=images_viewed,
            stopped=stopped,
        )

    # --------------------------------------------------------------- internals

    def _browse_one(self, target: ReelTarget) -> int:
        """Lướt hết ảnh của một trang. Trả về số ảnh đã xem."""
        viewed = 1
        self._emit("INFO", "image.viewed", {**self._target_data(target), "index": viewed})

        while viewed < self._max_images_per_link:
            if not self._dwell():
                break
            if self._next_disabled():
                self._emit(
                    "INFO",
                    "link.last_image",
                    {**self._target_data(target), "index": viewed},
                )
                break
            if not self._click_next(target):
                break
            viewed += 1
            self._emit("INFO", "image.viewed", {**self._target_data(target), "index": viewed})
        else:
            self._emit(
                "WARN",
                "link.image_cap_reached",
                {**self._target_data(target), "max_images_per_link": self._max_images_per_link},
            )
        return viewed

    def _wait_for_navigation(self, target: ReelTarget) -> bool:
        try:
            WebDriverWait(self._driver, self._selector_timeout_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, NEXT_SELECTOR))
            )
            return True
        except TimeoutException:
            self._emit(
                "ERROR",
                "link.nav_timeout",
                {
                    **self._target_data(target),
                    "selector": NEXT_SELECTOR,
                    "timeout_seconds": self._selector_timeout_seconds,
                },
            )
            return False

    def _next_disabled(self) -> bool:
        """Re-find mỗi lần đọc — DOM đã đổi sau click trước đó."""
        try:
            element = self._driver.find_element(By.CSS_SELECTOR, NEXT_SELECTOR)
        except NoSuchElementException:
            return True
        if element.get_attribute("aria-disabled") == "true":
            return True
        return not element.is_enabled()

    def _click_next(self, target: ReelTarget) -> bool:
        try:
            self._driver.find_element(By.CSS_SELECTOR, NEXT_SELECTOR).click()
            return True
        except (NoSuchElementException, WebDriverException) as exc:
            self._emit(
                "ERROR",
                "image.click_failed",
                {**self._target_data(target), "error": type(exc).__name__},
            )
            return False

    def _dwell(self) -> bool:
        """Chờ ``dwell_seconds`` theo lát cắt. False nếu bị yêu cầu dừng."""
        remaining = self._dwell_seconds
        while remaining > 0:
            if self._stopped():
                return False
            slice_seconds = min(STOP_POLL_SECONDS, remaining)
            self._sleep(slice_seconds)
            remaining -= slice_seconds
        return not self._stopped()

    def _stopped(self) -> bool:
        return self._stop_event.is_set()

    @staticmethod
    def _target_data(target: ReelTarget) -> dict[str, Any]:
        return {"link_id": target.id, "slug": target.slug, "title": target.title}
