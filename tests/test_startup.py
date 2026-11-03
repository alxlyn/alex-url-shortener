import asyncio

from app import init_db


async def test_parallel_startup_creates_the_schema_once(db_pool):
    # Several instances starting at once on an empty database.
    await db_pool.execute("DROP TABLE urls")
    await asyncio.gather(*[init_db() for _ in range(4)])
    assert await db_pool.fetchval("SELECT count(*) FROM urls") == 0
