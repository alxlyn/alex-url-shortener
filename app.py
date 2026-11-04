"""URL shortener: FastAPI, asyncpg and PostgreSQL, with click counts and a stats page."""
import ipaddress
import os
import re
import secrets
import socket
import string
import unicodedata
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
CODE_PATTERN = re.compile(r"[A-Za-z0-9]{6}")
# Absolute paths, so the app also works when imported from another directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/url_shortener")
REDIS_URL = os.getenv("REDIS_URL", "memory://")
# Short links are built from this, never from the request's Host header, which the client controls.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


# How many proxies you control sit in front of the app (Cloud Run alone: 1).
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
if not 0 <= TRUSTED_PROXY_HOPS <= 5:
    raise RuntimeError("TRUSTED_PROXY_HOPS must be a number from 0 to 5")


def _get_real_ip(request: Request) -> str:
    """Client IP for rate limiting.

    Each proxy appends the address it saw to X-Forwarded-For, so behind N trusted
    proxies the client is the Nth entry from the right. Everything further left
    was written by the client and can't be trusted. With no proxy, use the socket.
    """
    if TRUSTED_PROXY_HOPS > 0:
        # A proxy can add its own X-Forwarded-For line instead of extending the
        # last one, so read every line, in order.
        forwarded = ",".join(request.headers.getlist("X-Forwarded-For"))
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= TRUSTED_PROXY_HOPS:
            try:
                return client_key(ipaddress.ip_address(hops[-TRUSTED_PROXY_HOPS]))
            except ValueError:
                pass  # not an address, so not something a proxy wrote: use the socket
    if not request.client:
        return "unknown"
    try:
        return client_key(ipaddress.ip_address(request.client.host))
    except ValueError:
        return request.client.host


def client_key(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """The rate-limit bucket for an address.

    IPv4 counts per address. IPv6 counts per /64, because one home or server usually
    gets a whole /64 and could otherwise rotate through addresses for fresh limits.
    An IPv4 address written as IPv6 (::ffff:1.2.3.4) counts as that IPv4 address.
    """
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


# Give up on Redis after 0.2 s. slowapi calls it synchronously, so a Redis that
# accepts connections but never answers would otherwise hang every request.
REDIS_OPTIONS = {"socket_timeout": 0.2, "socket_connect_timeout": 0.2}

# If Redis goes down, count in memory instead of failing every request.
# key_style="endpoint": one counter per route. slowapi's default counts each URL
# separately, so every short code would get its own fresh limit.
limiter = Limiter(
    key_func=_get_real_ip, storage_uri=REDIS_URL, headers_enabled=True, in_memory_fallback_enabled=True,
    key_style="endpoint", storage_options=REDIS_OPTIONS,
)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
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
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
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


@app.get("/stats/{code}", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def stats(request: Request, code: str):
    if not CODE_PATTERN.fullmatch(code):
        return templates.TemplateResponse(
            request, "stats.html", {"error": "Short link not found.", "code": code},
            status_code=404,
        )
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
    if not CODE_PATTERN.fullmatch(code):  # e.g. /favicon.ico: no database round trip
        return HTMLResponse("URL not found", status_code=404)
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
# "word://" at the start: the URL already names its scheme.
HAS_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
# What a host may contain once it's in ASCII form.
HOST_PATTERN = re.compile(r"[a-z0-9._-]+")


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

    if not HAS_SCHEME.match(url):
        if url.startswith("//") or SCHEME_PREFIX.match(url):
            return None
        url = "https://" + url
    if len(url) > MAX_URL_LENGTH:  # check again now that https:// may have been added
        return None

    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError for a port that isn't a number in range
    except ValueError:  # e.g. an unclosed "[", or characters that change under Unicode normalization
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if not host or "@" in parts.netloc:
        return None
    host = browser_host(host)
    if host is None or "." not in host or not HOST_PATTERN.fullmatch(host):
        return None
    own = browser_host(urlsplit(PUBLIC_BASE_URL).hostname or "") or ""
    if host == own or host.endswith("." + own):  # our host or one of its subdomains
        return None
    return url


def browser_host(host: str) -> str | None:
    """The host as a browser would read it, or None if it can't be one.

    NFKC first, the way browsers map hosts (full-width and squared letters become plain
    ones), then IDNA to ASCII. The trailing dot comes off after that, because the mapping
    can turn an odd dot into a plain one. IPv4 in any spelling (127.1, 0x7f.0.0.1,
    0177.0.0.1) becomes its dotted form, so it compares equal to the usual one.
    """
    try:
        host = unicodedata.normalize("NFKC", host).encode("idna").decode("ascii")
    except UnicodeError:
        return None
    host = host.lower().rstrip(".")
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        return host


def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def init_db() -> None:
    async with db_pool.acquire() as conn, conn.transaction():
        # Several instances can start at once on an empty database. The lock makes them
        # take turns; it's released when the transaction ends.
        await conn.execute("SELECT pg_advisory_xact_lock(4242)")
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
        # No index on clicks: nothing searches by it, every redirect updates it, and an
        # index on that column stops Postgres from doing cheap in-place (HOT) updates.
        await conn.execute("DROP INDEX IF EXISTS idx_urls_clicks_code")
