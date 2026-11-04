# Alex URL Shortener

A URL shortener on FastAPI, asyncpg and PostgreSQL: about 320 lines of app code, per-route rate limiting, and 100 tests in CI.

I wrote the first version in February 2026 with AI help: Flask and SQLite on Google Cloud Run, then Postgres. In March I rebuilt it in FastAPI and asyncpg. This version has never been deployed, so there's no live demo, but CI builds the Docker image on every push.

## How it works

Short codes are 6 characters from a-z, A-Z and 0-9, picked with `secrets`, so there are about 57 billion of them. `shorten()` just inserts the new code and lets the primary key reject a duplicate. If asyncpg raises `UniqueViolationError`, it makes a new code and tries again, up to 10 times. I did it this way instead of checking first and then inserting, because with check-then-insert two requests can both see a code as free and the second one fails with a 500.

A redirect is one query: `UPDATE urls SET clicks = clicks + 1 WHERE code = $1 RETURNING long_url`. There's no index on `clicks`. Every redirect changes that column, and an index on a column that changes all the time stops Postgres from doing HOT (in-place) updates. A path that can't be a code, like `/favicon.ico`, gets a 404 without touching the database.

`normalize_url` only lets through http and https URLs with a host name, of at most 2,048 characters, counting the `https://` it adds when a link has no scheme. It rejects things like `javascript:`, `//evil.com`, `https://paypal.com@evil.com` and links back to the shortener itself. Links back to the shortener needed three follow-up fixes, because a browser reads `sho.rt.` and the same name in full-width letters as `sho.rt`, and `127.1` as `127.0.0.1`. So before comparing, the host is normalized roughly the way a browser does it: NFKC, then IDNA, then the trailing dot comes off, then IPv4 gets its normal dotted form.

Rate limiting uses slowapi: 10 a minute for creating links, 60 for redirects and 30 for pages. Each route has one counter per client, so trying different short codes doesn't get around the limit. Counters live in memory by default, or in Redis if you set `REDIS_URL`. If Redis refuses connections, the limiter falls back to memory instead of failing requests (checked by hand; there's no test for it yet). A Redis that accepts connections but never answers times out after 0.2 seconds, and a test checks that. Behind proxies you set `TRUSTED_PROXY_HOPS`. Each proxy appends the address it saw to `X-Forwarded-For`, so the client is that many entries from the right, and anything further left is ignored because the client can write whatever it wants there. uvicorn runs with `--no-proxy-headers`, since otherwise it rewrites the client address from that same header (for connections from `--forwarded-allow-ips`, 127.0.0.1 by default) before the app sees it. IPv6 clients count per /64, because one home or server usually gets a whole /64. An IPv4 address written as IPv6 (`::ffff:1.2.3.4`) counts as the IPv4 one. POST bodies over 8 KB get a 413 before anything reads them, and a POST with no length gets a 411.

There's one table, `urls(code PK, long_url, created_at, clicks)`. `init_db()` creates it under a Postgres advisory lock, so several instances starting at once on an empty database take turns. Short links are built from `PUBLIC_BASE_URL`, never from the request's Host header. The app keeps one asyncpg pool (2 to 10 connections) for the whole process, created in the FastAPI lifespan, and there's no ORM.

## Tests

100 pytest tests. 45 of them run against a real Postgres; the rest are mostly URL-check and code-generator cases. CI starts a `postgres:16` container and runs ruff. It also builds the Docker image and checks that the app loads inside it, and `.dockerignore` only lets in the files the image needs. The main ones:

- a forced collision: `generate_code` is swapped for a fake that repeats a code, and the test checks that the retry picks a new code and the existing link isn't touched, also with two requests at once
- the URL check, as a table of inputs that have to be rejected or accepted, including a few that crashed an earlier version of the check
- 50 concurrent visits all getting counted
- the rate limiter: the 11th create in a minute gets a 429, and a fake `X-Forwarded-For` (on the same line, on a second header line, or behind two proxies) doesn't get a fresh limit
- four instances creating the schema at the same time
- a fake Redis that accepts connections and never answers, to check that the client gives up

62 of the 100 tests, and the fixes they cover, came from two AI code reviews in November. They found bugs like short links built from the Host header and a rate limit you could dodge with a fake header or by trying different codes. The reviews gave step-by-step fixes and tests, and I made each change by hand, one commit at a time.

## Limitations

- The tests need Postgres even for the pure functions, because a shared fixture empties the table before every test.
- Anyone can create links. There are no accounts and no way to delete one.
- Anyone who has a code can see where it goes on its stats page.
- IP addresses like `10.0.0.1` are accepted as destinations. The app never fetches a URL, so they're only a redirect target, not a way into the server's network.
- The rate limit is only as good as `TRUSTED_PROXY_HOPS`. Set too high, honest clients behind one proxy share a bucket and a faked header works again; set too low, everyone shares the proxy's bucket.

## Endpoints

| Method | Path            | Description                           |
|--------|-----------------|---------------------------------------|
| GET    | `/`             | Homepage and create form              |
| POST   | `/shorten`      | Create a short link                   |
| GET    | `/{code}`       | 302 redirect and click count          |
| GET    | `/stats/{code}` | Destination, clicks and creation time |

## Run locally

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and a local PostgreSQL.

```bash
git clone https://github.com/alxlyn/alex-url-shortener.git
cd alex-url-shortener
uv sync
createdb url_shortener
uv run uvicorn app:app --reload --no-proxy-headers
```

Then open http://127.0.0.1:8000. `DATABASE_URL` defaults to `postgresql://localhost/url_shortener`, `PUBLIC_BASE_URL` to `http://127.0.0.1:8000`, and rate limiting uses in-memory storage unless you set `REDIS_URL` (see `.env.example`).

## Run tests

```bash
createdb url_shortener_test
uv run pytest            # 100 tests, using postgresql://localhost/url_shortener_test by default
uv run ruff check .      # lint, same as CI
```

## Stack

Python 3.12, FastAPI, asyncpg, PostgreSQL, slowapi, Jinja2, uv, Docker, GitHub Actions.
