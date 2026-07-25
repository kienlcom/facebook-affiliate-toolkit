from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_database_schema_after_migration() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    expected_tables = {"accounts", "sessions", "jobs", "job_attempts", "api_calls", "app_state"}
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_name = any(:tables)"
            ),
            {"tables": list(expected_tables)},
        )
        tables = {row[0] for row in result}
        account_count = await conn.scalar(text("select count(*) from accounts where display_name = 'Local User'"))
    await engine.dispose()
    assert tables == expected_tables
    assert account_count == 1
