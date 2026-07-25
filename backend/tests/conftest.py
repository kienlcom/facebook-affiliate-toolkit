from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
from alembic import command
from alembic.config import Config

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://tds:tds@127.0.0.1:5432/tds_assistant_test"
)


async def _ensure_test_database() -> None:
    connection = await asyncpg.connect(
        user="tds",
        password="tds",
        host="127.0.0.1",
        port=5432,
        database="postgres",
    )
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            "tds_assistant_test",
        )
        if exists is None:
            await connection.execute("CREATE DATABASE tds_assistant_test")
    finally:
        await connection.close()


def pytest_configure() -> None:
    test_database_url = os.environ.get(
        "TEST_DATABASE_URL",
        DEFAULT_TEST_DATABASE_URL,
    )
    if test_database_url.rstrip("/").endswith("/tds_assistant"):
        raise RuntimeError("Pytest refuses to use the application database")

    os.environ["TDS_ACCESS_TOKEN"] = "test-token"
    os.environ["DATABASE_URL"] = test_database_url
    asyncio.run(_ensure_test_database())

    backend_dir = Path(__file__).parents[1]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(backend_dir / "app/db/migrations"))
    command.upgrade(alembic_config, "head")
