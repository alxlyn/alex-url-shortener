"""
Validate collision-safe uniqueness by simulating bulk URL creation.

Usage:
    export DATABASE_URL=postgresql://localhost/url_shortener
    python scripts/validate_uniqueness.py --count 10000
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("SKIP_DB_INIT", "1")
from app import MAX_CODE_ATTEMPTS, generate_code


def run_validation(count: int) -> tuple[int, int]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required.")

    conn = psycopg2.connect(database_url, connect_timeout=10)

    retry_count = 0
    failed_creations = 0

    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE urls_validation (
                    code TEXT PRIMARY KEY,
                    long_url TEXT NOT NULL
                ) ON COMMIT DROP
                """
            )

            for i in range(count):
                created = False
                for _ in range(MAX_CODE_ATTEMPTS):
                    code = generate_code()
                    cur.execute(
                        """
                        INSERT INTO urls_validation (code, long_url)
                        VALUES (%s, %s)
                        ON CONFLICT (code) DO NOTHING
                        """,
                        (code, f"https://example.com/{i}"),
                    )
                    if cur.rowcount == 1:
                        created = True
                        break
                    retry_count += 1

                if not created:
                    failed_creations += 1

            cur.execute("SELECT COUNT(*) FROM urls_validation")
            unique_count = cur.fetchone()[0]

    conn.close()

    if unique_count != count or failed_creations > 0:
        raise SystemExit(
            f"Validation failed: requested={count}, unique_saved={unique_count}, "
            f"failed={failed_creations}, retries={retry_count}"
        )

    return unique_count, retry_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10000)
    args = parser.parse_args()

    unique_count, retry_count = run_validation(args.count)
    print(
        f"Validation passed: generated_and_saved={unique_count}, "
        f"collisions_retried={retry_count}"
    )


if __name__ == "__main__":
    main()
