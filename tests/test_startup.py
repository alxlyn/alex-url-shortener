import asyncio

from app import init_db


async def test_parallel_startup_creates_the_schema_once(db_pool):
    # Several instances starting at once on an empty database.
    await db_pool.execute("DROP TABLE urls")
    await asyncio.gather(*[init_db() for _ in range(4)])
    assert await db_pool.fetchval("SELECT count(*) FROM urls") == 0


async def test_a_path_that_cant_be_a_code_never_reaches_the_database(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "db_pool", None)  # any database call would crash
    r = await client.get("/favicon.ico")
    assert r.status_code == 404


def test_templates_and_static_files_load_from_any_working_directory():
    import os

    import app as app_module

    assert os.path.isabs(app_module.BASE_DIR)
