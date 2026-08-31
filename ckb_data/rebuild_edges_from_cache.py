from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rebuild_edges")

_CKB_HASH_TYPE_BYTE = {"data": 0, "type": 1, "data1": 2, "data2": 4}


def ckb_script_hash(code_hash_hex: str, hash_type: str, args_hex: str) -> Optional[str]:
    """Identical to collect_target_wallets.py's ckb_script_hash -- duplicated
    here (rather than imported) so this script has no dependency on the
    rest of the pipeline and can be run standalone against just the db."""
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


def old_extract_lock_hash(cell: dict) -> Optional[str]:
    """Exact copy of the ORIGINAL (buggy) ckb_explorer_pull.py logic, kept
    only so --diagnose can show old-vs-new side by side."""
    lock = cell.get("lock") if isinstance(cell.get("lock"), dict) else None
    if lock:
        h = lock.get("code_hash_hash") or lock.get("hash")
        if h:
            return h
        code_hash = lock.get("code_hash")
        args = lock.get("args")
        if code_hash and args:
            return f"{code_hash}:{args}"
    return cell.get("address_hash") or cell.get("lock_hash") or cell.get("address")


def canonical_lock_hash(cell: dict) -> Optional[str]:
    """Corrected version: always prefer the real blake2b script hash when
    code_hash/hash_type/args are all present (this is what raw_addresses
    stores), falling back to the old heuristics only when they're not."""
    lock = cell.get("lock") if isinstance(cell.get("lock"), dict) else None
    if lock:
        code_hash = lock.get("code_hash")
        hash_type = lock.get("hash_type")
        args = lock.get("args")
        if code_hash and hash_type and args is not None:
            h = ckb_script_hash(code_hash, hash_type, args)
            if h:
                return h
        h = lock.get("code_hash_hash") or lock.get("hash")
        if h:
            return h
        if code_hash and args:
            return f"{code_hash}:{args}"
    return cell.get("address_hash") or cell.get("lock_hash") or cell.get("address")


def _extract_address(cell: dict) -> Optional[str]:
    return cell.get("address_hash") or cell.get("address")


def _extract_capacity(cell: dict) -> Optional[int]:
    return _to_int(cell.get("capacity"))


def _to_int(v) -> Optional[int]:
    """Handles the real CKB Explorer API shape where numeric fields like
    `capacity` come back as STRINGS with a trailing decimal point, e.g.
    "1502912399995344.0" -- plain int(v) raises ValueError on that (int()
    does not parse decimal points in strings, only in float objects), so
    this was silently returning None for every capacity in every cell,
    which is what made resolve_transaction_to_edges produce zero edges
    for literally every transaction: `if not cap: continue` skipped every
    single output. Falls back to Decimal for exactness on very large
    capacities where a float round-trip could lose precision."""
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        from decimal import Decimal, InvalidOperation
        return int(Decimal(str(v)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def resolve_transaction_to_edges_fixed(tx_payload: dict) -> list[dict]:
    """Same edge-generation algorithm as ckb_explorer_pull.resolve_transaction_to_edges
    (including its proportional-value-split heuristic and its from==to
    self-change skip), with only the lock-hash computation corrected."""
    data = tx_payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        return []
    attrs = data.get("attributes", {})
    tx_hash = attrs.get("transaction_hash") or data.get("id")
    block_ts = _to_int(attrs.get("block_timestamp"))

    inputs = attrs.get("display_inputs") or []
    outputs = attrs.get("display_outputs") or []
    if not inputs or not outputs:
        return []

    in_hashes = [canonical_lock_hash(c) for c in inputs]
    out_caps = [
        (canonical_lock_hash(c), _extract_address(c), _extract_capacity(c))
        for c in outputs
    ]
    total_out = sum(c for _, _, c in out_caps if c) or 1

    edges = []
    seen_from = set(h for h in in_hashes if h)
    for from_hash in seen_from:
        for to_hash, to_address, cap in out_caps:
            if not to_hash or not cap:
                continue
            if to_hash == from_hash:
                continue
            share = cap / total_out
            edges.append({
                "from_lock_hash": from_hash,
                "to_lock_hash": to_hash,
                "to_address": to_address,
                "value_shannon": share * total_out,
                "capacity_bytes": cap,
                "block_timestamp": block_ts,
                "tx_hash": tx_hash,
            })
    return edges


# ------------------------------------------------------------------------
# Diagnose
# ------------------------------------------------------------------------

def diagnose(conn: sqlite3.Connection, sample_size: int = 500):
    n_tx = conn.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
    n_edges_old = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    n_addr = conn.execute("SELECT COUNT(*) FROM raw_addresses WHERE lock_hash IS NOT NULL").fetchone()[0]

    log.info("raw_transactions cached: %d", n_tx)
    log.info("edges rows (current/old): %d", n_edges_old)
    log.info("raw_addresses with a resolved lock_hash: %d", n_addr)

    if n_addr:
        sample_addr_hash = conn.execute(
            "SELECT lock_hash FROM raw_addresses WHERE lock_hash IS NOT NULL LIMIT 1"
        ).fetchone()[0]
        log.info("example raw_addresses.lock_hash  : %s", sample_addr_hash)
    if n_edges_old:
        sample_edge_hash = conn.execute(
            "SELECT from_lock_hash FROM edges LIMIT 1"
        ).fetchone()[0]
        log.info("example edges.from_lock_hash    : %s", sample_edge_hash)
        if n_addr and sample_addr_hash and sample_edge_hash:
            def _shape(s: str) -> str:
                if s.startswith("ckb1") or s.startswith("ckt1"):
                    return "address"
                if ":" in s:
                    return "composite-placeholder"
                if s.startswith("0x") and len(s) == 66:
                    return "real-hash"
                return "unknown"
            shape_addr, shape_edge = _shape(sample_addr_hash), _shape(sample_edge_hash)
            if shape_addr == shape_edge == "real-hash":
                log.info("Same format? YES -- both look like real 32-byte lock hashes.")
            elif shape_edge == "address":
                log.warning(
                    "Same format? NO -- raw_addresses.lock_hash is a %s but "
                    "edges.from_lock_hash is an ADDRESS STRING. This is expected "
                    "when cells have no `lock` object (only `address_hash`) -- "
                    "preprocess_ckb_wallets.py's resolve_wallet_identifiers() "
                    "already tries matching by address as well as by lock_hash "
                    "to handle exactly this case, so this by itself is not a "
                    "blocker as long as edges rows > 0 above.", shape_addr,
                )
            else:
                log.warning(
                    "Same format? NO -- raw_addresses.lock_hash looks like '%s' "
                    "and edges.from_lock_hash looks like '%s'. This IS the "
                    "lock-hash mismatch bug; --rebuild should fix it.",
                    shape_addr, shape_edge,
                )

    cur = conn.execute("SELECT tx_hash, raw_json FROM raw_transactions LIMIT ?", (sample_size,))
    n_cells_checked = 0
    n_cells_with_native_hash_field = 0
    n_cells_old_new_differ = 0
    n_cells_capacity_unparseable_old_way = 0
    n_cells_capacity_unparseable_new_way = 0
    example_pairs = []
    example_bad_capacities = []

    for tx_hash, raw_json in cur.fetchall():
        try:
            detail = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        data = detail.get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        if not data:
            continue
        attrs = data.get("attributes", {})
        cells = (attrs.get("display_inputs") or []) + (attrs.get("display_outputs") or [])
        for cell in cells:
            n_cells_checked += 1
            lock = cell.get("lock") if isinstance(cell.get("lock"), dict) else None
            if lock and (lock.get("code_hash_hash") or lock.get("hash")):
                n_cells_with_native_hash_field += 1
            old_h = old_extract_lock_hash(cell)
            new_h = canonical_lock_hash(cell)
            if old_h != new_h:
                n_cells_old_new_differ += 1
                if len(example_pairs) < 3:
                    example_pairs.append((old_h, new_h))

            cap_raw = cell.get("capacity")
            try:
                int(cap_raw)  # the ORIGINAL (buggy) parse: plain int()
            except (TypeError, ValueError):
                n_cells_capacity_unparseable_old_way += 1
                if len(example_bad_capacities) < 2:
                    example_bad_capacities.append(cap_raw)
            if _extract_capacity(cell) is None:
                n_cells_capacity_unparseable_new_way += 1

    log.info("Sampled %d transactions -> %d input/output cells checked",
              min(sample_size, n_tx), n_cells_checked)
    if n_cells_checked:
        log.info("Cells where the API actually provided a native hash field "
                  "(old code's first-choice path): %d/%d (%.1f%%)",
                  n_cells_with_native_hash_field, n_cells_checked,
                  100 * n_cells_with_native_hash_field / n_cells_checked)
        log.info("Cells where old vs. corrected lock-hash computation "
                  "DISAGREE: %d/%d (%.1f%%)",
                  n_cells_old_new_differ, n_cells_checked,
                  100 * n_cells_old_new_differ / n_cells_checked)
        log.info("Cells where capacity FAILS to parse under the OLD plain "
                  "int(v) call: %d/%d (%.1f%%)",
                  n_cells_capacity_unparseable_old_way, n_cells_checked,
                  100 * n_cells_capacity_unparseable_old_way / n_cells_checked)
        log.info("Cells where capacity FAILS to parse under the CORRECTED "
                  "(int-or-Decimal) call: %d/%d (%.1f%%)",
                  n_cells_capacity_unparseable_new_way, n_cells_checked,
                  100 * n_cells_capacity_unparseable_new_way / n_cells_checked)
    for old_h, new_h in example_pairs:
        log.info("  lock-hash example -- old: %s\n                          new: %s", old_h, new_h)
    for cap in example_bad_capacities:
        log.info("  capacity value that broke old parsing: %r", cap)

    if n_cells_checked and n_cells_capacity_unparseable_old_way / n_cells_checked > 0.5:
        log.warning(
            "Diagnosis CONFIRMED: the majority of cells have a capacity value "
            "(e.g. a decimal-point string like \"...995344.0\") that the "
            "ORIGINAL code's plain int(v) call cannot parse -- it silently "
            "returns None, which is why `if not cap: continue` skips every "
            "output and resolve_transaction_to_edges produces ZERO edges for "
            "every transaction, regardless of lock-hash correctness. "
            "Re-run with --rebuild -- this script's corrected capacity "
            "parsing (int() first, falling back to Decimal for decimal-point "
            "strings) resolves this."
        )
    elif n_cells_checked and n_cells_old_new_differ / n_cells_checked > 0.5:
        log.warning(
            "Diagnosis CONFIRMED: the majority of cells produce a different "
            "lock hash under the corrected computation. This matches the "
            "'100%% zero sent/received edges' symptom. Re-run with --rebuild "
            "to fix the edges table from the cached transaction data (no "
            "network access needed)."
        )
    elif n_cells_checked:
        log.info(
            "Old and corrected computations mostly agree on this sample -- "
            "the lock-hash mismatch may not be your issue here. Don't run "
            "--rebuild blindly; investigate features_full.csv directly "
            "instead (e.g. check whether raw_addresses.lock_hash is even "
            "being populated for these addresses)."
        )
    else:
        log.warning("No cells could be checked -- is raw_transactions empty?")


# ------------------------------------------------------------------------
# Rebuild
# ------------------------------------------------------------------------

EDGES_SCHEMA = """
CREATE TABLE edges (
    from_lock_hash TEXT NOT NULL,
    to_lock_hash TEXT NOT NULL,
    value_shannon REAL NOT NULL,
    capacity_bytes INTEGER,
    block_timestamp INTEGER,
    tx_hash TEXT NOT NULL,
    PRIMARY KEY (from_lock_hash, to_lock_hash, tx_hash)
);
"""


def rebuild(conn: sqlite3.Connection, batch_commit: int = 500):
    backup_name = f"edges_backup_pre_hash_fix"
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (backup_name,)
    ).fetchone()
    if existing:
        raise SystemExit(
            f"A backup table '{backup_name}' already exists -- refusing to overwrite it "
            f"(this probably means --rebuild was already run once). Drop it manually first "
            f"if you're sure you want to redo the rebuild: "
            f"sqlite3 ckb_explorer.sqlite \"DROP TABLE {backup_name};\""
        )

    n_old_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.execute(f"ALTER TABLE edges RENAME TO {backup_name}")
    conn.execute(EDGES_SCHEMA)
    conn.commit()
    log.info("backed up old edges table (%d rows) to '%s', created fresh empty edges table",
              n_old_edges, backup_name)

    total_tx = 0
    total_edges = 0
    total_skipped_bad_json = 0
    cur = conn.execute("SELECT tx_hash, raw_json FROM raw_transactions")
    rows = cur.fetchall()
    n_rows = len(rows)
    start = time.time()

    for tx_hash, raw_json in rows:
        try:
            detail = json.loads(raw_json)
        except json.JSONDecodeError:
            total_skipped_bad_json += 1
            continue
        edges = resolve_transaction_to_edges_fixed(detail)
        for e in edges:
            conn.execute(
                "INSERT OR REPLACE INTO edges "
                "(from_lock_hash, to_lock_hash, value_shannon, capacity_bytes, block_timestamp, tx_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (e["from_lock_hash"], e["to_lock_hash"], e["value_shannon"],
                 e["capacity_bytes"], e["block_timestamp"], e["tx_hash"]),
            )
            total_edges += 1
        total_tx += 1
        if total_tx % batch_commit == 0:
            conn.commit()
            elapsed = time.time() - start
            log.info("  %d/%d transactions reprocessed (%d edges so far, %.0fs elapsed)",
                      total_tx, n_rows, total_edges, elapsed)

    conn.commit()
    if total_skipped_bad_json:
        log.warning("%d cached transaction(s) had unparseable JSON and were skipped",
                     total_skipped_bad_json)
    log.info("done: %d transactions reprocessed -> %d edges written (was %d before the fix)",
              total_tx, total_edges, n_old_edges)

    # The table's primary key (from_lock_hash, to_lock_hash, tx_hash) only
    # accelerates lookups by from_lock_hash (the leftmost column) --
    # preprocess_ckb_wallets.py's "received" query filters by to_lock_hash
    # alone, which without its own index means a full table scan per
    # wallet. With a table this size that turns a few-second preprocessing
    # step into many minutes, so build both single-column indexes now
    # while we already have the connection open.
    idx_start = time.time()
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_to_lock_hash ON edges(to_lock_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_from_lock_hash ON edges(from_lock_hash)")
    conn.commit()
    log.info("built lookup indexes on edges(to_lock_hash) and edges(from_lock_hash) in %.1fs",
              time.time() - idx_start)

    log.info("old (broken) edges table preserved as '%s' -- drop it once you've "
              "verified the new edges look right: "
              "sqlite3 ckb_explorer.sqlite \"DROP TABLE %s;\"",
              backup_name, backup_name)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--data-dir", type=Path, required=True,
                   help="ckb_data_v2-style directory containing ckb_explorer.sqlite")
    p.add_argument("--rebuild", action="store_true",
                   help="Actually rebuild the edges table (default: diagnose only, no changes)")
    p.add_argument("--sample-size", type=int, default=500,
                   help="Number of cached transactions to sample for --diagnose. Default: 500")
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        if args.rebuild:
            rebuild(conn)
        else:
            diagnose(conn, sample_size=args.sample_size)
            log.info("This was a diagnosis-only run (no DB changes). "
                      "Re-run with --rebuild to apply the fix.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()