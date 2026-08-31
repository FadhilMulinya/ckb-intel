from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


try:
    import ckb_explorer_pull as crawler
except ImportError:
    print("Could not import ckb_explorer_pull.py -- it must be in the same directory.", file=sys.stderr)
    sys.exit(2)

try:
    import collect_target_wallets as ctw
except ImportError:
    print("Could not import collect_target_wallets.py -- it must be in the same directory.", file=sys.stderr)
    sys.exit(2)

try:
    import rebuild_edges_from_cache as rebuild_edges
except ImportError:
    print("Could not import rebuild_edges_from_cache.py -- it must be in the same directory.", file=sys.stderr)
    sys.exit(2)

try:
    import preprocess_ckb_wallets as prep
except ImportError:
    print("Could not import preprocess_ckb_wallets.py -- it must be in the same directory.", file=sys.stderr)
    sys.exit(2)


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT NOT NULL, fetched_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS raw_addresses (address TEXT PRIMARY KEY, lock_hash TEXT, raw_json TEXT NOT NULL, fetched_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS address_tx_seen (address TEXT NOT NULL, tx_hash TEXT NOT NULL, block_timestamp INTEGER, PRIMARY KEY (address, tx_hash));
CREATE TABLE IF NOT EXISTS edges (from_lock_hash TEXT NOT NULL, to_lock_hash TEXT NOT NULL, value_shannon REAL NOT NULL, capacity_bytes INTEGER, block_timestamp INTEGER, tx_hash TEXT NOT NULL, PRIMARY KEY (from_lock_hash, to_lock_hash, tx_hash));
CREATE TABLE IF NOT EXISTS dao_events (address TEXT NOT NULL, event_type TEXT, capacity REAL, block_timestamp INTEGER, tx_hash TEXT, raw_json TEXT, UNIQUE (address, tx_hash, event_type));
CREATE TABLE IF NOT EXISTS wallets (lock_hash TEXT PRIMARY KEY, address TEXT, lock_code_hash TEXT, lock_hash_type TEXT, tx_count INTEGER DEFAULT 0, first_seen INTEGER, last_seen INTEGER);
CREATE INDEX IF NOT EXISTS idx_edges_to_lock_hash ON edges(to_lock_hash);
CREATE INDEX IF NOT EXISTS idx_edges_from_lock_hash ON edges(from_lock_hash);
"""


def safe_collect_windowed_transactions(address: str, window_start_s: int, window_end_s: int,
                                        max_scanned: int = 50_000, safety_margin: int = 250,
                                        max_margin_triggers: int = 5) -> tuple[list[dict], bool]:
    
    collected: list[dict] = []
    direction: Optional[str] = None
    n_scanned = 0
    margin_remaining = 0
    margin_triggers = 0
    hit_scan_cap = False

    for tx_item in crawler.fetch_address_transactions(address):
        n_scanned += 1
        if n_scanned > max_scanned:
            hit_scan_cap = True
            break

        ts = ctw._tx_timestamp_s(tx_item)
        if ts is None:
            continue

        if direction is None and collected:
            prev_ts = ctw._tx_timestamp_s(collected[-1])
            if prev_ts is not None:
                direction = "newest_first" if ts < prev_ts else "oldest_first"

        past_boundary = (
            (direction == "newest_first" and ts < window_start_s) or
            (direction == "oldest_first" and ts > window_end_s)
        )

        if past_boundary:
            if margin_remaining <= 0:
                if margin_triggers >= max_margin_triggers:
                    break
                margin_triggers += 1
                margin_remaining = safety_margin
            margin_remaining -= 1
            if margin_remaining <= 0:
                break
            continue

        if direction == "oldest_first" and ts < window_start_s:
            continue

        if window_start_s <= ts <= window_end_s:
            collected.append(tx_item)
            margin_remaining = 0  

    return collected, hit_scan_cap


def _safe_filename(address: str) -> str:
    if len(address) <= 150:
        return address
    import hashlib
    h = hashlib.sha1(address.encode()).hexdigest()[:16]
    return f"{address[:100]}__LONG_{h}"


def resolve_and_store_address(conn: sqlite3.Connection, address: str) -> None:
    addr_detail = crawler.fetch_address_detail(address)
    lock_hash = None
    raw_json_str = "{}"
    if addr_detail:
        item = addr_detail.get("data")
        if isinstance(item, list):
            item = item[0] if item else None
        if item:
            attrs = item.get("attributes", {})
            lock_info = attrs.get("lock_script") or {}
            code_hash, hash_type, args = lock_info.get("code_hash"), lock_info.get("hash_type"), lock_info.get("args")
            if code_hash and hash_type and args is not None:
                lock_hash = ctw.ckb_script_hash(code_hash, hash_type, args)
            raw_json_str = json.dumps(addr_detail)
    conn.execute(
        "INSERT OR REPLACE INTO raw_addresses (address, lock_hash, raw_json, fetched_at) VALUES (?, ?, ?, ?)",
        (address, lock_hash, raw_json_str, int(time.time())),
    )
    conn.commit()


def collect_and_populate(conn: sqlite3.Connection, address: str, window_start_s: int, window_end_s: int,
                          max_tx_details: int, verbose: bool = True) -> dict:
    """Returns a dict of collection stats used to build the provenance record."""
    resolve_and_store_address(conn, address)

    tx_items, hit_scan_cap = safe_collect_windowed_transactions(address, window_start_s, window_end_s)
    tx_items.sort(key=lambda it: ctw._tx_timestamp_s(it) or 0)
    n_tx_in_window = len(tx_items)

    if verbose:
        print(f"  found {n_tx_in_window} transaction(s) in the last window"
              f"{' (hit scan safety cap -- see --max-scanned)' if hit_scan_cap else ''}")

    for it in tx_items:
        tx_hash = ctw._tx_hash_of(it)
        ts = ctw._tx_timestamp_s(it)
        if tx_hash and ts is not None:
            conn.execute(
                "INSERT OR REPLACE INTO address_tx_seen (address, tx_hash, block_timestamp) VALUES (?, ?, ?)",
                (address, tx_hash, ts),
            )
    conn.commit()

    if n_tx_in_window == 0:
        return {
            "n_tx_in_window": 0, "n_tx_detail_fetched": 0,
            "deepest_ts": None, "shallowest_ts": None, "n_dao_events": 0,
            "detail_sampled": False, "listing_truncated": hit_scan_cap,
        }

    to_detail = tx_items[:max_tx_details] if max_tx_details > 0 else tx_items
    detail_sampled = len(to_detail) < len(tx_items)
    if verbose:
        print(f"  fetching detail for {len(to_detail)}/{n_tx_in_window} transaction(s)"
              f"{' (sampled -- see --max-tx-details)' if detail_sampled else ''}...")

    for i, it in enumerate(to_detail):
        tx_hash = ctw._tx_hash_of(it)
        if not tx_hash:
            continue
        detail = crawler.fetch_transaction_detail(tx_hash)
        if not detail:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO raw_transactions (tx_hash, raw_json, fetched_at) VALUES (?, ?, ?)",
            (tx_hash, json.dumps(detail), int(time.time())),
        )
        for edge in rebuild_edges.resolve_transaction_to_edges_fixed(detail):
            conn.execute(
                "INSERT OR REPLACE INTO edges "
                "(from_lock_hash, to_lock_hash, value_shannon, capacity_bytes, block_timestamp, tx_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (edge["from_lock_hash"], edge["to_lock_hash"], edge["value_shannon"],
                 edge["capacity_bytes"], edge["block_timestamp"], edge["tx_hash"]),
            )
        if verbose and (i + 1) % 200 == 0:
            print(f"    {i + 1}/{len(to_detail)} detail(s) fetched...")
    conn.commit()

    n_dao = 0
    for event in crawler.fetch_dao_events(address):
        attrs = event.get("attributes", {})
        ts = rebuild_edges._ms_to_s(attrs.get("block_timestamp"))
        if ts is None or not (window_start_s <= ts <= window_end_s):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO dao_events (address, event_type, capacity, block_timestamp, tx_hash, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (address, attrs.get("dao_event_type") or attrs.get("event_type"),
             float(attrs.get("capacity")) if attrs.get("capacity") is not None else None,
             ts, attrs.get("transaction_hash") or attrs.get("tx_hash"), json.dumps(event)),
        )
        n_dao += 1
    conn.commit()
    if verbose and n_dao:
        print(f"  found {n_dao} DAO event(s) in window")

    timestamps = [ctw._tx_timestamp_s(it) for it in tx_items]
    timestamps = [t for t in timestamps if t is not None]

    return {
        "n_tx_in_window": n_tx_in_window,
        "n_tx_detail_fetched": len(to_detail),
        "deepest_ts": min(timestamps) if timestamps else None,
        "shallowest_ts": max(timestamps) if timestamps else None,
        "n_dao_events": n_dao,
        "detail_sampled": detail_sampled,
        "listing_truncated": hit_scan_cap,
    }


def write_provenance(prov_dir: Path, address: str, window_start_s: int, window_end_s: int,
                      lookback_days: int, stats: dict) -> None:
    prov = {
        "address": address, "status": "complete",
        "window_start_epoch": window_start_s, "window_end_epoch": window_end_s,
        "lookback_days": lookback_days,
        "max_tx_listed": 0, "max_tx_details": stats["n_tx_detail_fetched"],
        "deepest_block": {"block_timestamp_epoch": stats["deepest_ts"]} if stats["deepest_ts"] else None,
        "shallowest_block": {"block_timestamp_epoch": stats["shallowest_ts"]} if stats["shallowest_ts"] else None,
        "n_tx_in_window": stats["n_tx_in_window"],
        "n_tx_detail_fetched": stats["n_tx_detail_fetched"],
        "n_tx_detail_reused_from_cache": 0,
        "n_tx_detail_newly_fetched": stats["n_tx_detail_fetched"],
        "n_tx_detail_remaining": max(0, stats["n_tx_in_window"] - stats["n_tx_detail_fetched"]),
        "n_tx_detail_remaining_is_exact": True,
        "fetch_order": "sequential",
        "listing_truncated": stats["listing_truncated"],
        "detail_sampled": stats["detail_sampled"],
        "n_dao_events": stats["n_dao_events"],
    }
    (prov_dir / f"{_safe_filename(address)}.json").write_text(json.dumps(prov), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--address", required=True, help="CKB wallet address to classify")
    p.add_argument("--model-dir", type=Path, required=True, help="Directory with wallet_classifier.joblib")
    p.add_argument("--lookback-days", type=int, default=365, help="History window. Default: 365 (last 1 year)")
    p.add_argument("--max-tx-details", type=int, default=3000,
                   help="Cap on how many transactions get full detail fetched (1 API call each). Default: 3000")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="Reuse/extend an existing ckb_data_v2-style sqlite db here instead of a throwaway temp db "
                        "-- useful if you'll classify overlapping wallets repeatedly (caches raw_transactions).")
    p.add_argument("--out", type=Path, default=None, help="Append the result as a row to this CSV")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    verbose = not args.quiet

    import joblib
    bundle = joblib.load(args.model_dir / "wallet_classifier.joblib")

    window_end_s = int(time.time())
    window_start_s = window_end_s - args.lookback_days * 86400

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "provenance").mkdir()

        if args.data_dir:
            args.data_dir.mkdir(parents=True, exist_ok=True)
            db_path = args.data_dir / "ckb_explorer.sqlite"
        else:
            db_path = tmp_path / "ckb_explorer.sqlite"

        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA)

        if verbose:
            print(f"Collecting last {args.lookback_days} day(s) of history for {args.address}...")
        stats = collect_and_populate(conn, args.address, window_start_s, window_end_s,
                                      args.max_tx_details, verbose=verbose)
        conn.close()

        if stats["n_tx_in_window"] == 0:
            predicted_segment = bundle["dormant_rule"]["label"]
            confidence = 1.0
            if verbose:
                print(f"\nNo transactions in the last {args.lookback_days} day(s) -> {predicted_segment}")
        else:
            write_provenance(tmp_path / "provenance", args.address, window_start_s, window_end_s,
                              args.lookback_days, stats)
            df = prep.assemble_features([args.address], db_path, tmp_path)

            feature_cols = bundle["feature_cols"]
            missing = [c for c in feature_cols if c not in df.columns]
            if missing:
                raise SystemExit(f"Feature mismatch between model and pipeline -- missing columns: {missing}. "
                                  f"The model may have been trained on a different preprocess_ckb_wallets.py "
                                  f"version than the one in this directory.")

            X = df[feature_cols].values
            X_imputed = bundle["imputer"].transform(X)
            pred = bundle["model"].predict(X_imputed)
            probs = bundle["model"].predict_proba(X_imputed) if hasattr(bundle["model"], "predict_proba") else None
            predicted_segment = bundle["label_encoder"].inverse_transform(pred)[0]
            confidence = float(probs.max()) if probs is not None else None

            if verbose:
                row = df.iloc[0]
                print(f"\n  n_tx_in_window: {int(row['n_tx_in_window'])}")
                print(f"  tx_per_window_day: {row['tx_per_window_day']:.3f}")
                print(f"  sent_total_ckb: {row.get('sent_total_ckb', float('nan')):.2f}")
                print(f"  received_total_ckb: {row.get('received_total_ckb', float('nan')):.2f}")
                print(f"\n=> {args.address}\n   Predicted category: {predicted_segment}"
                      f"{f' (confidence {confidence:.1%})' if confidence is not None else ''}")

    if args.out:
        import csv
        write_header = not args.out.exists()
        with open(args.out, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["address", "predicted_segment", "confidence", "lookback_days",
                            "n_tx_in_window", "timestamp"])
            w.writerow([args.address, predicted_segment,
                        f"{confidence:.4f}" if confidence is not None else "",
                        args.lookback_days, stats["n_tx_in_window"], int(time.time())])
        if verbose:
            print(f"\nAppended result to {args.out}")

    print(predicted_segment)


if __name__ == "__main__":
    main()
