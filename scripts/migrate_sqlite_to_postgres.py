"""
Migrate existing URL data from SQLite into Postgres.

Usage:
    export DATABASE_URL=postgresql://localhost/url_shortener
    python scripts/migrate_sqlite_to_postgres.py --sqlite-path database.db
"""

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import psycopg2


def parse_created_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)

    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def ensure_postgres_schema(pg_conn) -> None:
    with pg_conn.cursor() as cur:
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


def load_sqlite_rows(sqlite_path: Path) -> list[tuple[str, str, str | None, int]]:
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='urls'"
        ).fetchall()
        if not tables:
            raise SystemExit("SQLite database does not contain `urls` table.")

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(urls)").fetchall()
        }

        select_parts = ["code", "long_url"]
        select_parts.append("created_at" if "created_at" in columns else "NULL AS created_at")
        select_parts.append("clicks" if "clicks" in columns else "0 AS clicks")
        query = f"SELECT {', '.join(select_parts)} FROM urls"

        rows = conn.execute(query).fetchall()
        return [(row[0], row[1], row[2], int(row[3] or 0)) for row in rows]
    finally:
        conn.close()


def migrate_rows(pg_conn, rows: list[tuple[str, str, str | None, int]]) -> int:
    inserted = 0
    with pg_conn.cursor() as cur:
        for code, long_url, created_at_raw, clicks in rows:
            created_at = parse_created_at(created_at_raw)
            cur.execute(
                """
                INSERT INTO urls (code, long_url, created_at, clicks)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE
                SET
                    long_url = EXCLUDED.long_url,
                    created_at = EXCLUDED.created_at,
                    clicks = EXCLUDED.clicks
                """,
                (code, long_url, created_at, clicks),
            )
            inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", default="database.db")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required.")

    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    rows = load_sqlite_rows(sqlite_path)

    pg_conn = psycopg2.connect(database_url, connect_timeout=10)
    try:
        with pg_conn:
            ensure_postgres_schema(pg_conn)
            copied = migrate_rows(pg_conn, rows)
    finally:
        pg_conn.close()

    print(f"Migration complete: copied={copied} rows from {sqlite_path}")


if __name__ == "__main__":
    main()
