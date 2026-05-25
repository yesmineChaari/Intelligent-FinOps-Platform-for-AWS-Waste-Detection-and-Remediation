"""Database pool and read-only connection handling for dashboard queries."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from dotenv import load_dotenv


load_dotenv()

_pool: asyncpg.Pool | None = None


async def open_pool() -> None:
    """Open the dashboard database pool at application startup."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the dashboard backend.")

    global _pool
    _pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )


async def close_pool() -> None:
    """Close the application pool if startup initialized it."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the initialized connection pool."""
    if _pool is None:
        raise RuntimeError("Dashboard database pool has not been initialized.")
    return _pool


@asynccontextmanager
async def read_connection() -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection restricted to a read-only transaction."""
    async with get_pool().acquire() as conn:
        async with conn.transaction(readonly=True):
            yield conn
