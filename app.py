import string
import secrets
import sqlite3
from flask import Flask, render_template, request, redirect

app = Flask(__name__)
DB_PATH = "database.db"
url_map = {}

@app.route("/")
def home():
    return render_template("index.html", short_url=None)

@app.route("/shorten", methods=["POST"])
def shorten():
    long_url = request.form.get("long_url", "").strip()
    code = generate_code()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO urls (code, long_url) VALUES (?, ?)",
            (code, long_url)
        )
    conn.commit()
    short_url = request.host_url + code
    return render_template("index.html", short_url=short_url, long_url=long_url)

@app.route("/<code>")
def redirect_to_url(code):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT long_url FROM urls WHERE code = ?",
            (code,)
        ).fetchone()

    long_url = row[0] if row else None
    if long_url:
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
if __name__ == "__main__":
    app.run(debug=True)
    init_db()
