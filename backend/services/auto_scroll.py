from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScrollConfig:
    scroll_interval: int = 30
    scroll_x: int = 500
    scroll_y_start: int = 780
    scroll_y_end: int = 240


class AutoScrollService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._skip_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._config = ScrollConfig()
        self.running = False
        self.mode = "stopped"
        self.last_scroll_at: float | None = None
        self.last_error: str | None = None
        self.active_channels_count = 0

    def start(
        self,
        channel_loader: Callable[[], list[dict[str, Any]]],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._apply_config(config)
            self.last_error = None

            if self.running and self._thread and self._thread.is_alive():
                self.mode = "running"
                self._skip_event.set()
                return self.status()

            self._stop_event.clear()
            self._skip_event.clear()
            self.running = True
            self.mode = "running"
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(channel_loader,),
                name="tiktok-shop-auto-scroll",
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self.running = False
            self.mode = "stopped"
            self._stop_event.set()
            self._skip_event.set()
            return self.status()

    def buy(self) -> dict[str, Any]:
        with self._lock:
            self.running = False
            self.mode = "waiting_for_buy"
            self._stop_event.set()
            self._skip_event.set()
            return self.status()

    def skip(self) -> dict[str, Any]:
        with self._lock:
            should_scroll_now = not self.running
            if self.running:
                self._skip_event.set()

        if should_scroll_now:
            try:
                self._perform_scroll()
            except Exception as exc:  # pragma: no cover - depends on host GUI.
                with self._lock:
                    self.last_error = str(exc)
                raise

        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "running" if self.running else "stopped",
                "running": self.running,
                "mode": self.mode,
                "config": asdict(self._config),
                "last_scroll_at": self.last_scroll_at,
                "last_error": self.last_error,
                "active_channels_count": self.active_channels_count,
            }

    def _apply_config(self, config: dict[str, Any] | None) -> None:
        if not config:
            return

        scroll_interval = int(config.get("scroll_interval", self._config.scroll_interval))
        scroll_x = int(config.get("scroll_x", self._config.scroll_x))
        scroll_y_start = int(config.get("scroll_y_start", self._config.scroll_y_start))
        scroll_y_end = int(config.get("scroll_y_end", self._config.scroll_y_end))

        self._config = ScrollConfig(
            scroll_interval=max(10, min(60, scroll_interval)),
            scroll_x=max(0, scroll_x),
            scroll_y_start=max(0, scroll_y_start),
            scroll_y_end=max(0, scroll_y_end),
        )

    def _run_loop(self, channel_loader: Callable[[], list[dict[str, Any]]]) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    channels = channel_loader()
                    with self._lock:
                        self.active_channels_count = len(channels)
                except Exception as exc:
                    logger.exception("auto_scroll.channel_load_failed")
                    with self._lock:
                        self.last_error = f"Cannot load channels: {exc}"

                interval = self._current_config().scroll_interval
                self._skip_event.wait(interval)
                self._skip_event.clear()

                if self._stop_event.is_set():
                    break

                try:
                    self._perform_scroll()
                except Exception as exc:  # pragma: no cover - depends on host GUI.
                    logger.exception("auto_scroll.scroll_failed")
                    with self._lock:
                        self.last_error = str(exc)
                    time.sleep(1)
        finally:
            with self._lock:
                self.running = False
                if self.mode == "running":
                    self.mode = "stopped"

    def _current_config(self) -> ScrollConfig:
        with self._lock:
            return ScrollConfig(**asdict(self._config))

    def _perform_scroll(self) -> None:
        import pyautogui

        config = self._current_config()
        pyautogui.moveTo(config.scroll_x, config.scroll_y_start, duration=0.1)
        pyautogui.dragTo(
            config.scroll_x,
            config.scroll_y_end,
            duration=0.35,
            button="left",
        )
        with self._lock:
            self.last_scroll_at = time.time()


auto_scroll_service = AutoScrollService()
