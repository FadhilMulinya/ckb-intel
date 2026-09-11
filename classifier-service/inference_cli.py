"""CLI for the CKB-native V2 wallet behaviour service."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2_service import AnalysisError, V2WalletService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="mainnet CKB bech32 address")
    parser.add_argument("--db", type=Path, default=None, help="frozen V2 SQLite database")
    parser.add_argument("--live", action="store_true", help="request live mode (currently explicit unsupported status)")
    args = parser.parse_args()
    try:
        profile = V2WalletService(args.db).analyze(args.address, live=args.live)
    except AnalysisError as exc:
        print(json.dumps({"status": exc.status, "message": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(profile, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
