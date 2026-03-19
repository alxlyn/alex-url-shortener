"""
Pytest configuration and shared fixtures.

Requires a test PostgreSQL database. Set TEST_DATABASE_URL or ensure
postgresql://localhost/url_shortener_test exists locally.

CI: GitHub Actions spins up a postgres service container automatically.
"""
import os

import asyncpg
import pytest

# Must be set before importing app — prevents lifespan from running init_db
_test_db_url = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://localhost/url_shortener_test",
)
os.environ["DATABASE_URL"] = _test_db_url
os.environ["SKIP_DB_INIT"] = "1"

import app as app_module  # noqa: E402
from app import app as fastapi_app, init_db  # noqa: E402


@pytest.fixture
async def db_pool():
    """Per-test asyncpg pool. Function-scoped so pool and tests share the same event loop.

    Note: httpx ASGITransport does NOT trigger the FastAPI lifespan, so this pool
    stays as app_module.db_pool throughout the test — routes use it directly.
    """
    pool = await asyncpg.create_pool(_test_db_url)
    app_module.db_pool = pool
    await init_db()
    yield pool
    await pool.close()
    app_module.db_pool = None


@pytest.fixture
async def client(db_pool):
    """Per-test async HTTP client. Depends on db_pool so the pool is ready before requests."""
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
async def clean_db(db_pool):
    """Wipe the urls table before each test to guarantee isolation."""
    await db_pool.execute("DELETE FROM urls")


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset in-memory rate limit counters between tests.

    The limiter is a module-level singleton initialized at import time with
    memory:// storage. Its counters persist across tests in the same process —
    this fixture clears all keys before each test to prevent bleed-over.

    Uses limiter.reset() — slowapi's public API — which internally calls
    storage.reset() with proper error handling. Does not touch the DB;
    ordering relative to db_pool/clean_db fixtures is irrelevant.
    """
    from app import limiter

    limiter.reset()
    yield
