from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("audit_gaps")


def _ms_to_s(ms) -> Optional[int]:
    try:
        return int(ms) // 1000
    except (TypeError, ValueError):
        return None


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


def load_provenance_window(data_dir: Path, address: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    
    def _safe_filename(a: str) -> str:
        if len(a) <= 150:
            return a
        import hashlib
        h = hashlib.sha1(a.encode()).hexdigest()[:16]
        return f"{a[:100]}__LONG_{h}"

    p = data_dir / "provenance" / f"{_safe_filename(address)}.json"
    if not p.exists():
        return None, None, None
    try:
        prov = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None, None
    return prov.get("window_start_epoch"), prov.get("window_end_epoch"), prov.get("n_tx_in_window")


def scan_cache_for_addresses(conn: sqlite3.Connection, target_addresses: set[str]) -> dict[str, list[tuple[str, Optional[int]]]]:
    
    result: dict[str, list[tuple[str, Optional[int]]]] = defaultdict(list)
    n_tx = conn.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
    log.info("scanning %d cached transactions for %d target address(es)...", n_tx, len(target_addresses))

    start = time.time()
    cur = conn.execute("SELECT tx_hash, raw_json FROM raw_transactions")
    n_processed = 0
    for tx_hash_pk, raw_json in cur:
        n_processed += 1
        if n_processed % 50000 == 0:
            log.info("  %d/%d transactions scanned (%.0fs elapsed)", n_processed, n_tx, time.time() - start)
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        data = payload.get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        if not data:
            continue
        attrs = data.get("attributes", {})
        real_tx_hash = attrs.get("transaction_hash") or tx_hash_pk
        ts_s = _ms_to_s(attrs.get("block_timestamp"))
        cells = (attrs.get("display_inputs") or []) + (attrs.get("display_outputs") or [])

        seen_this_tx = set()
        for cell in cells:
            addr = cell.get("address_hash") or cell.get("address")
            if addr and addr in target_addresses and addr not in seen_this_tx:
                seen_this_tx.add(addr)
                result[addr].append((real_tx_hash, ts_s))

    log.info("scan complete in %.0fs", time.time() - start)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--active-list", type=Path, required=True)
    p.add_argument("--fix", action="store_true",
                   help="Apply fixes (INSERT/UPDATE address_tx_seen). Default: report only.")
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    addresses = load_address_list(args.active_list)
    conn = sqlite3.connect(str(db_path))

    cache_by_address = scan_cache_for_addresses(conn, set(addresses))

    n_single_tx_wallets = 0
    n_genuine_gaps = 0
    n_missing_rows_total = 0
    n_null_ts_total = 0
    fix_rows = []  

    for address in addresses:
        window_start, window_end, n_tx_in_window = load_provenance_window(args.data_dir, address)

        cache_events = cache_by_address.get(address, [])
        if window_start is not None and window_end is not None:
            cache_events = [(h, t) for h, t in cache_events if t is not None and window_start <= t <= window_end]
        cache_distinct = {h for h, _ in cache_events}

        current_rows = conn.execute(
            "SELECT tx_hash, block_timestamp FROM address_tx_seen WHERE address = ?", (address,)
        ).fetchall()
        current_distinct = {h for h, _ in current_rows}
        current_valid_ts = {h for h, t in current_rows if t is not None}

        missing_rows = cache_distinct - current_distinct
        null_ts_rows = current_distinct - current_valid_ts

        if (n_tx_in_window or 0) <= 1 and not missing_rows and not null_ts_rows:
            n_single_tx_wallets += 1
            continue

        if missing_rows or null_ts_rows:
            n_genuine_gaps += 1
            n_missing_rows_total += len(missing_rows)
            n_null_ts_total += len(null_ts_rows)
            log.info("%s: %d missing row(s), %d NULL-timestamp row(s) "
                     "(provenance n_tx_in_window=%s, cache-derived usable events=%d)",
                     address, len(missing_rows), len(null_ts_rows), n_tx_in_window, len(cache_distinct))

            if args.fix:
                for tx_hash, ts in cache_events:
                    if tx_hash in missing_rows or tx_hash in null_ts_rows:
                        fix_rows.append((address, tx_hash, ts))

    print(f"\n{len(addresses)} active wallets checked.")
    print(f"  {n_single_tx_wallets} wallet(s) genuinely have <=1 transaction -- no gap possible, not a bug.")
    print(f"  {n_genuine_gaps} wallet(s) have a real discrepancy between address_tx_seen and the cache:")
    print(f"    {n_missing_rows_total} missing row(s) total (transactions the cache has but address_tx_seen never recorded)")
    print(f"    {n_null_ts_total} NULL-timestamp row(s) total (recorded but timestamp was never filled in)")

    if not args.fix:
        if n_genuine_gaps:
            print(f"\nThis was a dry run. Re-run with --fix to write {len(fix_rows) if fix_rows else '(see above)'} "
                  f"corrected row(s) into address_tx_seen.")
        else:
            print("\nNo fixable gaps found -- the 169 wallets missing gap stats are almost certainly "
                  "just wallets with too few transactions in the window for a gap to be computable, "
                  "not a data-completeness problem.")
    else:
        for address, tx_hash, ts in fix_rows:
            conn.execute(
                "INSERT INTO address_tx_seen (address, tx_hash, block_timestamp) VALUES (?, ?, ?) "
                "ON CONFLICT(address, tx_hash) DO UPDATE SET block_timestamp = excluded.block_timestamp "
                "WHERE excluded.block_timestamp IS NOT NULL",
                (address, tx_hash, ts),
            )
        conn.commit()
        print(f"\nWrote/updated {len(fix_rows)} row(s) in address_tx_seen.")
        print("Re-run preprocess_ckb_wallets.py -- some of the 169 wallets missing gap stats "
              "may now have enough timing data to compute them.")

    conn.close()


if __name__ == "__main__":
    main()
