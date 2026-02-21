import string
import secrets
import sqlite3
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect

MAX_CODE_ATTEMPTS = 10

app = Flask(__name__)
DB_PATH = "database.db"

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

@app.route("/")
def home():
    return render_template("index.html", short_url=None, code=None)

@app.route("/shorten", methods=["POST"])
def shorten():
    long_url = normalize_url(request.form.get("long_url", ""))
    created_at = datetime.now(timezone.utc).isoformat()
    if not long_url:
        return "Please enter a valid URL.", 400
    for _ in range(MAX_CODE_ATTEMPTS):
        code = generate_code()
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO urls (code, long_url, created_at, clicks) VALUES (?, ?, ?, 0)",
                    (code, long_url, created_at)
                )
                conn.commit()
            break
        except sqlite3.IntegrityError:
            continue
    else:
        return "Could not generate a unique short code. Try again.", 500       
    short_url = request.host_url + code
    return render_template("index.html", short_url=short_url, long_url=long_url, code=code)

@app.route("/<code>")
def redirect_to_url(code):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT long_url, clicks FROM urls WHERE code = ?",
            (code,)
        ).fetchone()

    long_url = row[0] if row else None
    if long_url:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE urls SET clicks = clicks + 1 WHERE code = ?", (code,))
            conn.commit()
        return redirect(long_url)
    return "URL not found", 404

def generate_code(length=6):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                code TEXT PRIMARY KEY,
                long_url TEXT NOT NULL
            )
        """)
        conn.commit()
        # Add columns if they don't exist yet (simple migration)
        try:
            conn.execute("ALTER TABLE urls ADD COLUMN created_at TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE urls ADD COLUMN clicks INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

@app.route("/stats/<code>")
def stats(code):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT long_url, clicks, created_at FROM urls WHERE code = ?",
            (code,)
        ).fetchone()

    if not row:
        return render_template("stats.html", error="Short link not found.", code=code)

    long_url, clicks, created_at = row
    return render_template(
        "stats.html",
        error=None,
        code=code,
        long_url=long_url,
        clicks=clicks,
        created_at=created_at
    )

@app.route("/stats/<code>")
def link_stats(code):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT long_url, clicks, created_at FROM urls WHERE code = ?",
            (code,)
        ).fetchone()

    if not row:
        return render_template("stats.html", error="Short link not found.", code=code)

    long_url, clicks, created_at = row
    return render_template(
        "stats.html",
        error=None,
        code=code,
        long_url=long_url,
        clicks=clicks,
        created_at=created_at
    )
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
    
