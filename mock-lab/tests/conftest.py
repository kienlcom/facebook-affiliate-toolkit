"""Fixture chung cho mock lab.

Ba cạm bẫy đã biết, xử lý trong file này:
  1. ``httpd.shutdown()`` phải gọi từ thread KHÁC ``serve_forever`` — cùng thread
     sẽ deadlock.
  2. Thread server phải ``daemon=True`` để pytest không treo nếu shutdown lỗi.
  3. Chrome session-scoped nhanh hơn nhiều nhưng phải reset về about:blank giữa
     các test để không rò trạng thái trang.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

MOCK_LAB_ROOT = Path(__file__).resolve().parent.parent
if str(MOCK_LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(MOCK_LAB_ROOT))

from api_client import ApiClient  # noqa: E402
from server import build_server  # noqa: E402

DATA_DIR = MOCK_LAB_ROOT / "data"


class ServerHandle:
    def __init__(self, httpd: Any, thread: threading.Thread) -> None:
        self.httpd = httpd
        self.thread = thread
        host, port = httpd.server_address[:2]
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.store = httpd.store
        self.api = ApiClient(self.base_url)

    def stop(self) -> None:
        self.api.close()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _spawn(app_env: str = "test", **kwargs: Any) -> ServerHandle:
    httpd = build_server("127.0.0.1", 0, app_env=app_env, data_dir=DATA_DIR, **kwargs)
    thread = threading.Thread(
        target=httpd.serve_forever,
        name="mock-lab-server",
        daemon=True,
    )
    thread.start()
    return ServerHandle(httpd, thread)


@pytest.fixture
def server_factory() -> Iterator[Callable[..., ServerHandle]]:
    handles: list[ServerHandle] = []

    def _make(app_env: str = "test", **kwargs: Any) -> ServerHandle:
        handle = _spawn(app_env, **kwargs)
        handles.append(handle)
        return handle

    yield _make
    for handle in handles:
        handle.stop()


@pytest.fixture
def server(server_factory: Callable[..., ServerHandle]) -> ServerHandle:
    """Server riêng cho từng test — isolation tuyệt đối giữa các case."""
    return server_factory()


@pytest.fixture
def api(server: ServerHandle) -> ApiClient:
    return server.api


@pytest.fixture(scope="session")
def shared_server() -> Iterator[ServerHandle]:
    """Session-scoped cho nhóm B (§13.2 S7): một server, một browser, một run."""
    handle = _spawn()
    yield handle
    handle.stop()


@pytest.fixture
def closed_port() -> int:
    """Port đã bind rồi close — dùng cho test connection refused (A13/C07)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# --------------------------------------------------------------- workflow helper


def drive_job_to_verified(api: ApiClient, session_id: str) -> dict[str, Any]:
    """Đưa job kế tiếp qua next → opened → follow → verify, không cần browser."""
    job = api.next_job(session_id).unwrap()["job"]
    assert job is not None, "queue rỗng"
    api.mark_opened(job["id"]).unwrap()
    api.follow(job["target_id"]).unwrap()
    api.verify_action(job["id"], job["target_id"]).unwrap()
    return job


@pytest.fixture
def verified_job_factory(api: ApiClient) -> Callable[[str], dict[str, Any]]:
    def _make(session_id: str) -> dict[str, Any]:
        return drive_job_to_verified(api, session_id)

    return _make


# ------------------------------------------------------------------- selenium


@pytest.fixture(scope="session")
def chrome_driver():
    selenium = pytest.importorskip("selenium")  # noqa: F841
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    driver = webdriver.Chrome(options=options)
    yield driver
    driver.quit()


@pytest.fixture
def clean_page(chrome_driver):
    """Reset trang giữa các test để Chrome session-scoped không rò trạng thái."""
    yield chrome_driver
    try:
        chrome_driver.delete_all_cookies()
        chrome_driver.get("about:blank")
    except Exception:  # noqa: BLE001 - driver có thể đã chết ở test crash
        pass
