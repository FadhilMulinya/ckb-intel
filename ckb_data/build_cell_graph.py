from __future__ import annotations

"""
Phase 1 of the gap-closure plan (see CKB_Wallet_Classifier_Gap_Closure_Plan.md,
section 3, Phase 1): build a genuine Cell-level representation -- lock/type
scripts, previous-outpoint provenance, `since` -- from the transaction detail
already cached in raw_transactions, instead of the flat address-pair `edges`
table.

This does NOT require re-collecting anything already-collected. The only new
network calls this introduces are for OUTPOINT transactions that fund a
target wallet but weren't themselves in the collection list.

IMPORTANT CORRECTION (found by running this against real ckb_data_v2 data):
this "one-hop expansion" is NOT small in practice. With a fixed collection
window (e.g. 730 days) and ~900 target wallets, most spent Cells were
created either before the window or by an external counterparty never in
the target list -- so the missing-previous-transaction set can be in the
millions, not a bounded handful. Do not try to fetch it exhaustively.
--export-missing-prev-tx now ranks by how many of YOUR OWN inputs depend on
each missing transaction, and --fetch-missing supports --top-n /
--min-ref-count so you fetch only the small number of high-value, shared
counterparties (exchanges, pools, popular contracts) worth the API calls.
Treat the rest as INSUFFICIENT_EVIDENCE for Cell-lifetime/age features
(consistent with the gap-closure plan's Phase 2 support-condition design),
not as a gap to close.

Usage (same two-step pattern as rebuild_edges_from_cache.py, on purpose):

    # 1. ALWAYS diagnose first -- confirms which field-name shape your real
    #    cached data actually uses before anything gets written.
    python3 build_cell_graph.py --data-dir ./ckb_data_v2 --diagnose

    # 2. Only after --diagnose looks sane, build the tables.
    python3 build_cell_graph.py --data-dir ./ckb_data_v2 --rebuild

    # 3. If --diagnose showed lock resolution falling back to address_hash
    #    (this is the expected/confirmed shape of CKB Explorer's
    #    display_inputs/display_outputs -- see Data_Aquisition.md), backfill
    #    the real lock_hash you already fetched for your own target wallets:
    python3 build_cell_graph.py --data-dir ./ckb_data_v2 --backfill-from-addresses

    # 4. See which input Cells reference a previous transaction that isn't
    #    cached yet, RANKED by how many of your own inputs depend on each one.
    python3 build_cell_graph.py --data-dir ./ckb_data_v2 --export-missing-prev-tx missing_prev_tx.txt

    # 5. Fetch only the highest-value ones (see the printed cost/benefit report
    #    from step 4 for a sensible --top-n), not the full list.
    python3 build_cell_graph.py --data-dir ./ckb_data_v2 --fetch-missing --top-n 5000 --workers 6
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import cell_resolver as cr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("build_cell_graph")


CELL_SCHEMA = """
CREATE TABLE IF NOT EXISTS cells (
    out_tx_hash TEXT NOT NULL,
    out_index INTEGER NOT NULL,
    lock_hash TEXT,
    lock_code_hash TEXT,
    lock_hash_type TEXT,
    lock_args TEXT,
    lock_family TEXT,
    lock_match_method TEXT,
    type_hash TEXT,
    type_code_hash TEXT,
    type_hash_type TEXT,
    type_args TEXT,
    has_type_script INTEGER,
    type_match_method TEXT,
    capacity INTEGER,
    address_hash TEXT,
    created_block_timestamp INTEGER,
    PRIMARY KEY (out_tx_hash, out_index)
);

CREATE TABLE IF NOT EXISTS tx_inputs (
    tx_hash TEXT NOT NULL,
    input_index INTEGER NOT NULL,
    prev_tx_hash TEXT,
    prev_index INTEGER,
    prev_match_method TEXT,
    lock_hash TEXT,
    lock_family TEXT,
    address_hash TEXT,
    capacity INTEGER,
    since_raw TEXT,
    since_relative INTEGER,
    since_metric TEXT,
    since_raw_value INTEGER,
    is_cellbase INTEGER,
    block_timestamp INTEGER,
    PRIMARY KEY (tx_hash, input_index)
);

CREATE TABLE IF NOT EXISTS tx_outputs (
    tx_hash TEXT NOT NULL,
    output_index INTEGER NOT NULL,
    lock_hash TEXT,
    lock_family TEXT,
    type_hash TEXT,
    has_type_script INTEGER,
    capacity INTEGER,
    block_timestamp INTEGER,
    PRIMARY KEY (tx_hash, output_index)
);

CREATE TABLE IF NOT EXISTS cell_resolution_audit (
    tx_hash TEXT PRIMARY KEY,
    n_inputs INTEGER,
    n_inputs_prev_resolved INTEGER,
    n_inputs_since_present INTEGER,
    n_outputs INTEGER,
    n_outputs_type_script INTEGER,
    processed_at INTEGER
);
"""


def _parse_tx(raw_json: str) -> Optional[tuple]:
    """Returns (tx_hash, block_ts, inputs, outputs) or None."""
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        return None
    attrs = data.get("attributes", {})
    tx_hash = attrs.get("transaction_hash") or data.get("id")
    block_ts = cr._to_int(attrs.get("block_timestamp"))
    inputs = attrs.get("display_inputs") or []
    outputs = attrs.get("display_outputs") or []
    return tx_hash, block_ts, inputs, outputs


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------

def diagnose(conn: sqlite3.Connection, sample_size: int = 500) -> None:
    n_tx = conn.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
    log.info("raw_transactions cached: %d (sampling up to %d)", n_tx, sample_size)
    if n_tx == 0:
        log.warning("No cached transactions -- nothing to diagnose.")
        return

    rows = conn.execute(
        "SELECT tx_hash, raw_json FROM raw_transactions LIMIT ?", (sample_size,)
    ).fetchall()

    n_tx_checked = 0
    n_inputs_checked = 0
    n_outputs_checked = 0
    lock_match_counts = Counter()
    type_match_counts = Counter()
    prev_outpoint_match_counts = Counter()
    since_present = 0
    since_meaningful = 0
    cellbase_flagged = 0
    bad_json = 0

    for tx_hash, raw_json in rows:
        parsed = _parse_tx(raw_json)
        if parsed is None:
            bad_json += 1
            continue
        _, _, inputs, outputs = parsed
        if not inputs and not outputs:
            continue
        n_tx_checked += 1

        for cell in inputs:
            n_inputs_checked += 1
            lock_info = cr.extract_lock(cell)
            lock_match_counts[lock_info["match_method"]] += 1
            prev = cr.extract_previous_outpoint(cell)
            prev_outpoint_match_counts[prev["match_method"]] += 1
            since_raw = cr.extract_since_raw(cell)
            decoded = cr.decode_since(since_raw)
            if decoded is not None:
                since_present += 1
                if decoded["raw_value"] > 0:
                    since_meaningful += 1
            if cr.is_cellbase_input(cell):
                cellbase_flagged += 1

        for cell in outputs:
            n_outputs_checked += 1
            lock_info = cr.extract_lock(cell)
            lock_match_counts[lock_info["match_method"]] += 1
            type_info = cr.extract_type(cell)
            type_match_counts[type_info["match_method"]] += 1

    log.info("Parsed %d/%d sampled transaction(s) with usable input/output lists "
              "(%d had unparseable JSON)", n_tx_checked, len(rows), bad_json)
    log.info("Checked %d input cell(s), %d output cell(s)", n_inputs_checked, n_outputs_checked)

    print("\n=== Lock resolution match method (inputs + outputs combined) ===")
    total_lock = sum(lock_match_counts.values()) or 1
    for method, count in lock_match_counts.most_common():
        print(f"  {count:6d}  ({100*count/total_lock:5.1f}%)  {method}")
    if lock_match_counts.get("address_fallback", 0) / total_lock > 0.5:
        print("  --> majority still falling back to address_hash, same as the current "
              "'edges' table. This means your cached data genuinely doesn't carry nested "
              "lock-script dicts on display cells -- the LOCK_KEY_CANDIDATES list in "
              "cell_resolver.py won't fix that; you'd need a different Explorer endpoint "
              "or field, or a CKB node/indexer, to get real per-cell lock scripts.")

    print("\n=== Type-script resolution match method (outputs only) ===")
    total_type = sum(type_match_counts.values()) or 1
    for method, count in type_match_counts.most_common():
        print(f"  {count:6d}  ({100*count/total_type:5.1f}%)  {method}")

    print("\n=== Previous-outpoint resolution match method (inputs only) ===")
    total_prev = sum(prev_outpoint_match_counts.values()) or 1
    for method, count in prev_outpoint_match_counts.most_common():
        print(f"  {count:6d}  ({100*count/total_prev:5.1f}%)  {method}")
    n_unresolved = prev_outpoint_match_counts.get("unresolved", 0)
    if n_unresolved / total_prev > 0.5:
        print("  --> majority of inputs have NO recoverable previous-outpoint under any "
              "candidate field name tried. This means Cell lineage (report section 4/8) "
              "cannot be built from this cached data as-is -- check PREV_OUTPOINT_FLAT_CANDIDATES "
              "in cell_resolver.py against a real raw_transactions row's actual keys "
              "(e.g. `sqlite3 ckb_explorer.sqlite \"SELECT raw_json FROM raw_transactions LIMIT 1\"` "
              "and inspect the display_inputs keys by hand), or plan on a node/indexer source instead.")
    else:
        print(f"  --> {100*(1-n_unresolved/total_prev):.1f}% of inputs resolved a previous "
              f"outpoint. Cell lineage should be buildable for the resolved majority; "
              f"run --rebuild, then --export-missing-prev-tx to see how many distinct "
              f"prior transactions still need fetching to close the remaining gap.")

    print(f"\n=== `since` presence ===\n  {since_present}/{n_inputs_checked} input(s) "
          f"({100*since_present/max(1,n_inputs_checked):.1f}%) decode to a non-null `since`")
    print(f"  of those, {since_meaningful}/{since_present} "
          f"({100*since_meaningful/max(1,since_present):.1f}%) have raw_value > 0 -- an actual "
          f"timelock constraint, not just the common relative-0-blocks sentinel "
          f"(0x8000000000000000) that many wallets set as a routine placeholder even with no "
          f"real timelock intended. If the presence figure is ~100% but the meaningful figure "
          f"is low, that's expected and NOT a bug -- treat since_raw_value (in tx_inputs) as "
          f"the real feature going forward, not mere since-presence.")
    print(f"\n=== Cellbase flag presence ===\n  {cellbase_flagged}/{n_inputs_checked} input(s) "
          f"({100*cellbase_flagged/max(1,n_inputs_checked):.1f}%) flagged from_cellbase/is_cellbase")
    if cellbase_flagged == 0:
        print("  --> zero cellbase-flagged inputs in this sample is expected if none of your "
              "wallets touch a coinbase transaction directly; it does NOT by itself mean the "
              "flag extraction is broken. Miner detection (plan Phase 5) will likely need "
              "cellbase LINEAGE (a cell descended from a cellbase output), not just a direct "
              "cellbase input flag -- treat this count as a lower bound, not the final answer.")

    print("\nThis was a diagnosis-only run (no DB changes). Re-run with --rebuild once "
          "the match-method distributions above look right for your real data.")


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

def rebuild(conn: sqlite3.Connection, registry: dict, batch_commit: int = 500) -> None:
    conn.executescript(CELL_SCHEMA)
    conn.commit()

    for table in ("cells", "tx_inputs", "tx_outputs", "cell_resolution_audit"):
        n_before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if n_before:
            log.info("clearing %d existing row(s) from %s before rebuild", n_before, table)
            conn.execute(f"DELETE FROM {table}")
    conn.commit()

    n_tx = conn.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
    log.info("rebuilding Cell tables from %d cached transaction(s)...", n_tx)

    cur = conn.execute("SELECT tx_hash, raw_json FROM raw_transactions")
    n_processed = 0
    n_cells = 0
    n_bad_json = 0
    start = time.time()

    for tx_hash_pk, raw_json in cur:
        parsed = _parse_tx(raw_json)
        if parsed is None:
            n_bad_json += 1
            continue
        tx_hash, block_ts, inputs, outputs = parsed
        tx_hash = tx_hash or tx_hash_pk

        n_prev_resolved = 0
        n_since_present = 0

        for i, cell in enumerate(inputs):
            lock_info = cr.extract_lock(cell)
            lock_family = cr.classify_lock_family(lock_info.get("lock_code_hash"), lock_info.get("lock_hash_type"), registry)
            prev = cr.extract_previous_outpoint(cell)
            if prev["prev_tx_hash"] is not None:
                n_prev_resolved += 1
            since_raw = cr.extract_since_raw(cell)
            since_decoded = cr.decode_since(since_raw)
            if since_decoded is not None:
                n_since_present += 1

            conn.execute(
                "INSERT OR REPLACE INTO tx_inputs "
                "(tx_hash, input_index, prev_tx_hash, prev_index, prev_match_method, "
                " lock_hash, lock_family, address_hash, capacity, since_raw, "
                " since_relative, since_metric, since_raw_value, is_cellbase, block_timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tx_hash, i, prev["prev_tx_hash"], prev["prev_index"], prev["match_method"],
                    lock_info.get("lock_hash"), lock_family, lock_info.get("address_hash"),
                    cr.extract_capacity(cell),
                    str(since_raw) if since_raw is not None else None,
                    int(since_decoded["relative"]) if since_decoded else None,
                    since_decoded["metric"] if since_decoded else None,
                    since_decoded["raw_value"] if since_decoded else None,
                    int(cr.is_cellbase_input(cell)),
                    block_ts,
                ),
            )

        for i, cell in enumerate(outputs):
            lock_info = cr.extract_lock(cell)
            lock_family = cr.classify_lock_family(lock_info.get("lock_code_hash"), lock_info.get("lock_hash_type"), registry)
            type_info = cr.extract_type(cell)
            capacity = cr.extract_capacity(cell)
            out_index = cell.get("cell_index")
            out_index = out_index if isinstance(out_index, int) or (isinstance(out_index, str) and out_index.isdigit()) else i
            out_index = int(out_index)

            conn.execute(
                "INSERT OR REPLACE INTO cells "
                "(out_tx_hash, out_index, lock_hash, lock_code_hash, lock_hash_type, lock_args, "
                " lock_family, lock_match_method, type_hash, type_code_hash, type_hash_type, "
                " type_args, has_type_script, type_match_method, capacity, address_hash, "
                " created_block_timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tx_hash, out_index, lock_info.get("lock_hash"), lock_info.get("lock_code_hash"),
                    lock_info.get("lock_hash_type"), lock_info.get("lock_args"), lock_family,
                    lock_info["match_method"], type_info.get("type_hash"), type_info.get("type_code_hash"),
                    type_info.get("type_hash_type"), type_info.get("type_args"),
                    int(type_info["has_type_script"]), type_info["match_method"], capacity,
                    lock_info.get("address_hash"), block_ts,
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO tx_outputs "
                "(tx_hash, output_index, lock_hash, lock_family, type_hash, has_type_script, "
                " capacity, block_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tx_hash, out_index, lock_info.get("lock_hash"), lock_family,
                    type_info.get("type_hash"), int(type_info["has_type_script"]), capacity, block_ts,
                ),
            )
            n_cells += 1

        conn.execute(
            "INSERT OR REPLACE INTO cell_resolution_audit "
            "(tx_hash, n_inputs, n_inputs_prev_resolved, n_inputs_since_present, "
            " n_outputs, n_outputs_type_script, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tx_hash, len(inputs), n_prev_resolved, n_since_present, len(outputs),
                sum(1 for c in outputs if cr.extract_type(c)["has_type_script"]),
                int(time.time()),
            ),
        )

        n_processed += 1
        if n_processed % batch_commit == 0:
            conn.commit()
            log.info("  %d/%d transactions processed (%d output cells written, %.0fs elapsed)",
                      n_processed, n_tx, n_cells, time.time() - start)

    conn.commit()
    if n_bad_json:
        log.warning("%d cached transaction(s) had unparseable JSON and were skipped", n_bad_json)

    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_cells_lock_hash ON cells(lock_hash)",
        "CREATE INDEX IF NOT EXISTS idx_tx_inputs_lock_hash ON tx_inputs(lock_hash)",
        "CREATE INDEX IF NOT EXISTS idx_tx_inputs_prev ON tx_inputs(prev_tx_hash, prev_index)",
        "CREATE INDEX IF NOT EXISTS idx_tx_outputs_lock_hash ON tx_outputs(lock_hash)",
    ):
        conn.execute(stmt)
    conn.commit()

    log.info("done: %d transaction(s) processed -> %d output cell(s) written to cells/tx_outputs",
              n_processed, n_cells)

    n_prev_total = conn.execute("SELECT COUNT(*) FROM tx_inputs").fetchone()[0]
    n_prev_resolved = conn.execute(
        "SELECT COUNT(*) FROM tx_inputs WHERE prev_tx_hash IS NOT NULL"
    ).fetchone()[0]
    n_prev_found_locally = conn.execute(
        "SELECT COUNT(*) FROM tx_inputs ti JOIN cells c "
        "ON c.out_tx_hash = ti.prev_tx_hash AND c.out_index = ti.prev_index"
    ).fetchone()[0]
    log.info("previous-outpoint resolved for %d/%d input(s) (%.1f%%); of those, %d already "
              "have the referenced Cell materialized locally (%.1f%% of resolved)",
              n_prev_resolved, n_prev_total, 100 * n_prev_resolved / max(1, n_prev_total),
              n_prev_found_locally, 100 * n_prev_found_locally / max(1, n_prev_resolved))
    log.info("run --export-missing-prev-tx to get the list of transactions still needed "
              "to close the remaining gap.")


def _parse_address_detail(raw_json: str) -> Optional[tuple]:
    """Extract (code_hash, hash_type, args) from a cached raw_addresses.raw_json
    blob (the /addresses/{address} response), which -- unlike display_inputs/
    display_outputs -- does carry a real nested lock_script (this is how
    collect_target_wallets.py / infer_wallet_class.py already compute correct
    lock_hash values for target wallets, per resolve_and_store_address)."""
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    item = payload.get("data")
    if isinstance(item, list):
        item = item[0] if item else None
    if not item:
        return None
    attrs = item.get("attributes", {})
    lock_info = attrs.get("lock_script") or {}
    code_hash, hash_type, args = lock_info.get("code_hash"), lock_info.get("hash_type"), lock_info.get("args")
    if code_hash and hash_type and args is not None:
        return code_hash, hash_type, args
    return None


def backfill_lock_hash_from_addresses(conn: sqlite3.Connection, registry: dict) -> None:
    """Fixes the confirmed gap from --diagnose: display_inputs/display_outputs
    cells carry only address_hash, never a nested lock script, so cells/
    tx_inputs/tx_outputs come out of --rebuild with lock_hash=NULL,
    match_method='address_fallback' for essentially everything.

    raw_addresses DOES have real lock-script data (fetched via a different
    endpoint, /addresses/{address}), but only for the wallets this pipeline
    actually collected -- your ~764 active + ~123 unused target wallets, not
    arbitrary counterparties. `wallets` is checked as a second source (it's
    populated by collect_target_wallets.py's own address-detail fetch, and
    may cover addresses raw_addresses doesn't, though without lock_args since
    `wallets` doesn't store that column). Cells belonging to un-collected
    counterparty addresses remain address-only, which is reported explicitly
    rather than silently left ambiguous.
    """
    lookup: dict[str, dict] = {}
    n_from_raw_json = n_from_raw_addresses_hash = n_from_wallets = 0

    if _table_exists(conn, "raw_addresses"):
        rows = conn.execute("SELECT address, lock_hash, raw_json FROM raw_addresses").fetchall()
        for address, lock_hash, raw_json in rows:
            code_hash = hash_type = args = None
            parsed = _parse_address_detail(raw_json) if raw_json else None
            if parsed:
                code_hash, hash_type, args = parsed
                n_from_raw_json += 1
                if not lock_hash:
                    lock_hash = cr.ckb_script_hash(code_hash, hash_type, args)
            elif lock_hash:
                n_from_raw_addresses_hash += 1
            if lock_hash or code_hash:
                lookup[address] = {
                    "lock_hash": lock_hash,
                    "lock_code_hash": code_hash,
                    "lock_hash_type": hash_type,
                    "lock_args": args,
                    "lock_family": cr.classify_lock_family(code_hash, hash_type, registry) if code_hash else "unknown",
                }
        log.info("raw_addresses: %d row(s), %d with a decodable lock script, %d with only a "
                  "precomputed lock_hash and no script breakdown", len(rows), n_from_raw_json, n_from_raw_addresses_hash)
    else:
        log.info("no raw_addresses table -- trying wallets only.")

    if _table_exists(conn, "wallets"):
        rows = conn.execute(
            "SELECT address, lock_hash, lock_code_hash, lock_hash_type FROM wallets WHERE address IS NOT NULL"
        ).fetchall()
        for address, lock_hash, code_hash, hash_type in rows:
            if address in lookup or not lock_hash:
                continue
            lookup[address] = {
                "lock_hash": lock_hash,
                "lock_code_hash": code_hash,
                "lock_hash_type": hash_type,
                "lock_args": None,  # wallets doesn't store args; lock_hash itself is still authoritative
                "lock_family": cr.classify_lock_family(code_hash, hash_type, registry) if code_hash else "unknown",
            }
            n_from_wallets += 1
        log.info("wallets: %d additional address(es) with a real lock_hash not already covered by raw_addresses",
                  n_from_wallets)

    if not lookup:
        log.warning("neither raw_addresses nor wallets has usable lock data -- nothing to backfill.")
        return

    n_updated = {"cells": 0, "tx_inputs": 0, "tx_outputs": 0}
    for table, addr_col in (("cells", "address_hash"), ("tx_inputs", "address_hash"), ("tx_outputs", None)):
        if addr_col is None:
            # tx_outputs has no address_hash column -- join through cells on (tx_hash, output_index)/(out_tx_hash, out_index)
            cur = conn.execute(
                "SELECT o.tx_hash, o.output_index, c.address_hash FROM tx_outputs o "
                "JOIN cells c ON c.out_tx_hash = o.tx_hash AND c.out_index = o.output_index "
                "WHERE o.lock_hash IS NULL AND c.address_hash IS NOT NULL"
            )
            for tx_hash, out_idx, address in cur.fetchall():
                info = lookup.get(address)
                if not info:
                    continue
                conn.execute(
                    "UPDATE tx_outputs SET lock_hash = ?, lock_family = ? "
                    "WHERE tx_hash = ? AND output_index = ?",
                    (info["lock_hash"], info["lock_family"], tx_hash, out_idx),
                )
                n_updated["tx_outputs"] += 1
            continue

        cur = conn.execute(f"SELECT rowid, {addr_col} FROM {table} WHERE lock_hash IS NULL AND {addr_col} IS NOT NULL")
        for rowid, address in cur.fetchall():
            info = lookup.get(address)
            if not info:
                continue
            if table == "cells":
                conn.execute(
                    "UPDATE cells SET lock_hash=?, lock_code_hash=?, lock_hash_type=?, lock_args=?, "
                    "lock_family=?, lock_match_method='backfilled_from_raw_addresses' WHERE rowid=?",
                    (info["lock_hash"], info["lock_code_hash"], info["lock_hash_type"], info["lock_args"],
                     info["lock_family"], rowid),
                )
            else:
                conn.execute(
                    "UPDATE tx_inputs SET lock_hash=?, lock_family=? WHERE rowid=?",
                    (info["lock_hash"], info["lock_family"], rowid),
                )
            n_updated[table] += 1
    conn.commit()

    for table in ("cells", "tx_inputs", "tx_outputs"):
        n_total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        n_resolved = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE lock_hash IS NOT NULL").fetchone()[0]
        log.info("%-11s: backfilled %d row(s) this pass; %d/%d (%.1f%%) now have a real lock_hash",
                  table, n_updated[table], n_resolved, n_total, 100 * n_resolved / max(1, n_total))

    log.info("Rows still without lock_hash belong to addresses this pipeline never fetched "
              "/addresses detail for (counterparties outside the target-wallet list). Their "
              "address_hash is still recorded, so downstream features can fall back to "
              "address-level identity for those specifically, same as the current 'edges' "
              "table does for everyone today -- this backfill only closes the gap for the "
              "population that actually matters for classification: your own target wallets.")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def export_missing_prev_tx(conn: sqlite3.Connection, out_path: Path, ranked: bool = True) -> int:
    """Writes distinct missing previous-transaction hashes. When ranked=True
    (default), also writes out_path with a '.ranked.tsv' sibling sorted by
    how many of YOUR OWN tx_inputs rows depend on each one -- a prev_tx
    referenced by hundreds of your inputs is very likely a shared
    counterparty (exchange/pool/popular contract) worth fetching; one
    referenced once almost never is. At real-world scale (see module
    docstring update) the flat missing list can be enormous -- most of it
    is one-off external counterparty history, not worth chasing -- so the
    ranked file is what --fetch-missing --top-n actually uses.
    """
    rows = conn.execute(
        "SELECT ti.prev_tx_hash, COUNT(*) as ref_count FROM tx_inputs ti "
        "LEFT JOIN cells c ON c.out_tx_hash = ti.prev_tx_hash AND c.out_index = ti.prev_index "
        "WHERE ti.prev_tx_hash IS NOT NULL AND c.out_tx_hash IS NULL "
        "GROUP BY ti.prev_tx_hash"
    ).fetchall()
    missing = [(r[0], r[1]) for r in rows if r[0]]
    missing_sorted_by_hash = sorted(h for h, _ in missing)
    out_path.write_text("\n".join(missing_sorted_by_hash) + ("\n" if missing_sorted_by_hash else ""))
    log.info("wrote %s (%d distinct previous transaction(s) not yet cached)", out_path, len(missing))

    if ranked and missing:
        ranked_path = out_path.with_suffix(out_path.suffix + ".ranked.tsv")
        missing_by_count = sorted(missing, key=lambda x: -x[1])
        with open(ranked_path, "w") as f:
            f.write("# prev_tx_hash\tref_count\n")
            for h, count in missing_by_count:
                f.write(f"{h}\t{count}\n")
        log.info("wrote %s (same %d transaction(s), sorted by how many of your inputs "
                  "depend on each one)", ranked_path, len(missing))

        counts = [c for _, c in missing]
        n_single_ref = sum(1 for c in counts if c == 1)
        top10_total_refs = sum(c for _, c in missing_by_count[:10])
        all_refs = sum(counts)
        print(f"\n=== Missing previous-transaction cost/benefit ===")
        print(f"  {len(missing)} distinct missing transaction(s), covering {all_refs} of your input row(s)")
        print(f"  {n_single_ref} ({100*n_single_ref/len(missing):.1f}%) are referenced by only 1 of "
              f"your inputs -- fetching these one at a time has poor payoff at this scale.")
        print(f"  the top 10 most-referenced alone cover {top10_total_refs} input row(s) "
              f"({100*top10_total_refs/max(1,all_refs):.1f}% of all resolvable references) -- "
              f"a small, high-value fetch.")
        if len(missing) > 50000:
            print(f"\n  At {len(missing)} distinct transactions, exhaustively fetching all of them "
                  f"is NOT recommended -- it's realistically a multi-day-to-multi-week task and "
                  f"mostly pulls in one-off counterparty history outside your classification "
                  f"population. Use --fetch-missing --top-n <N> against {ranked_path.name} instead "
                  f"of trying to close this gap completely. Cell-lifetime/age features for the "
                  f"unresolved remainder should be treated as INSUFFICIENT_EVIDENCE (per the "
                  f"gap-closure plan's Phase 2 support-condition design), not as a blocker.")
    return len(missing)


def fetch_missing_prev_tx(conn: sqlite3.Connection, workers: int, top_n: Optional[int] = None,
                           min_ref_count: int = 1) -> int:
    """Bounded expansion: fetch the previous transactions that input Cells
    reference but that aren't in raw_transactions yet, then re-run --rebuild
    to pick them up. This does NOT re-collect anything already-collected --
    see module docstring.

    At real-world scale this list is typically far too large to fetch in
    full (see export_missing_prev_tx's cost/benefit report) -- use --top-n
    and/or --min-ref-count to fetch only the highest-value transactions
    (the ones shared across many of your own inputs) instead.
    """
    try:
        import ckb_explorer_pull as crawler
    except ImportError:
        log.error("Could not import ckb_explorer_pull.py -- it must be in the same directory.")
        return 0

    from concurrent.futures import ThreadPoolExecutor, as_completed

    rows = conn.execute(
        "SELECT ti.prev_tx_hash, COUNT(*) as ref_count FROM tx_inputs ti "
        "LEFT JOIN cells c ON c.out_tx_hash = ti.prev_tx_hash AND c.out_index = ti.prev_index "
        "WHERE ti.prev_tx_hash IS NOT NULL AND c.out_tx_hash IS NULL "
        "GROUP BY ti.prev_tx_hash"
    ).fetchall()
    missing = [(r[0], r[1]) for r in rows if r[0] and r[1] >= min_ref_count]
    missing.sort(key=lambda x: -x[1])
    if top_n is not None:
        missing = missing[:top_n]

    if not missing:
        log.info("nothing to fetch at these thresholds (top_n=%s, min_ref_count=%d).", top_n, min_ref_count)
        return 0

    log.info("fetching %d previous transaction(s) with %d worker(s) "
              "(top_n=%s, min_ref_count=%d)...", len(missing), workers, top_n, min_ref_count)
    n_fetched = 0

    def _fetch(tx_hash):
        return tx_hash, crawler.fetch_transaction_detail(tx_hash)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fetch, h) for h, _ in missing]
        for f in as_completed(futures):
            tx_hash, detail = f.result()
            if detail:
                conn.execute(
                    "INSERT OR REPLACE INTO raw_transactions (tx_hash, raw_json, fetched_at) "
                    "VALUES (?, ?, ?)",
                    (tx_hash, json.dumps(detail), int(time.time())),
                )
                n_fetched += 1
    conn.commit()
    log.info("fetched %d/%d transaction(s). Re-run --rebuild to incorporate them.",
              n_fetched, len(missing))
    return n_fetched


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, required=True,
                   help="ckb_data_v2-style directory containing ckb_explorer.sqlite")
    p.add_argument("--diagnose", action="store_true",
                   help="Read-only: report which field-name shapes actually appear in your "
                        "cached data. Default action if no other flag is given.")
    p.add_argument("--rebuild", action="store_true",
                   help="Build/replace cells, tx_inputs, tx_outputs, cell_resolution_audit "
                        "from raw_transactions. Safe to re-run (clears and rewrites those "
                        "tables only -- never touches raw_transactions/edges/provenance).")
    p.add_argument("--backfill-from-addresses", action="store_true",
                   help="Backfill real lock_hash/lock_code_hash/lock_hash_type/lock_args/lock_family "
                        "onto cells/tx_inputs/tx_outputs wherever address_hash matches an address "
                        "already resolved in raw_addresses or wallets (your own collected wallets). "
                        "Run this AFTER --rebuild. Does not resolve counterparty-only addresses "
                        "-- see the printed note.")
    p.add_argument("--export-missing-prev-tx", type=Path, default=None,
                   help="Write the list of distinct previous-transaction hashes referenced "
                        "by tx_inputs but not yet cached, to this file.")
    p.add_argument("--fetch-missing", action="store_true",
                   help="Fetch missing previous transactions over the network, prioritized by "
                        "how many of your own inputs reference each one -- see --top-n / "
                        "--min-ref-count. Then remind you to re-run --rebuild.")
    p.add_argument("--top-n", type=int, default=None,
                   help="With --fetch-missing: only fetch the N most-referenced missing "
                        "transactions. Strongly recommended over fetching everything once "
                        "the missing list is large (see the cost/benefit report printed by "
                        "--export-missing-prev-tx).")
    p.add_argument("--min-ref-count", type=int, default=1,
                   help="With --fetch-missing: skip transactions referenced by fewer than this "
                        "many of your own inputs. Default 1 (no filtering beyond --top-n).")
    p.add_argument("--workers", type=int, default=6, help="Concurrent fetch threads for --fetch-missing")
    p.add_argument("--sample-size", type=int, default=500, help="Transactions to sample for --diagnose")
    p.add_argument("--registry", type=Path, default=None,
                   help="Path to lock_script_registry.json (default: alongside this script)")
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    registry = cr.load_lock_registry(args.registry)
    if not registry:
        log.warning("lock_script_registry.json not found/empty -- lock_family will be "
                     "'unrecognized' for everything. This does not block Cell resolution "
                     "itself, only the lock-family CONTEXT feature.")

    did_something = False
    try:
        if args.rebuild:
            rebuild(conn, registry)
            did_something = True
        if args.backfill_from_addresses:
            backfill_lock_hash_from_addresses(conn, registry)
            did_something = True
        if args.export_missing_prev_tx:
            export_missing_prev_tx(conn, args.export_missing_prev_tx)
            did_something = True
        if args.fetch_missing:
            fetch_missing_prev_tx(conn, args.workers, top_n=args.top_n, min_ref_count=args.min_ref_count)
            did_something = True
        if args.diagnose or not did_something:
            diagnose(conn, sample_size=args.sample_size)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
