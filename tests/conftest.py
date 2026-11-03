"""
Shared fixtures. The tests need a Postgres database: TEST_DATABASE_URL, or
postgresql://localhost/url_shortener_test by default. CI starts one as a service.
"""
import os

import asyncpg
import pytest

# Set before importing app so the lifespan skips init_db
_test_db_url = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://localhost/url_shortener_test",
)
os.environ["DATABASE_URL"] = _test_db_url
os.environ["SKIP_DB_INIT"] = "1"
# Keep rate-limit counters in memory, even if REDIS_URL is set in your shell.
os.environ["REDIS_URL"] = "memory://"

import app as app_module  # noqa: E402
from app import app as fastapi_app, init_db  # noqa: E402


@pytest.fixture
async def db_pool():
    """A new pool for each test, so the pool and the test share an event loop.

    ASGITransport doesn't run the app's lifespan, so the routes use this pool.
    """
    pool = await asyncpg.create_pool(_test_db_url)
    app_module.db_pool = pool
    await init_db()
    yield pool
    await pool.close()
    app_module.db_pool = None


@pytest.fixture
async def client(db_pool):
    """HTTP client for the app. Uses db_pool so the pool exists before the first request."""
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
async def clean_db(db_pool):
    """Empty the urls table before each test."""
    await db_pool.execute("DELETE FROM urls")


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear the rate-limit counters before each test.

    The limiter keeps its counters in memory for the whole test run.
    """
    from app import limiter

    limiter.reset()
    yield
