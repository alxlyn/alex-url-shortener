# Alex URL Shortener

An async URL shortener - FastAPI + PostgreSQL over asyncpg, per-IP rate limiting that reads the client IP from `X-Forwarded-For`, and a CI pipeline that tests every route against a real database. Small enough to read in one sitting (~200 lines of app code), built so every design decision is defensible.

There is no live demo: the Cloud Run deployment has been retired. The image still builds in CI and runs anywhere Docker does.

## Why this is interesting

**Collision handling with no pre-check query.** Short codes are 6 chars from a 62-symbol alphabet (`secrets`-based, ~57B keyspace). Instead of SELECT-then-INSERT - which has a race window - `shorten()` just INSERTs and lets the PRIMARY KEY decide: on `asyncpg.UniqueViolationError` it regenerates and retries, up to 10 attempts. `scripts/validate_uniqueness.py` inserts 100,000 codes from the app's `generate_code` into a real Postgres (sequentially, psycopg2 + `ON CONFLICT DO NOTHING`) and fails unless every one is unique. It checks the generator against the PRIMARY KEY, not the app's async retry path or concurrent inserts; at 100k codes in a 57B keyspace the expected number of collisions is about 0.09.

**Connection pooling at the right layer.** A single `asyncpg` pool (min 2 / max 10) is created in the FastAPI lifespan and closed on shutdown; handlers `acquire()` a connection per request. asyncpg speaks the Postgres binary protocol natively async - no ORM, no thread-pool bridge, one pool for the process.

**Rate limiting built for a load balancer.** slowapi, keyed per client IP. The naive version breaks behind GCP's load balancer: every request arrives from the LB's IP, so all clients share one bucket. `_get_real_ip()` parses `X-Forwarded-For` instead, falling back to the socket address when unproxied. Limits are per-route (10/min on creates, 60/min on redirects, 30/min on pages) and responses carry `X-RateLimit-*` headers. Counter storage is pluggable: `memory://` by default, Redis via `REDIS_URL`. Rate limiting landed after the last Cloud Run deploy, so it never ran in production.

**Tests run against real Postgres, not mocks.** 38 pytest tests: 15 unit (code generation, URL normalization - including `javascript:`/`data:`/`file:` scheme rejection) and 23 integration tests that exercise every route against a live database. CI spins up a `postgres:16` service container, so constraints and SQL are tested for real. Function-scoped asyncpg pool fixtures keep the pool on the same event loop as each test; rate-limit tests assert the actual 429 on the 11th request and that different IPs get independent counters.

## Architecture

```
             ┌────────────────────────────────────────┐
             │           FastAPI on uvicorn           │
 client ───▶ │  slowapi middleware - per-IP limits,   │
             │  X-Forwarded-For aware                 │
             │                 │                      │
             │        async route handlers            │
             └───────┬───────────────────┬────────────┘
                     │ asyncpg pool      │ rate-limit
                     │ (min 2 / max 10)  │ counters
                     ▼                   ▼
                PostgreSQL          memory:// or Redis
```

Storage is one table - `urls(code PK, long_url, created_at, clicks)` - plus a composite index on `(clicks DESC, code)` so the top-10 query can read rows in index order instead of sorting. Schema lives in `init_db()` and `scripts/init_postgres.sql`.

Deployment was containerized for Cloud Run (uv-built image, `PORT`-driven uvicorn entrypoint) with Cloud SQL for PostgreSQL, deployed with Google Cloud Build (`gcloud builds submit`). The Cloud Run service is retired, but the Dockerfile is intact and CI still builds the image on every push.

## Endpoints

| Method | Path            | Description                          |
|--------|-----------------|--------------------------------------|
| GET    | `/`             | Homepage + create form               |
| POST   | `/shorten`      | Create a short link                  |
| GET    | `/{code}`       | 302 redirect + click increment       |
| GET    | `/stats/{code}` | Clicks and created-at for a link     |
| GET    | `/top`          | Top 10 links by clicks               |

## Run locally

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and a local PostgreSQL.

```bash
git clone https://github.com/alxlyn/alex-url-shortener.git
cd alex-url-shortener
uv sync
createdb url_shortener
uv run uvicorn app:app --reload
```

Open http://127.0.0.1:8000. Defaults work out of the box: `DATABASE_URL` falls back to `postgresql://localhost/url_shortener` and rate limiting uses in-memory storage (see `.env.example` for the Redis-backed setup).

## Run tests

```bash
createdb url_shortener_test
uv run pytest            # 38 tests; conftest defaults to postgresql://localhost/url_shortener_test
uv run ruff check .      # lint, same as CI
```

The 100k uniqueness check (uses psycopg2, not part of the app's dependencies):

```bash
uv pip install psycopg2-binary
DATABASE_URL=postgresql://localhost/url_shortener uv run python scripts/validate_uniqueness.py --count 100000
```

## Tech stack

Python 3.12 · FastAPI · asyncpg · PostgreSQL · slowapi (memory:// or Redis) · Jinja2 · uv · Docker · Google Cloud Run + Cloud SQL · GitHub Actions (ruff + pytest against a live Postgres container + Docker build)
