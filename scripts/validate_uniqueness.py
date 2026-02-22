"""
Validate collision-safe uniqueness by simulating bulk URL creation.

Usage:
    python scripts/validate_uniqueness.py --count 10000
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import MAX_CODE_ATTEMPTS, generate_code


def run_validation(count: int) -> tuple[int, int]:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE urls (
            code TEXT PRIMARY KEY,
            long_url TEXT NOT NULL
        )
        """
    )

    retry_count = 0
    failed_creations = 0

    for i in range(count):
        created = False
        for _ in range(MAX_CODE_ATTEMPTS):
            code = generate_code()
            try:
                conn.execute(
                    "INSERT INTO urls (code, long_url) VALUES (?, ?)",
                    (code, f"https://example.com/{i}"),
                )
                created = True
                break
            except sqlite3.IntegrityError:
                retry_count += 1

        if not created:
            failed_creations += 1

    unique_count = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
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
