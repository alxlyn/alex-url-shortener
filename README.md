# Alex URL Shortener

A small URL shortener built with FastAPI, asyncpg and PostgreSQL. The app code is about 200 lines. It has per-IP rate limiting and a test suite that runs every route against a real Postgres database in CI.

It used to run on Google Cloud Run. That deployment is retired, so there's no live demo, but CI still builds the Docker image on every push.

## How it works

Short codes are 6 characters from a 62-character alphabet, generated with `secrets`, which gives about 57 billion possible codes. `shorten()` inserts the new code directly and lets the primary key reject a duplicate. On `asyncpg.UniqueViolationError` it generates another code and tries again, up to 10 times. I chose this over checking for the code first because a check followed by an insert leaves a window where two requests can pick the same code.

`scripts/validate_uniqueness.py` inserts 100,000 codes from the app's `generate_code` into Postgres and fails if any of them collide. It tests the generator against the primary key, not the app's retry path. At this size the expected number of collisions is about 0.09.

The app keeps one asyncpg pool (2 to 10 connections) for the whole process. It's created in the FastAPI lifespan and closed on shutdown, and each request borrows a connection from it. There's no ORM.

Rate limiting uses slowapi with a separate limit per route: 10 per minute for creating links, 60 for redirects and 30 for pages. Responses include the `X-RateLimit-*` headers. Counters live in memory by default, or in Redis if you set `REDIS_URL`. Behind Cloud Run every request arrives from the load balancer, so the limiter keys on the client IP from `X-Forwarded-For`. Rate limiting was added after the last Cloud Run deploy, so it never ran in production.

There is one table, `urls(code PK, long_url, created_at, clicks)`, with an index on `(clicks DESC, code)` so the top-10 page reads rows in index order. The schema is in `init_db()` and `scripts/init_postgres.sql`.

## Tests

There are 38 pytest tests. 15 are unit tests for code generation and URL normalization, including rejecting `javascript:`, `data:` and `file:` URLs. The other 23 call every route against a live database. CI starts a `postgres:16` service container and also runs ruff and a Docker build. The rate-limit tests check that the 11th create request in a minute gets a 429 and that different IPs get separate counters.

## Limitations

- The limiter uses the leftmost `X-Forwarded-For` entry, which the client can set. Sending a different value on every request gets a fresh rate-limit bucket each time. A real deployment should use the address the load balancer appends.
- No test forces a code collision or sends two inserts at the same time, so the retry path isn't covered by a test.

## Endpoints

| Method | Path            | Description                          |
|--------|-----------------|--------------------------------------|
| GET    | `/`             | Homepage and create form             |
| POST   | `/shorten`      | Create a short link                  |
| GET    | `/{code}`       | 302 redirect and click count         |
| GET    | `/stats/{code}` | Clicks and creation time for a link  |
| GET    | `/top`          | Top 10 links by clicks               |

## Run locally

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and a local PostgreSQL.

```bash
git clone https://github.com/alxlyn/alex-url-shortener.git
cd alex-url-shortener
uv sync
createdb url_shortener
uv run uvicorn app:app --reload
```

Then open http://127.0.0.1:8000. `DATABASE_URL` defaults to `postgresql://localhost/url_shortener`, and rate limiting uses in-memory storage unless you set `REDIS_URL` (see `.env.example`).

## Run tests

```bash
createdb url_shortener_test
uv run pytest            # 38 tests, using postgresql://localhost/url_shortener_test by default
uv run ruff check .      # lint, same as CI
```

The uniqueness check uses psycopg2, which isn't one of the app's dependencies:

```bash
uv pip install psycopg2-binary
DATABASE_URL=postgresql://localhost/url_shortener uv run python scripts/validate_uniqueness.py --count 100000
```

## Stack

Python 3.12, FastAPI, asyncpg, PostgreSQL, slowapi, Jinja2, uv, Docker, GitHub Actions. Previously deployed on Google Cloud Run.
