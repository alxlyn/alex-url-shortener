import asyncio
from datetime import datetime, timezone

import app as app_module


def fake_codes(*codes: str):
    sequence = iter(codes)
    calls = []

    def generate_code(length: int = 6) -> str:
        code = next(sequence)
        calls.append(code)
        return code

    return generate_code, calls


async def insert(pool, code: str, long_url: str) -> None:
    await pool.execute(
        "INSERT INTO urls (code, long_url, created_at, clicks) VALUES ($1, $2, $3, 0)",
        code, long_url, datetime.now(timezone.utc),
    )


async def test_collision_retries_and_keeps_the_old_link(client, db_pool, monkeypatch):
    await insert(db_pool, "AAAAAA", "https://old.example")
    fake, calls = fake_codes("AAAAAA", "BBBBBB")
    monkeypatch.setattr(app_module, "generate_code", fake)

    r = await client.post("/shorten", data={"long_url": "https://new.example"})

    assert r.status_code == 200
    assert calls == ["AAAAAA", "BBBBBB"]
    rows = dict(await db_pool.fetch("SELECT code, long_url FROM urls"))
    assert rows == {"AAAAAA": "https://old.example", "BBBBBB": "https://new.example"}


async def test_gives_up_after_max_attempts(client, db_pool, monkeypatch):
    await insert(db_pool, "AAAAAA", "https://old.example")
    fake, calls = fake_codes(*["AAAAAA"] * app_module.MAX_CODE_ATTEMPTS)
    monkeypatch.setattr(app_module, "generate_code", fake)

    r = await client.post("/shorten", data={"long_url": "https://new.example"})

    assert r.status_code == 500
    assert len(calls) == app_module.MAX_CODE_ATTEMPTS
    assert await db_pool.fetchval("SELECT count(*) FROM urls") == 1


async def test_two_requests_racing_for_one_code_both_succeed(client, db_pool, monkeypatch):
    fake, calls = fake_codes("AAAAAA", "AAAAAA", "BBBBBB")
    monkeypatch.setattr(app_module, "generate_code", fake)

    first, second = await asyncio.gather(
        client.post("/shorten", data={"long_url": "https://one.example"}),
        client.post("/shorten", data={"long_url": "https://two.example"}),
    )

    assert first.status_code == second.status_code == 200
    assert len(calls) == 3
    codes = {row["code"] for row in await db_pool.fetch("SELECT code FROM urls")}
    assert codes == {"AAAAAA", "BBBBBB"}