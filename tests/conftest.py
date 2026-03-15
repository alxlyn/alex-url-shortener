"""
Pytest configuration and shared fixtures.

Requires a test PostgreSQL database. Set TEST_DATABASE_URL or ensure
postgresql://localhost/url_shortener_test exists locally.

CI: GitHub Actions spins up a postgres service container automatically.
"""
import os

import psycopg2
import pytest

# Must be set before importing app — prevents module-level init_db() from running
_test_db_url = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://localhost/url_shortener_test",
)
os.environ["DATABASE_URL"] = _test_db_url
os.environ["SKIP_DB_INIT"] = "1"

from app import app as flask_app, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_schema():
    """Create the urls table once for the entire test session."""
    init_db()


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe the urls table before each test to guarantee isolation."""
    conn = psycopg2.connect(_test_db_url, connect_timeout=10)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DELETE FROM urls")
    conn.close()
