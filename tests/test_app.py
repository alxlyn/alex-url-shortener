"""
Test suite for the URL shortener.

Unit tests: generate_code(), normalize_url() — no DB required.
Integration tests: all routes — require the test PostgreSQL database.
"""
import os

import asyncpg

from app import generate_code, normalize_url


# ─────────────────────────────────────────────
# Unit Tests — pure functions, no DB
# ─────────────────────────────────────────────


class TestGenerateCode:
    def test_default_length(self):
        assert len(generate_code()) == 6

    def test_custom_length(self):
        assert len(generate_code(length=10)) == 10

    def test_alphanumeric_only(self):
        for _ in range(100):
            code = generate_code()
            assert code.isalnum(), f"Non-alphanumeric character in code: {code!r}"

    def test_produces_unique_codes(self):
        codes = {generate_code() for _ in range(200)}
        # 62^6 ≈ 56B combinations — 200 draws should all be unique
        assert len(codes) == 200


class TestNormalizeUrl:
    def test_valid_https_url_unchanged(self):
        assert normalize_url("https://example.com") == "https://example.com"

    def test_valid_http_url_unchanged(self):
        assert normalize_url("http://example.com") == "http://example.com"

    def test_bare_domain_gets_https_prefix(self):
        assert normalize_url("example.com") == "https://example.com"

    def test_strips_surrounding_whitespace(self):
        assert normalize_url("  https://example.com  ") == "https://example.com"

    def test_empty_string_returns_none(self):
        assert normalize_url("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_url("   ") is None

    def test_none_input_returns_none(self):
        assert normalize_url(None) is None  # type: ignore[arg-type]

    def test_rejects_javascript_scheme(self):
        assert normalize_url("javascript:alert(1)") is None

    def test_rejects_data_scheme(self):
        assert normalize_url("data:text/html,<script>alert(1)</script>") is None

    def test_rejects_file_scheme(self):
        assert normalize_url("file:///etc/passwd") is None

    def test_scheme_rejection_is_case_insensitive(self):
        assert normalize_url("JAVASCRIPT:alert(1)") is None
        assert normalize_url("DATA:text/plain,hello") is None
        assert normalize_url("FILE:///etc/passwd") is None


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


async def _get_first_code() -> str:
    """Fetch the first code inserted in the current test's clean slate."""
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    row = await pool.fetchrow("SELECT code FROM urls LIMIT 1")
    await pool.close()
    assert row is not None, "Expected at least one row in urls table"
    return row["code"]


async def _get_click_count(code: str) -> int:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    row = await pool.fetchrow("SELECT clicks FROM urls WHERE code = $1", code)
    await pool.close()
    assert row is not None
    return row["clicks"]


# ─────────────────────────────────────────────
# Integration Tests — require DB
# ─────────────────────────────────────────────


class TestHomeRoute:
    async def test_returns_200(self, client):
        r = await client.get("/")
        assert r.status_code == 200


class TestShortenRoute:
    async def test_valid_url_returns_200(self, client):
        r = await client.post("/shorten", data={"long_url": "https://example.com"})
        assert r.status_code == 200

    async def test_response_contains_short_url(self, client):
        r = await client.post("/shorten", data={"long_url": "https://example.com"})
        assert b"test" in r.content  # base_url is http://test

    async def test_bare_domain_accepted(self, client):
        r = await client.post("/shorten", data={"long_url": "example.com"})
        assert r.status_code == 200

    async def test_empty_url_returns_400(self, client):
        r = await client.post("/shorten", data={"long_url": ""})
        assert r.status_code == 400

    async def test_missing_url_field_returns_400(self, client):
        r = await client.post("/shorten", data={})
        assert r.status_code == 400

    async def test_javascript_url_returns_400(self, client):
        r = await client.post("/shorten", data={"long_url": "javascript:alert(1)"})
        assert r.status_code == 400

    async def test_data_url_returns_400(self, client):
        r = await client.post("/shorten", data={"long_url": "data:text/html,<h1>xss</h1>"})
        assert r.status_code == 400

    async def test_row_persisted_in_db(self, client, db_pool):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        count = await db_pool.fetchval("SELECT COUNT(*) FROM urls")
        assert count == 1


class TestRedirectRoute:
    async def test_valid_code_returns_302(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        r = await client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302

    async def test_redirect_location_matches_original_url(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        r = await client.get(f"/{code}", follow_redirects=False)
        assert "example.com" in r.headers["location"]

    async def test_each_visit_increments_click_count(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        await client.get(f"/{code}")
        await client.get(f"/{code}")
        await client.get(f"/{code}")
        assert await _get_click_count(code) == 3

    async def test_unknown_code_returns_404(self, client):
        r = await client.get("/doesnotexist")
        assert r.status_code == 404


class TestStatsRoute:
    async def test_valid_code_returns_200(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        r = await client.get(f"/stats/{code}")
        assert r.status_code == 200

    async def test_response_contains_original_url(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        r = await client.get(f"/stats/{code}")
        assert b"example.com" in r.content

    async def test_unknown_code_returns_404(self, client):
        r = await client.get("/stats/doesnotexist")
        assert r.status_code == 404


class TestTopRoute:
    async def test_empty_db_returns_200(self, client):
        r = await client.get("/top")
        assert r.status_code == 200

    async def test_shows_created_links(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        r = await client.get("/top")
        assert r.status_code == 200
        assert b"example.com" in r.content

    async def test_orders_by_clicks_descending(self, client, db_pool):
        await client.post("/shorten", data={"long_url": "https://first.com"})
        await client.post("/shorten", data={"long_url": "https://second.com"})

        second_code = await db_pool.fetchval(
            "SELECT code FROM urls WHERE long_url = 'https://second.com'"
        )
        await db_pool.execute("UPDATE urls SET clicks = 5 WHERE code = $1", second_code)

        r = await client.get("/top")
        body = r.text
        assert body.index("second.com") < body.index("first.com")
