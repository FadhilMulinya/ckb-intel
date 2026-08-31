from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional


def _safe_filename(address: str) -> str:
    if len(address) <= 150:
        return address
    h = hashlib.sha1(address.encode()).hexdigest()[:16]
    return f"{address[:100]}__LONG_{h}"


def load_address_list(path: Path) -> list[str]:
    out, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        addr = line.split("\t", 1)[0].strip()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--active-list", type=Path, required=True)
    p.add_argument("--fix", action="store_true", help="Write updated provenance JSON. Default: report only.")
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    addresses = load_address_list(args.active_list)
    conn = sqlite3.connect(str(db_path))

    n_checked = 0
    n_stale = 0
    n_no_provenance = 0

    for address in addresses:
        prov_path = args.data_dir / "provenance" / f"{_safe_filename(address)}.json"
        if not prov_path.exists():
            n_no_provenance += 1
            continue

        try:
            prov = json.loads(prov_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        window_start = prov.get("window_start_epoch")
        window_end = prov.get("window_end_epoch")
        old_n_tx = prov.get("n_tx_in_window")
        n_checked += 1

        query = "SELECT tx_hash, block_timestamp FROM address_tx_seen WHERE address = ?"
        params: list = [address]
        if window_start is not None and window_end is not None:
            query += " AND block_timestamp BETWEEN ? AND ?"
            params += [window_start, window_end]
        rows = conn.execute(query, params).fetchall()

        distinct_tx = {h for h, _ in rows}
        new_n_tx = len(distinct_tx)
        timestamps = sorted(t for _, t in rows if t is not None)

        if new_n_tx == old_n_tx:
            continue

        n_stale += 1
        print(f"{address}: n_tx_in_window {old_n_tx} -> {new_n_tx}")

        if args.fix:
            prov["n_tx_in_window"] = new_n_tx
            if timestamps:
                prov["deepest_block"] = {"block_timestamp_epoch": timestamps[0]}
                prov["shallowest_block"] = {"block_timestamp_epoch": timestamps[-1]}
            prov_path.write_text(json.dumps(prov), encoding="utf-8")

    conn.close()

    print(f"\n{n_checked} wallet(s) with provenance checked ({n_no_provenance} had no provenance file).")
    print(f"{n_stale} wallet(s) had a stale n_tx_in_window.")
    if n_stale and not args.fix:
        print("\nThis was a dry run. Re-run with --fix to update the provenance JSON files.")
    elif n_stale:
        print("\nProvenance updated. Re-run preprocess_ckb_wallets.py -- the staleness "
              "warning for these wallets should be gone, and tx_per_window_day / "
              "coverage figures will now reflect the corrected transaction counts.")
    else:
        print("\nNo stale provenance found -- nothing to fix.")


if __name__ == "__main__":
    main()
