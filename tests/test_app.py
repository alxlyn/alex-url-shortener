"""
Unit tests for generate_code() and normalize_url(), which need no database,
and integration tests for every route, which use the test database.
"""
import asyncio
import os
import re
import string

import asyncpg

from app import generate_code, normalize_url


# Unit tests (no database)


class TestGenerateCode:
    def test_default_length(self):
        assert len(generate_code()) == 6

    def test_custom_length(self):
        assert len(generate_code(length=10)) == 10

    def test_only_ascii_letters_and_digits(self):
        allowed = set(string.ascii_letters + string.digits)
        for _ in range(100):
            assert set(generate_code()) <= allowed

    def test_produces_unique_codes(self):
        codes = {generate_code() for _ in range(200)}
        # 62^6 is about 57 billion codes, so 200 draws should all differ.
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


# Helpers


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


# Integration tests (test database)


class TestHomeRoute:
    async def test_returns_200(self, client):
        r = await client.get("/")
        assert r.status_code == 200


class TestShortenRoute:
    async def test_valid_url_returns_200(self, client):
        r = await client.post("/shorten", data={"long_url": "https://example.com"})
        assert r.status_code == 200

    async def test_response_shows_the_stored_short_link(self, client, db_pool):
        r = await client.post("/shorten", data={"long_url": "https://example.com"})
        match = re.search(r'href="http://test/([A-Za-z0-9]{6})"', r.text)
        assert match, "no short link in the page"
        stored = await db_pool.fetchval("SELECT long_url FROM urls WHERE code = $1", match.group(1))
        assert stored == "https://example.com"

    async def test_bare_domain_is_stored_with_https(self, client, db_pool):
        r = await client.post("/shorten", data={"long_url": "example.com"})
        assert r.status_code == 200
        assert await db_pool.fetchval("SELECT long_url FROM urls") == "https://example.com"

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


    async def test_short_link_ignores_a_forged_host_header(self, client):
        r = await client.post(
            "/shorten", data={"long_url": "https://example.com"}, headers={"host": "evil.example"}
        )
        assert "evil.example" not in r.text
        assert re.search(r'href="http://test/[A-Za-z0-9]{6}"', r.text)


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
        assert r.headers["location"] == "https://example.com"

    async def test_each_visit_increments_click_count(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        await client.get(f"/{code}")
        await client.get(f"/{code}")
        await client.get(f"/{code}")
        assert await _get_click_count(code) == 3

    async def test_unknown_code_returns_404(self, client):
        r = await client.get("/ZZZZZZ")  # a valid-looking code, so the query runs
        assert r.status_code == 404

    async def test_concurrent_visits_are_all_counted(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        # 50 visits at once, each from a different client so the rate limit doesn't kick in
        await asyncio.gather(*[
            client.get(f"/{code}", headers={"X-Forwarded-For": f"10.0.0.{i}"}) for i in range(50)
        ])
        assert await _get_click_count(code) == 50


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

    async def test_shows_the_click_count(self, client):
        await client.post("/shorten", data={"long_url": "https://example.com"})
        code = await _get_first_code()
        await client.get(f"/{code}")
        await client.get(f"/{code}")
        r = await client.get(f"/stats/{code}")
        assert re.search(r"Clicks:</b>\s*2\b", r.text)

    async def test_unknown_code_returns_404(self, client):
        r = await client.get("/stats/ZZZZZZ")
        assert r.status_code == 404


class TestNoPublicListing:
    async def test_there_is_no_page_listing_other_peoples_links(self, client):
        # A list of codes leads to /stats/<code>, which shows each destination.
        r = await client.get("/top")
        assert r.status_code == 404


# Rate limiting


class TestRateLimiting:
    """Per-IP rate limiting.

    The tests run with TRUSTED_PROXY_HOPS=1 (see conftest.py), so the client is
    the last X-Forwarded-For entry. limiter.reset() runs before every test.
    /shorten has the lowest limit (10/minute), so it's the one tested in
    a loop. The other routes only get header checks.
    """

    async def test_shorten_allows_requests_under_limit(self, client):
        """10 requests to /shorten from the same IP should all succeed."""
        for i in range(10):
            response = await client.post(
                "/shorten",
                data={"long_url": f"https://example{i}.com"},
                headers={"X-Forwarded-For": "192.0.2.10"},
            )
            assert response.status_code == 200, f"Request {i+1} unexpectedly failed"

    async def test_shorten_blocks_request_over_limit(self, client):
        """11th request to /shorten from the same IP should return 429."""
        for _ in range(10):
            await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": "192.0.2.11"},
            )
        response = await client.post(
            "/shorten",
            data={"long_url": "https://example.com"},
            headers={"X-Forwarded-For": "192.0.2.11"},
        )
        assert response.status_code == 429

    async def test_different_ips_have_independent_counters(self, client):
        """Requests from different IPs do not share a rate limit bucket."""
        # Exhaust limit for IP A
        for _ in range(10):
            await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": "192.0.2.20"},
            )
        # IP A is now limited
        blocked = await client.post(
            "/shorten",
            data={"long_url": "https://example.com"},
            headers={"X-Forwarded-For": "192.0.2.20"},
        )
        assert blocked.status_code == 429

        # IP B should be unaffected
        allowed = await client.post(
            "/shorten",
            data={"long_url": "https://example.com"},
            headers={"X-Forwarded-For": "192.0.2.21"},
        )
        assert allowed.status_code == 200

    async def test_rate_limit_headers_present(self, client):
        """Responses include X-RateLimit-Limit and X-RateLimit-Remaining.

        Requires headers_enabled=True in the Limiter constructor (see app.py).
        """
        response = await client.post(
            "/shorten",
            data={"long_url": "https://example.com"},
            headers={"X-Forwarded-For": "192.0.2.30"},
        )
        assert response.status_code == 200
        assert "x-ratelimit-limit" in response.headers
        assert "x-ratelimit-remaining" in response.headers

    async def test_a_spoofed_header_does_not_get_a_fresh_bucket(self, client):
        """The client can write anything left of the proxy's entry; it must not matter."""
        statuses = []
        for i in range(11):
            response = await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": f"198.51.100.{i}, 192.0.2.40"},
            )
            statuses.append(response.status_code)
        assert statuses[-1] == 429

    async def test_a_spoofed_first_header_line_does_not_get_a_fresh_bucket(self, client):
        """Some proxies add a second X-Forwarded-For line instead of extending the first."""
        statuses = []
        for i in range(11):
            response = await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers=[("X-Forwarded-For", f"198.51.100.{i}"), ("X-Forwarded-For", "192.0.2.50")],
            )
            statuses.append(response.status_code)
        assert statuses[-1] == 429

    async def test_a_proxy_entry_that_isnt_an_address_falls_back_to_the_socket(self, client):
        statuses = []
        for i in range(11):
            response = await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": f"not-an-ip-{i}"},
            )
            statuses.append(response.status_code)
        assert statuses[-1] == 429

    async def test_with_two_proxies_the_second_entry_from_the_right_is_the_client(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "TRUSTED_PROXY_HOPS", 2)
        # Spoofing the leftmost entry doesn't help: the client is still 192.0.2.60.
        spoofed = []
        for i in range(11):
            response = await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": f"198.51.100.{i}, 192.0.2.60, 10.0.0.1"},
            )
            spoofed.append(response.status_code)
        assert spoofed[-1] == 429
        # Different clients behind the same two proxies each get their own limit.
        others = []
        for i in range(11):
            response = await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": f"203.0.113.{i}, 10.0.0.1"},
            )
            others.append(response.status_code)
        assert set(others) == {200}

    async def test_without_a_proxy_the_header_is_ignored(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "TRUSTED_PROXY_HOPS", 0)
        statuses = []
        for i in range(11):
            response = await client.post(
                "/shorten",
                data={"long_url": "https://example.com"},
                headers={"X-Forwarded-For": f"198.51.100.{i}"},
            )
            statuses.append(response.status_code)
        assert statuses[-1] == 429
