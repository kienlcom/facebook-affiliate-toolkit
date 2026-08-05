"""Đọc bảng reel_links và khởi động lượt lướt ảnh."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.core.errors import ConflictError
from app.db.models import ReelLink
from app.reels.browser import ReelTarget
from app.reels.manager import ReelRunManager


class ReelService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        run_manager: ReelRunManager,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._run_manager = run_manager

    async def list_links(self, *, enabled_only: bool = False) -> list[ReelLink]:
        statement = select(ReelLink).order_by(ReelLink.sort_order, ReelLink.slug)
        if enabled_only:
            statement = statement.where(ReelLink.enabled.is_(True))
        async with self._session_factory() as db:
            return list(await db.scalars(statement))

    async def start_run(
        self,
        *,
        dwell_seconds: float | None = None,
        headed: bool | None = None,
    ) -> dict[str, Any]:
        links = await self.list_links(enabled_only=True)
        if not links:
            raise ConflictError(
                "REEL_LINKS_EMPTY",
                "There are no enabled links in reel_links to browse",
            )
        return self._run_manager.start(
            [self._to_target(link) for link in links],
            dwell_seconds=(
                dwell_seconds if dwell_seconds is not None else self._settings.REEL_DWELL_SECONDS
            ),
            selector_timeout_seconds=self._settings.REEL_SELECTOR_TIMEOUT_SECONDS,
            max_images_per_link=self._settings.REEL_MAX_IMAGES_PER_LINK,
            headed=headed if headed is not None else self._settings.REEL_RUNNER_HEADED,
        )

    def run_status(self) -> dict[str, Any]:
        return self._run_manager.status()

    def stop_run(self) -> dict[str, Any]:
        return self._run_manager.stop()

    def _to_target(self, link: ReelLink) -> ReelTarget:
        return ReelTarget(
            id=str(link.id),
            slug=link.slug,
            title=link.title,
            url=self.absolute_url(link.url),
            image_count=link.image_count,
        )

    def absolute_url(self, url: str) -> str:
        """URL trong DB là đường dẫn tương đối; Selenium cần origin đầy đủ."""
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(f"{self._settings.REEL_BASE_URL.rstrip('/')}/", url.lstrip("/"))
