from __future__ import annotations

import pytest

from app.core.errors import NotFoundError
from app.reels.pages import REPO_ROOT, image_dir, page_path


def test_repo_root_contains_the_viewer_pages() -> None:
    assert (REPO_ROOT / "viewer.html").is_file()
    assert (REPO_ROOT / "viewer2.html").is_file()


def test_page_path_resolves_a_seeded_page() -> None:
    assert page_path("viewer.html") == REPO_ROOT / "viewer.html"


@pytest.mark.parametrize(
    "page_file",
    ["../backend/.env", "backend/../.env", ".hidden.html", "viewer.txt", "sub/viewer.html"],
)
def test_page_path_rejects_anything_but_a_bare_html_name(page_file: str) -> None:
    with pytest.raises(NotFoundError):
        page_path(page_file)


def test_image_dir_resolves_seeded_dirs_and_rejects_traversal() -> None:
    assert image_dir("image") == REPO_ROOT / "image"
    assert image_dir("image2") == REPO_ROOT / "image2"
    assert image_dir("../backend") is None
    assert image_dir("nope") is None
