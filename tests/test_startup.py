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


async def test_templates_and_static_files_load_from_any_working_directory(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # an empty folder, so relative paths would find nothing
    assert (await client.get("/")).status_code == 200
    assert (await client.get("/static/style.css")).status_code == 200


async def test_a_stats_path_that_cant_be_a_code_never_reaches_the_database(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "db_pool", None)  # any database call would crash
    assert (await client.get("/stats/favicon.ico")).status_code == 404


async def test_the_app_opens_and_closes_its_pool():
    import app as app_module

    async with app_module.lifespan(app_module.app):
        pool = app_module.db_pool
        assert await pool.fetchval("SELECT 1") == 1
    assert pool.is_closing()
