"""Install the normalized CKB schema and rebuild it from cached raw details."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from wallet_intelligence.normalization import rebuild_from_raw_cache


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"database not found: {args.db}")
    with sqlite3.connect(args.db) as conn:
        result = rebuild_from_raw_cache(conn)
    print(f"Normalized {result['parsed']} cached transaction(s); {result['failed']} failed; "
          f"{result['newly_resolved']} input(s) resolved from cached previous outputs.")


if __name__ == "__main__":
    main()
