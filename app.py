"""URL shortener: FastAPI, asyncpg and PostgreSQL, with click counts, a stats page and a top-10 page."""
import os
import re
import secrets
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

import asyncpg
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# -------------------------
# Configuration
# -------------------------

MAX_CODE_ATTEMPTS = 10
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/url_shortener")
REDIS_URL = os.getenv("REDIS_URL", "memory://")
# Short links are built from this, never from the request's Host header, which the client controls.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _get_real_ip(request: Request) -> str:
    """Client IP for rate limiting.

    Behind Cloud Run every request comes from the load balancer, so read
    X-Forwarded-For. This takes the leftmost entry, which the client can set
    (see Limitations in the README). Without the header, use the socket address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    if request.client:
        return request.client.host
    return "unknown"


limiter = Limiter(key_func=_get_real_ip, storage_uri=REDIS_URL, headers_enabled=True)

templates = Jinja2Templates(directory="templates")
db_pool: asyncpg.Pool | None = None


# -------------------------
# Lifespan (startup / shutdown)
# -------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    if os.getenv("SKIP_DB_INIT") != "1":
        await init_db()
    yield
    await db_pool.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# -------------------------
# Routes
# -------------------------

@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def home(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"short_url": None, "code": None}
    )


@app.post("/shorten", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def shorten(request: Request, long_url: str = Form(default="")):
    normalized = normalize_url(long_url)
    if not normalized:
        return HTMLResponse("Please enter a valid URL.", status_code=400)

    created_at = datetime.now(timezone.utc)
    code = None

    for _ in range(MAX_CODE_ATTEMPTS):
        candidate = generate_code()
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO urls (code, long_url, created_at, clicks) VALUES ($1, $2, $3, 0)",
                    candidate, normalized, created_at,
                )
            code = candidate
            break
        except asyncpg.UniqueViolationError:
            continue

    if code is None:
        return HTMLResponse("Could not generate a unique short code. Try again.", status_code=500)

    short_url = f"{PUBLIC_BASE_URL}/{code}"
    return templates.TemplateResponse(
        request, "index.html", {"short_url": short_url, "long_url": normalized, "code": code}
    )


@app.get("/top", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def top_links(request: Request):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, clicks FROM urls ORDER BY clicks DESC, code ASC LIMIT 10"
        )
    return templates.TemplateResponse(request, "top.html", {"links": rows})


@app.get("/stats/{code}", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def stats(request: Request, code: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT long_url, clicks, created_at FROM urls WHERE code = $1", code
        )
    if not row:
        return templates.TemplateResponse(
            request, "stats.html", {"error": "Short link not found.", "code": code},
            status_code=404,
        )
    return templates.TemplateResponse(
        request, "stats.html",
        {
            "error": None,
            "code": code,
            "long_url": row["long_url"],
            "clicks": row["clicks"],
            "created_at": row["created_at"],
        },
    )


@app.get("/{code}")
@limiter.limit("60/minute")
async def redirect_to_url(request: Request, code: str):
    # One statement: count the click and read the destination in a single round trip.
    async with db_pool.acquire() as conn:
        long_url = await conn.fetchval(
            "UPDATE urls SET clicks = clicks + 1 WHERE code = $1 RETURNING long_url", code
        )
    if long_url is None:
        return HTMLResponse("URL not found", status_code=404)
    return RedirectResponse(url=long_url, status_code=302)


# -------------------------
# Utility functions
# -------------------------

MAX_URL_LENGTH = 2048
# "word:" at the start that isn't a port number, e.g. "javascript:" or "mailto:".
SCHEME_PREFIX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)")


def normalize_url(raw: str | None) -> str | None:
    """Return a safe http(s) URL, or None if the input can't be one.

    An allowlist: only http and https, a real host name, no user info, nothing
    that points back at the shortener, and a length cap.
    """
    url = (raw or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        return None
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return None

    if "://" not in url:
        if url.startswith("//") or SCHEME_PREFIX.match(url):
            return None
        url = "https://" + url

    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = parts.hostname
    if not host or "." not in host or "@" in parts.netloc:
        return None
    try:
        parts.port  # raises ValueError for a port that isn't a number in range
    except ValueError:
        return None
    if host == urlsplit(PUBLIC_BASE_URL).hostname:
        return None
    return url


def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def init_db() -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS urls (
                code       TEXT PRIMARY KEY,
                long_url   TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                clicks     INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # No index on clicks: every redirect updates clicks, and an index on that column
        # stops Postgres from doing cheap in-place (HOT) updates. Sorting a small table for
        # the top-10 page is cheaper than rewriting the index on every click.
        await conn.execute("DROP INDEX IF EXISTS idx_urls_clicks_code")
