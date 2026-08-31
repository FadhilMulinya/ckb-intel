from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

try:
    import ckb_explorer_pull as crawler
except ImportError:
    print(
        "Could not import ckb_explorer_pull.py -- it must be in the same "
        "directory as this script (or on PYTHONPATH). Reuses its proven "
        "fetch_* functions rather than reimplementing HTTP/retry handling.",
        file=sys.stderr,
    )
    sys.exit(2)


def load_address_list(path: Path) -> list[str]:
    addresses, seen = [], set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        addr = line.split("\t", 1)[0].strip()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        addresses.append(addr)
    return addresses


_CKB_HASH_TYPE_BYTE = {"data": 0, "type": 1, "data1": 2, "data2": 4}


def ckb_script_hash(code_hash_hex: str, hash_type: str, args_hex: str) -> Optional[str]:
    try:
        code_hash = bytes.fromhex(code_hash_hex[2:] if code_hash_hex.startswith("0x") else code_hash_hex)
        args = bytes.fromhex(args_hex[2:] if args_hex.startswith("0x") else args_hex)
        hash_type_byte = _CKB_HASH_TYPE_BYTE[hash_type]
    except (AttributeError, ValueError, KeyError):
        return None

    args_encoded = len(args).to_bytes(4, "little") + args
    header_len = 4 + 4 * 3
    off0 = header_len
    off1 = off0 + len(code_hash)
    off2 = off1 + 1
    total_size = off2 + len(args_encoded)

    buf = bytearray()
    buf += total_size.to_bytes(4, "little")
    buf += off0.to_bytes(4, "little")
    buf += off1.to_bytes(4, "little")
    buf += off2.to_bytes(4, "little")
    buf += code_hash
    buf += bytes([hash_type_byte])
    buf += args_encoded

    digest = hashlib.blake2b(bytes(buf), digest_size=32, person=b"ckb-default-hash").digest()
    return "0x" + digest.hex()


def _ms_to_s(ms) -> Optional[int]:
    try:
        return int(ms) // 1000
    except (TypeError, ValueError):
        return None


def _tx_timestamp_s(tx_item: dict) -> Optional[int]:
    attrs = tx_item.get("attributes", {})
    return _ms_to_s(attrs.get("block_timestamp"))


def _tx_block_number(tx_item: dict) -> Optional[int]:
    attrs = tx_item.get("attributes", {})
    bn = attrs.get("block_number")
    try:
        return int(bn) if bn is not None else None
    except (TypeError, ValueError):
        return None


def _safe_filename(address: str) -> str:
    if len(address) <= 150:
        return address
    h = hashlib.sha1(address.encode()).hexdigest()[:16]
    return f"{address[:100]}__LONG_{h}"


def provenance_path(data_dir: Path, address: str) -> Path:
    return data_dir / "provenance" / f"{_safe_filename(address)}.json"


def load_provenance(data_dir: Path, address: str) -> Optional[dict]:
    p = provenance_path(data_dir, address)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _cap_increased(new_cap: int, old_cap) -> bool:
    if old_cap is None:
        return True
    new_unlimited = new_cap <= 0
    old_unlimited = old_cap <= 0
    if old_unlimited:
        return False  
    if new_unlimited:
        return True   
    return new_cap > old_cap


def provenance_is_still_valid(prov: dict, window_start_s: int, window_end_s: int,
                               max_tx_listed: int, max_tx_details: int) -> bool:
    if prov.get("status") != "complete":
        return False
    if prov.get("window_start_epoch") != window_start_s or prov.get("window_end_epoch") != window_end_s:
        return False
    if not prov.get("listing_truncated") and not prov.get("detail_sampled"):
        return True  

    old_max_listed = prov.get("max_tx_listed")
    old_max_details = prov.get("max_tx_details")
    if prov.get("listing_truncated") and _cap_increased(max_tx_listed, old_max_listed):
        return False
    if prov.get("detail_sampled") and _cap_increased(max_tx_details, old_max_details):
        return False
    return True


def write_provenance(data_dir: Path, address: str, window_start_s: int, window_end_s: int,
                      lookback_days: int, max_tx_listed: int, max_tx_details: int,
                      tx_items: list[dict], summary: dict) -> None:
    path = provenance_path(data_dir, address)
    path.parent.mkdir(parents=True, exist_ok=True)

    deepest = shallowest = None
    if tx_items:
        oldest_item, newest_item = tx_items[0], tx_items[-1]
        deepest = {
            "block_number": _tx_block_number(oldest_item),
            "block_timestamp_epoch": _tx_timestamp_s(oldest_item),
            "block_timestamp_utc": dt.datetime.fromtimestamp(
                _tx_timestamp_s(oldest_item), tz=dt.timezone.utc).isoformat()
                if _tx_timestamp_s(oldest_item) else None,
            "tx_hash": oldest_item.get("attributes", {}).get("transaction_hash") or oldest_item.get("id"),
        }
        shallowest = {
            "block_number": _tx_block_number(newest_item),
            "block_timestamp_epoch": _tx_timestamp_s(newest_item),
            "block_timestamp_utc": dt.datetime.fromtimestamp(
                _tx_timestamp_s(newest_item), tz=dt.timezone.utc).isoformat()
                if _tx_timestamp_s(newest_item) else None,
            "tx_hash": newest_item.get("attributes", {}).get("transaction_hash") or newest_item.get("id"),
        }

    record = {
        "address": address,
        "status": "complete",
        "collected_at_utc": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "window_start_epoch": window_start_s,
        "window_end_epoch": window_end_s,
        "window_start_utc": dt.datetime.fromtimestamp(window_start_s, tz=dt.timezone.utc).isoformat(),
        "window_end_utc": dt.datetime.fromtimestamp(window_end_s, tz=dt.timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "max_tx_listed": max_tx_listed,
        "max_tx_details": max_tx_details,
        "deepest_block": deepest,     
        "shallowest_block": shallowest,  
        "n_tx_in_window": summary["n_tx_in_window"],
        "n_tx_detail_fetched": summary["n_tx_detail_fetched"],
        "n_tx_detail_reused_from_cache": summary.get("n_tx_detail_reused_from_cache", 0),
        "n_tx_detail_newly_fetched": summary.get("n_tx_detail_newly_fetched", summary["n_tx_detail_fetched"]),
        "n_tx_detail_remaining": summary.get("n_tx_detail_remaining", 0),
        "n_tx_detail_remaining_is_exact": summary.get("n_tx_detail_remaining_is_exact", True),
        "fetch_order": summary.get("fetch_order", "sequential"),
        "listing_truncated": summary["listing_truncated"],
        "detail_sampled": summary["detail_sampled"],
        "n_dao_events": summary["n_dao_events"],
    }
    path.write_text(json.dumps(record, indent=2))


def clean_slate(conn: sqlite3.Connection, address: str) -> None:
    conn.execute("DELETE FROM address_tx_seen WHERE address = ?", (address,))
    conn.execute("DELETE FROM edges WHERE from_lock_hash = ? OR to_lock_hash = ?", (address, address))
    conn.execute("DELETE FROM dao_events WHERE address = ?", (address,))
    conn.execute("DELETE FROM raw_addresses WHERE address = ?", (address,))


def collect_windowed_transactions(address: str, window_start_s: int, window_end_s: int,
                                   max_tx_listed: int) -> tuple[list[dict], bool]:
    collected: list[dict] = []
    direction: Optional[str] = None  
    truncated = False
    unlimited = max_tx_listed <= 0

    for tx_item in crawler.fetch_address_transactions(address):
        ts = _tx_timestamp_s(tx_item)
        if ts is None:
            continue

        if direction is None and collected:
            prev_ts = _tx_timestamp_s(collected[-1])
            if prev_ts is not None:
                direction = "newest_first" if ts < prev_ts else "oldest_first"

        if direction == "newest_first" and ts < window_start_s:
            break  
        if direction == "oldest_first" and ts > window_end_s:
            break  
        if direction == "oldest_first" and ts < window_start_s:
            continue  

        if window_start_s <= ts <= window_end_s:
            collected.append(tx_item)
            if not unlimited and len(collected) >= max_tx_listed:
                truncated = True
                break

    return collected, truncated


def sample_evenly(items: list, k: int) -> list:
    if len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def _tx_hash_of(item: dict) -> Optional[str]:
    attrs = item.get("attributes", {})
    return attrs.get("transaction_hash") or item.get("id")


def sample_evenly_incremental(items: list, k: int, already_cached: set) -> list:
    already_present = [it for it in items if _tx_hash_of(it) in already_cached]
    if len(already_present) >= k:
        return already_present
    remaining_needed = k - len(already_present)
    remaining_pool = [it for it in items if _tx_hash_of(it) not in already_cached]
    additional = sample_evenly(remaining_pool, remaining_needed)
    combined = already_present + additional
    combined.sort(key=lambda it: _tx_timestamp_s(it) or 0)
    return combined


def sample_sequential(items_ascending: list, k: int, already_cached: set) -> list:
    items_newest_first = list(reversed(items_ascending))
    already_present = [it for it in items_newest_first if _tx_hash_of(it) in already_cached]
    if len(already_present) >= k:
        result = already_present[:k]
    else:
        remaining_needed = k - len(already_present)
        remaining_pool = [it for it in items_newest_first if _tx_hash_of(it) not in already_cached]
        additional = remaining_pool[:remaining_needed]  # sequential, not evenly spaced
        result = already_present + additional
    result.sort(key=lambda it: _tx_timestamp_s(it) or 0)
    return result


def fetch_detail(tx_hash: str) -> tuple[str, Optional[dict]]:
    """Network-only, no DB access -- safe to run concurrently across threads."""
    return tx_hash, crawler.fetch_transaction_detail(tx_hash)


def store_detail(store, tx_hash: str, detail: Optional[dict]) -> None:
    if not detail:
        return
    store.save_transaction(tx_hash, detail)  
    for edge in crawler.resolve_transaction_to_edges(detail):
        store.save_edge(
            edge["from_lock_hash"], edge["to_lock_hash"], edge["value_shannon"],
            edge.get("capacity_bytes"), edge.get("block_timestamp"), edge["tx_hash"],
        )


def pull_address_history(store, address: str, window_start_s: int, window_end_s: int,
                          max_tx_listed: int, max_tx_details: int, workers: int,
                          pull_dao: bool, needs_full_repull: bool = True,
                          fetch_order: str = "sequential") -> tuple[dict, list[dict]]:
    conn = store.conn

    if needs_full_repull:
        clean_slate(conn, address)

    if needs_full_repull:
        addr_detail = crawler.fetch_address_detail(address)
        lock_hash = None
        if addr_detail:
            item = addr_detail.get("data")
            if isinstance(item, list):
                item = item[0] if item else None
            if item:
                attrs = item.get("attributes", {})
                lock_info = attrs.get("lock_script") or {}
                code_hash, hash_type, args = lock_info.get("code_hash"), lock_info.get("hash_type"), lock_info.get("args")
                if code_hash and hash_type and args is not None:
                    lock_hash = ckb_script_hash(code_hash, hash_type, args)
                store.save_address_raw(address, lock_hash, addr_detail)  # handles fetched_at
                if lock_hash:
                    conn.execute("""
                        INSERT INTO wallets (lock_hash, address, lock_code_hash, lock_hash_type, tx_count, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, 0, NULL, NULL)
                        ON CONFLICT(lock_hash) DO UPDATE SET
                            address = excluded.address,
                            lock_code_hash = COALESCE(wallets.lock_code_hash, excluded.lock_code_hash),
                            lock_hash_type = COALESCE(wallets.lock_hash_type, excluded.lock_hash_type)
                    """, (lock_hash, address, code_hash, hash_type))

    
    tx_items, listing_truncated = collect_windowed_transactions(
        address, window_start_s, window_end_s, max_tx_listed)
    tx_items.sort(key=lambda it: _tx_timestamp_s(it) or 0)

    for it in tx_items:
        tx_hash = _tx_hash_of(it)
        ts = _tx_timestamp_s(it)
        if tx_hash and ts is not None:
            store.mark_address_tx_seen(address, tx_hash, ts)  

    
    already_cached = {
        r[0] for r in conn.execute(
            "SELECT tx_hash FROM raw_transactions WHERE tx_hash IN ({})".format(
                ",".join("?" * len(tx_items))
            ),
            [_tx_hash_of(it) for it in tx_items if _tx_hash_of(it)],
        ).fetchall()
    } if tx_items else set()

    unlimited_detail = max_tx_details <= 0
    effective_cap = len(tx_items) if unlimited_detail else max_tx_details

    if fetch_order == "even":
        sampled = sample_evenly_incremental(tx_items, effective_cap, already_cached)
    else:
        sampled = sample_sequential(tx_items, effective_cap, already_cached)
    detail_truncated = (not unlimited_detail) and len(tx_items) > max_tx_details
    n_remaining = max(0, len(tx_items) - len(sampled))

    to_fetch = [it for it in sampled if _tx_hash_of(it) not in already_cached]
    n_reused = len(sampled) - len(to_fetch)

    if to_fetch:
        tx_hashes = [_tx_hash_of(it) for it in to_fetch if _tx_hash_of(it)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_detail, h) for h in tx_hashes]
            for f in as_completed(futures):
                tx_hash, detail = f.result()  
                store_detail(store, tx_hash, detail)  

    
    n_dao = 0
    if pull_dao:
        try:
            for ev in crawler.fetch_dao_events(address):
                store.save_dao_event(address, ev)
                n_dao += 1
        except Exception:
            pass  

    store.enqueue(address, hop=0)
    store.mark_done(address)

    summary = {
        "n_tx_in_window": len(tx_items),
        "n_tx_detail_fetched": len(sampled),
        "n_tx_detail_reused_from_cache": n_reused,
        "n_tx_detail_newly_fetched": len(to_fetch),
        "n_tx_detail_remaining": n_remaining,
        "n_tx_detail_remaining_is_exact": not listing_truncated,  
        "fetch_order": fetch_order,
        "listing_truncated": listing_truncated,
        "detail_sampled": detail_truncated,
        "n_dao_events": n_dao,
    }
    return summary, tx_items


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=Path("./ckb_data_v2"),
                    help="Base output folder. DB goes to {data-dir}/ckb_explorer.sqlite, "
                         "per-wallet provenance to {data-dir}/provenance/<address>.json. "
                         "Default: ./ckb_data_v2")
    p.add_argument("--addresses", type=Path, help="Text file, one ckb1... address per line")
    p.add_argument("--test-address", type=str, default=None,
                    help="Pull just this one address, print the summary, and exit -- "
                         "use this to sanity-check window/sampling settings before a full run")
    p.add_argument("--lookback-days", type=int, default=730,
                    help="How far back from --as-of to pull. Default: 730 (~2 years). "
                         "See module docstring for why this is recommended over 5 years / genesis.")
    p.add_argument("--as-of", type=str, default=None,
                    help="Window end date, YYYY-MM-DD (default: today, UTC). Fix this "
                         "explicitly across a multi-day/resumed run -- otherwise 'today' "
                         "changes day to day and no provenance file will match on resume.")
    p.add_argument("--max-tx-listed", type=int, default=0,
                    help="Safety cap on how many tx get LISTED within the window per address "
                         "(cheap -- 50/page, no per-tx cost). Default: 0 = unlimited, which "
                         "gives the TRUE total tx count for the window (needed for an honest "
                         "n_tx_detail_remaining figure). Set a positive number only if a "
                         "pathologically active wallet is taking too long to just list.")
    p.add_argument("--max-tx-details", type=int, default=200,
                    help="Cap on how many of those get full DETAIL fetched (expensive -- "
                         "one API call each). This is the main lever for rate-limit cost. "
                         "Default: 200")
    p.add_argument("--fetch-order", choices=["sequential", "even"], default="sequential",
                    help="sequential (default): strict newest-to-oldest, complete and "
                         "resumable -- each re-run with a higher cap continues exactly where "
                         "the last one stopped walking backward through time. No sampling. "
                         "even: spreads detail-fetches across the WHOLE window at every stage "
                         "instead, trading completeness-of-a-slice for representativeness-so-"
                         "far. See module docstring for the trade-off.")
    p.add_argument("--workers", type=int, default=6, help="Concurrent detail-fetch threads per address")
    p.add_argument("--no-dao", action="store_true", help="Skip fetching DAO events")
    p.add_argument("--force", action="store_true",
                    help="Re-pull every address in the list even if its provenance file "
                         "already matches this exact window (default: skip those -- this is "
                         "what makes an interrupted run resumable without redoing work)")
    args = p.parse_args()

    as_of = dt.datetime.strptime(args.as_of, "%Y-%m-%d") if args.as_of else dt.datetime.utcnow()
    as_of = as_of.replace(tzinfo=dt.timezone.utc)
    window_end_s = int(as_of.timestamp())
    window_start_s = window_end_s - args.lookback_days * 86400
    print(f"Window: {dt.datetime.fromtimestamp(window_start_s, tz=dt.timezone.utc).date()} "
          f"to {dt.datetime.fromtimestamp(window_end_s, tz=dt.timezone.utc).date()} "
          f"({args.lookback_days} days)")

    args.data_dir.mkdir(parents=True, exist_ok=True)
    db_path = args.data_dir / "ckb_explorer.sqlite"
    store = crawler.Store(db_path)

    if args.test_address:
        prov = load_provenance(args.data_dir, args.test_address)
        needs_full = not (prov and prov.get("window_start_epoch") == window_start_s
                           and prov.get("window_end_epoch") == window_end_s
                           and prov.get("status") == "complete")
        summary, tx_items = pull_address_history(store, args.test_address, window_start_s, window_end_s,
                                                   args.max_tx_listed, args.max_tx_details, args.workers,
                                                   not args.no_dao, needs_full_repull=needs_full,
                                                   fetch_order=args.fetch_order)
        store.conn.commit()
        write_provenance(args.data_dir, args.test_address, window_start_s, window_end_s,
                          args.lookback_days, args.max_tx_listed, args.max_tx_details, tx_items, summary)
        store.conn.close()
        print(json.dumps(summary, indent=2))
        print(f"\nProvenance written to {provenance_path(args.data_dir, args.test_address)}")
        return

    if not args.addresses:
        raise SystemExit("--addresses is required unless using --test-address")
    if not args.addresses.exists():
        raise SystemExit(f"no such file: {args.addresses}")

    addresses = load_address_list(args.addresses)
    if not addresses:
        raise SystemExit(f"{args.addresses} contained no addresses")
    print(f"Loaded {len(addresses)} target address(es) from {args.addresses}")
    print(f"Data dir: {args.data_dir}\n")

    n_done, n_skipped, n_incremental, n_failed = 0, 0, 0, []
    for i, addr in enumerate(addresses, 1):
        prov = load_provenance(args.data_dir, addr)

        if not args.force and prov and provenance_is_still_valid(
                prov, window_start_s, window_end_s, args.max_tx_listed, args.max_tx_details):
            n_skipped += 1
            print(f"  [{i}/{len(addresses)}] {addr} -- already collected and complete for "
                  f"this window/cap, skipping")
            continue

        
        same_window = bool(prov and prov.get("window_start_epoch") == window_start_s
                            and prov.get("window_end_epoch") == window_end_s
                            and prov.get("status") == "complete")
        needs_full = not same_window

        try:
            summary, tx_items = pull_address_history(store, addr, window_start_s, window_end_s,
                                                       args.max_tx_listed, args.max_tx_details,
                                                       args.workers, not args.no_dao,
                                                       needs_full_repull=needs_full,
                                                       fetch_order=args.fetch_order)
            write_provenance(args.data_dir, addr, window_start_s, window_end_s,
                              args.lookback_days, args.max_tx_listed, args.max_tx_details, tx_items, summary)
            n_done += 1
            if not needs_full:
                n_incremental += 1
            flags = []
            if summary["listing_truncated"]:
                flags.append("listing capped -- remaining count is a lower bound")
            if summary["detail_sampled"]:
                flags.append(f"{summary['n_tx_detail_remaining']} more available beyond this fetch")
            if summary.get("n_tx_detail_reused_from_cache"):
                flags.append(f"{summary['n_tx_detail_reused_from_cache']} reused from cache")
            flag_str = f" ({', '.join(flags)})" if flags else ""
            print(f"  [{i}/{len(addresses)}] {addr} -- {summary['n_tx_in_window']} tx in window, "
                  f"{summary['n_tx_detail_fetched']} detail total, "
                  f"{summary.get('n_tx_detail_newly_fetched', summary['n_tx_detail_fetched'])} newly fetched"
                  f"{flag_str}")
        except Exception as e:
            n_failed.append((addr, str(e)))
            print(f"  [{i}/{len(addresses)}] {addr} -- FAILED: {e}", file=sys.stderr)
        finally:
            store.conn.commit()

    store.conn.close()

    print(f"\nCollected {n_done}/{len(addresses)} address(es) into {db_path} "
          f"({n_skipped} already complete, skipped; {n_incremental} topped up incrementally)")
    if n_failed:
        print(f"{len(n_failed)} address(es) failed:")
        for addr, err in n_failed:
            print(f"  {addr}: {err}")
        print("Re-run the exact same command to retry just the failed ones -- "
              "everything else will be skipped via provenance.")
    print(f"\nNext: python3 preprocess_ckb.py --db {db_path} --out-dir ./features")


if __name__ == "__main__":
    main()