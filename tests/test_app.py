"""
Test suite for the URL shortener.

Unit tests: generate_code(), normalize_url() — no DB required.
Integration tests: all routes — require the test PostgreSQL database.
"""
import os

import psycopg2

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
# Integration Tests — require DB
# ─────────────────────────────────────────────


def _get_first_code() -> str:
    """Helper: fetch the first code inserted in the current test's clean slate."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM urls LIMIT 1")
        row = cur.fetchone()
    conn.close()
    assert row is not None, "Expected at least one row in urls table"
    return row[0]


def _get_click_count(code: str) -> int:
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)
    with conn.cursor() as cur:
        cur.execute("SELECT clicks FROM urls WHERE code = %s", (code,))
        row = cur.fetchone()
    conn.close()
    assert row is not None
    return row[0]


class TestHomeRoute:
    def test_returns_200(self, client):
        assert client.get("/").status_code == 200


class TestShortenRoute:
    def test_valid_url_returns_200(self, client):
        r = client.post("/shorten", data={"long_url": "https://example.com"})
        assert r.status_code == 200

    def test_response_contains_short_url(self, client):
        r = client.post("/shorten", data={"long_url": "https://example.com"})
        assert b"localhost" in r.data  # short_url rendered in template

    def test_bare_domain_accepted(self, client):
        r = client.post("/shorten", data={"long_url": "example.com"})
        assert r.status_code == 200

    def test_empty_url_returns_400(self, client):
        r = client.post("/shorten", data={"long_url": ""})
        assert r.status_code == 400

    def test_missing_url_field_returns_400(self, client):
        r = client.post("/shorten", data={})
        assert r.status_code == 400

    def test_javascript_url_returns_400(self, client):
        r = client.post("/shorten", data={"long_url": "javascript:alert(1)"})
        assert r.status_code == 400

    def test_data_url_returns_400(self, client):
        r = client.post("/shorten", data={"long_url": "data:text/html,<h1>xss</h1>"})
        assert r.status_code == 400

    def test_row_persisted_in_db(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM urls")
            count = cur.fetchone()[0]
        conn.close()
        assert count == 1


class TestRedirectRoute:
    def test_valid_code_returns_302(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        code = _get_first_code()
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302

    def test_redirect_location_matches_original_url(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        code = _get_first_code()
        r = client.get(f"/{code}", follow_redirects=False)
        assert "example.com" in r.headers["Location"]

    def test_each_visit_increments_click_count(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        code = _get_first_code()
        client.get(f"/{code}")
        client.get(f"/{code}")
        client.get(f"/{code}")
        assert _get_click_count(code) == 3

    def test_unknown_code_returns_404(self, client):
        r = client.get("/doesnotexist")
        assert r.status_code == 404


class TestStatsRoute:
    def test_valid_code_returns_200(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        code = _get_first_code()
        r = client.get(f"/stats/{code}")
        assert r.status_code == 200

    def test_response_contains_original_url(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        code = _get_first_code()
        r = client.get(f"/stats/{code}")
        assert b"example.com" in r.data

    def test_unknown_code_returns_404(self, client):
        r = client.get("/stats/doesnotexist")
        assert r.status_code == 404


class TestTopRoute:
    def test_empty_db_returns_200(self, client):
        assert client.get("/top").status_code == 200

    def test_shows_created_links(self, client):
        client.post("/shorten", data={"long_url": "https://example.com"})
        r = client.get("/top")
        assert r.status_code == 200
        assert b"example.com" in r.data

    def test_orders_by_clicks_descending(self, client):
        client.post("/shorten", data={"long_url": "https://first.com"})
        client.post("/shorten", data={"long_url": "https://second.com"})

        # Give second.com more clicks
        second_code = _get_first_code()  # after DELETE, first inserted = second (alphabetical last)
        conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM urls WHERE long_url = 'https://second.com'")
            second_code = cur.fetchone()[0]
            cur.execute(
                "UPDATE urls SET clicks = 5 WHERE code = %s", (second_code,)
            )
            conn.commit()
        conn.close()

        r = client.get("/top")
        body = r.data.decode()
        assert body.index("second.com") < body.index("first.com")
