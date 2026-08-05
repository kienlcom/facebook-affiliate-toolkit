from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.api.dependencies import get_reel_service
from app.core.errors import NotFoundError
from app.reels.pages import page_path
from app.reels.service import ReelService
from app.schemas.reel import (
    ReelLinkResponse,
    ReelRunLogsResponse,
    ReelRunRequest,
    ReelRunResponse,
)

router = APIRouter(prefix="/api/reels", tags=["reels"])

# Router riêng: trang HTML không nằm dưới /api vì Selenium mở nó như một trang
# web bình thường, và ảnh tương đối phải phân giải vào các mount /reels/<dir>.
pages_router = APIRouter(prefix="/reels", tags=["reels"])


@router.get("", response_model=list[ReelLinkResponse])
async def list_reel_links(
    service: ReelService = Depends(get_reel_service),
) -> list[ReelLinkResponse]:
    links = await service.list_links()
    return [
        ReelLinkResponse(
            id=link.id,
            slug=link.slug,
            title=link.title,
            url=link.url,
            absolute_url=service.absolute_url(link.url),
            image_count=link.image_count,
            sort_order=link.sort_order,
            enabled=link.enabled,
        )
        for link in links
    ]


@router.post("/run", response_model=ReelRunResponse)
async def start_reel_run(
    payload: ReelRunRequest | None = None,
    service: ReelService = Depends(get_reel_service),
) -> ReelRunResponse:
    request = payload or ReelRunRequest()
    started = await service.start_run(
        dwell_seconds=request.dwell_seconds,
        headed=request.headed,
    )
    return ReelRunResponse(**started)


@router.get("/run", response_model=ReelRunLogsResponse)
async def reel_run_status(
    service: ReelService = Depends(get_reel_service),
) -> ReelRunLogsResponse:
    return ReelRunLogsResponse(**service.run_status())


@router.post("/run/stop", response_model=ReelRunResponse)
async def stop_reel_run(
    service: ReelService = Depends(get_reel_service),
) -> ReelRunResponse:
    return ReelRunResponse(**service.stop_run())


@pages_router.get("/{slug}", response_class=HTMLResponse)
async def reel_page(
    slug: str,
    service: ReelService = Depends(get_reel_service),
) -> HTMLResponse:
    links = await service.list_links()
    link = next((item for item in links if item.slug == slug), None)
    if link is None:
        raise NotFoundError("REEL_LINK_NOT_FOUND", f"No reel link with slug {slug}")
    return HTMLResponse(page_path(link.page_file).read_text(encoding="utf-8"))
