"""
Flask URL Shortener

Features:
- Random short code generation
- Optional custom alias support (future-ready)
- PostgreSQL persistence
- Click tracking and created_at metadata
- Stats page per short link
- Top links leaderboard

Author: Alex Lian
"""
import string
import secrets
import os
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.middleware.proxy_fix import ProxyFix

# -------------------------
# Configuration
# -------------------------

MAX_CODE_ATTEMPTS = 10

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/url_shortener")


def get_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


# -------------------------
# Routes
# -------------------------
@app.route("/")
def home():
    return render_template("index.html", short_url=None, code=None)

@app.route("/shorten", methods=["POST"])
def shorten():
    long_url = normalize_url(request.form.get("long_url", ""))
    created_at = datetime.now(timezone.utc)
    if not long_url:
        return "Please enter a valid URL.", 400
    # Attempt to insert a randomly generated short code.
    # Retry if a collision occurs. 
    for _ in range(MAX_CODE_ATTEMPTS):
        code = generate_code()
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO urls (code, long_url, created_at, clicks) VALUES (%s, %s, %s, 0)",
                        (code, long_url, created_at),
                    )
            break
        except psycopg2.IntegrityError:
            continue
    else:
        return "Could not generate a unique short code. Try again.", 500       
    short_url = request.host_url + code
    return render_template("index.html", short_url=short_url, long_url=long_url, code=code)

@app.route("/<code>")
def redirect_to_url(code):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT long_url, clicks FROM urls WHERE code = %s",
                (code,),
            )
            row = cur.fetchone()

    long_url = row[0] if row else None
    if long_url:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE urls SET clicks = clicks + 1 WHERE code = %s", (code,))
        return redirect(long_url)
    return "URL not found", 404
@app.route("/stats/<code>")
def stats(code):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT long_url, clicks, created_at FROM urls WHERE code = %s",
                (code,),
            )
            row = cur.fetchone()

    if not row:
        return render_template("stats.html", error="Short link not found.", code=code), 404

    long_url, clicks, created_at = row
    return render_template(
        "stats.html",
        error=None,
        code=code,
        long_url=long_url,
        clicks=clicks,
        created_at=created_at
    )

@app.route("/top")
def top_links():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT code, long_url, clicks FROM urls ORDER BY clicks DESC, code ASC LIMIT 10"
            )
            rows = cur.fetchall()

    return render_template("top.html", links=rows)
# -------------------------
# Utility functions
# -------------------------

def normalize_url(raw: str) -> str | None:
    url = (raw or "").strip()

    if not url:
        return None

    lower = url.lower()
    if lower.startswith("javascript:") or lower.startswith("data:") or lower.startswith("file:"):
        return None

    if not (lower.startswith("http://") or lower.startswith("https://")):
        url = "https://" + url

    return url

def generate_code(length=6):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS urls (
                    code TEXT PRIMARY KEY,
                    long_url TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    clicks INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_urls_clicks_code
                ON urls (clicks DESC, code ASC)
                """
            )

# Ensure schema exists when app is loaded by Gunicorn/Cloud Run.
if os.getenv("SKIP_DB_INIT") != "1":
    init_db()

if __name__ == "__main__":
    app.run(debug=True)
    
