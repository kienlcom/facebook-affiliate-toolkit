from __future__ import annotations

import os


def pytest_configure() -> None:
    os.environ.setdefault("TDS_ACCESS_TOKEN", "test-token")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tds:tds@localhost:5432/tds_assistant")
