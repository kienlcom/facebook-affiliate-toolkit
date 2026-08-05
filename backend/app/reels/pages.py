"""Định vị các trang HTML và thư mục ảnh mà reel runner lướt qua.

Trang HTML nằm ở repo root (viewer.html, viewer2.html) và tham chiếu ảnh bằng
đường dẫn tương đối ``image/...``. Route ``/reels/{slug}`` trả nội dung trang,
còn các thư mục ảnh được mount ở ``/reels/{tên thư mục}`` — nhờ vậy đường dẫn
tương đối trong trang phân giải đúng cả khi mở qua backend lẫn khi mở file trực
tiếp bằng trình duyệt.
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import NotFoundError

REPO_ROOT = Path(__file__).resolve().parents[3]


def page_path(page_file: str) -> Path:
    """Trả về đường dẫn tuyệt đối của một trang reel.

    Chỉ chấp nhận tên file ``.html`` trần nằm ngay repo root — chặn path
    traversal từ giá trị ``page_file`` lưu trong DB.
    """
    if (
        not page_file.endswith(".html")
        or Path(page_file).name != page_file
        or page_file.startswith(".")
    ):
        raise NotFoundError("REEL_PAGE_INVALID", f"Invalid reel page file: {page_file}")
    path = REPO_ROOT / page_file
    if not path.is_file():
        raise NotFoundError("REEL_PAGE_NOT_FOUND", f"Reel page file not found: {page_file}")
    return path


def image_dir(name: str) -> Path | None:
    """Thư mục ảnh ở repo root, hoặc None nếu không tồn tại."""
    if Path(name).name != name or name.startswith("."):
        return None
    path = REPO_ROOT / name
    return path if path.is_dir() else None
