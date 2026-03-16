"""
FastAPI URL Shortener

Features:
- Random short code generation
- PostgreSQL persistence via asyncpg
- Click tracking and created_at metadata
- Stats page per short link
- Top links leaderboard

Author: Alex Lian
"""
import os
import secrets
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# -------------------------
# Configuration
# -------------------------

MAX_CODE_ATTEMPTS = 10
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/url_shortener")

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


# -------------------------
# Routes
# -------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"short_url": None, "code": None}
    )


@app.post("/shorten", response_class=HTMLResponse)
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

    short_url = str(request.base_url) + code
    return templates.TemplateResponse(
        request, "index.html", {"short_url": short_url, "long_url": normalized, "code": code}
    )


@app.get("/top", response_class=HTMLResponse)
async def top_links(request: Request):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, long_url, clicks FROM urls ORDER BY clicks DESC, code ASC LIMIT 10"
        )
    return templates.TemplateResponse(request, "top.html", {"links": rows})


@app.get("/stats/{code}", response_class=HTMLResponse)
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
async def redirect_to_url(code: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT long_url FROM urls WHERE code = $1", code)
        if not row:
            return HTMLResponse("URL not found", status_code=404)
        await conn.execute("UPDATE urls SET clicks = clicks + 1 WHERE code = $1", code)
    return RedirectResponse(url=row["long_url"], status_code=302)


# -------------------------
# Utility functions
# -------------------------

def normalize_url(raw: str | None) -> str | None:
    url = (raw or "").strip()
    if not url:
        return None
    lower = url.lower()
    if lower.startswith(("javascript:", "data:", "file:")):
        return None
    if not (lower.startswith("http://") or lower.startswith("https://")):
        url = "https://" + url
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
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_urls_clicks_code
            ON urls (clicks DESC, code ASC)
            """
        )
