# Alex URL Shortener

A production-ready URL shortener built in Python using FastAPI and PostgreSQL. Built to deepen understanding of async web architecture, database persistence, and request lifecycle management.

Deployed on GCP Cloud Run.

## Features

- Short code generation with collision-safe retry logic
- PostgreSQL persistence via asyncpg (async connection pool)
- Click tracking and created_at metadata
- Stats page per short link
- Top 10 leaderboard by click count
- Server-side URL validation and normalization
- 34 pytest integration tests with CI on GitHub Actions

## Tech Stack

- **FastAPI** — async Python web framework
- **asyncpg** — async PostgreSQL driver with connection pooling
- **uvicorn** — ASGI server
- **uv** — dependency management and lockfile
- **PostgreSQL** — persistent storage
- **Docker** — containerized for Cloud Run deployment
- **GitHub Actions** — CI pipeline (lint + test against live Postgres)

## Local Setup

```bash
git clone https://github.com/alxlyn/alex-url-shortener.git
cd alex-url-shortener

# Install dependencies (creates .venv automatically)
uv sync

# Create local Postgres database
createdb url_shortener

# Run the app
DATABASE_URL=postgresql://localhost/url_shortener uv run uvicorn app:app --reload
```

Visit: `http://127.0.0.1:8000`

## Running Tests

Requires a local Postgres database:

```bash
createdb url_shortener_test
TEST_DATABASE_URL=postgresql://localhost/url_shortener_test uv run pytest tests/ -v
```

## Uniqueness Validation (100k links)

Stress test the short code generator against a real database:

```bash
DATABASE_URL=postgresql://localhost/url_shortener python scripts/validate_uniqueness.py --count 100000
```

## Project Structure

```
app.py                    # FastAPI app, routes, asyncpg pool, utility functions
templates/                # Jinja2 HTML templates
static/                   # CSS
tests/
  conftest.py             # pytest fixtures (asyncpg pool, httpx client, DB cleanup)
  test_app.py             # 34 tests: unit + integration
scripts/
  validate_uniqueness.py  # Short code collision stress test
  init_postgres.sql       # Schema DDL
.github/workflows/ci.yml  # CI: lint (ruff) + pytest against Postgres service container
Dockerfile                # uvicorn on Cloud Run
pyproject.toml            # Dependencies + pytest config
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Homepage |
| POST | `/shorten` | Create a short link |
| GET | `/<code>` | Redirect to original URL |
| GET | `/stats/<code>` | Click stats for a link |
| GET | `/top` | Top 10 most clicked links |

## Design Decisions

- **asyncpg over psycopg2** — native async driver, no thread-pool overhead, better throughput for I/O-bound workloads
- **Retry-based collision handling** — uses PostgreSQL PRIMARY KEY constraint violations as the signal, no pre-check queries
- **Function-scoped DB fixtures in tests** — each test gets its own asyncpg pool so there are no asyncio event loop conflicts across tests
- **uv over pip** — reproducible lockfile, 10-100x faster installs, single source of truth in pyproject.toml

## Known Limitations

- No authentication / user accounts
- No rate limiting (planned)
- No custom aliases (intentionally out of scope)
