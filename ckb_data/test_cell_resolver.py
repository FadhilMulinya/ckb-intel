"""
Sanity tests for Phase 1 (cell_resolver.py / build_cell_graph.py) using
synthetic transaction payloads shaped like CKB Explorer's transaction-detail
response. This environment has no network access to the real Explorer API,
so these fixtures encode this module's best-guess field-name candidates
(see cell_resolver.py's module docstring) -- they prove the EXTRACTION LOGIC
is correct for each candidate shape and that the whole pipeline (diagnose ->
rebuild -> export-missing-prev-tx -> fetch-missing hookup) works end to end.
They do NOT prove which shape the real Explorer API actually returns --
that's exactly why --diagnose must be run against real cached data before
trusting --rebuild.
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cell_resolver as cr
import build_cell_graph as bcg

SECP_CODE_HASH = "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"


def make_tx(tx_hash, block_ts, inputs, outputs):
    return json.dumps({
        "data": {
            "id": tx_hash,
            "attributes": {
                "transaction_hash": tx_hash,
                "block_timestamp": block_ts,
                "display_inputs": inputs,
                "display_outputs": outputs,
            },
        }
    })


def test_lock_extraction_nested():
    cell = {"lock": {"code_hash": SECP_CODE_HASH, "hash_type": "type", "args": "0x1234"}, "address_hash": "ckb1qzzz"}
    info = cr.extract_lock(cell)
    assert info["lock_hash"] and info["lock_hash"].startswith("0x"), info
    assert info["match_method"] == "nested_script:lock"
    print("OK: nested lock extraction ->", info["lock_hash"][:18], "...")


def test_lock_extraction_address_fallback():
    cell = {"address_hash": "ckb1qzzzfallback"}
    info = cr.extract_lock(cell)
    assert info["lock_hash"] is None
    assert info["match_method"] == "address_fallback"
    print("OK: address fallback when no script data present")


def test_type_extraction_present_and_absent():
    with_type = {"type": {"code_hash": "0xabc", "hash_type": "type", "args": "0xdead"}}
    without_type = {"cell_type": "normal"}
    t1 = cr.extract_type(with_type)
    t2 = cr.extract_type(without_type)
    assert t1["has_type_script"] is True and t1["match_method"] == "nested_script:type"
    assert t2["has_type_script"] is False and t2["match_method"] == "no_type_script"
    print("OK: type-script presence/absence distinguished correctly")


def test_previous_outpoint_candidates():
    nested = {"previous_output": {"tx_hash": "0xAAA", "index": 2}}
    flat1 = {"generated_tx_hash": "0xBBB", "cell_index": "3"}
    unresolved = {"address_hash": "ckb1qnothing"}
    r1 = cr.extract_previous_outpoint(nested)
    r2 = cr.extract_previous_outpoint(flat1)
    r3 = cr.extract_previous_outpoint(unresolved)
    assert r1 == {"prev_tx_hash": "0xAAA", "prev_index": 2, "match_method": "nested_previous_output"}
    assert r2["prev_tx_hash"] == "0xBBB" and r2["prev_index"] == 3
    assert r3["match_method"] == "unresolved" and r3["prev_tx_hash"] is None
    print("OK: previous-outpoint candidate priority works for nested, flat, and unresolved")


def test_since_decode():
    assert cr.decode_since(0) is None
    assert cr.decode_since(None) is None
    # absolute block number 1000 -> flag bits 0, value 1000
    d = cr.decode_since(1000)
    assert d == {"relative": False, "metric": "block_number", "raw_value": 1000}, d
    # relative (bit63=1) + timestamp metric (bits61-62=10) + value 500
    relative_ts = (1 << 63) | (2 << 61) | 500
    d2 = cr.decode_since(relative_ts)
    assert d2 == {"relative": True, "metric": "timestamp", "raw_value": 500}, d2
    print("OK: since decoding matches RFC 0017 bit layout for both test vectors")


def test_lock_family_registry():
    registry = cr.load_lock_registry(Path(__file__).parent / "lock_script_registry.json")
    fam = cr.classify_lock_family(SECP_CODE_HASH, "type", registry)
    assert fam == "secp256k1_blake160_sighash_all", fam
    fam_unknown = cr.classify_lock_family("0xnotinregistry", "type", registry)
    assert fam_unknown == "unrecognized", fam_unknown
    fam_none = cr.classify_lock_family(None, None, registry)
    assert fam_none == "unknown", fam_none
    print("OK: lock family classification (known / unrecognized / unknown) all correct")


def test_end_to_end_rebuild():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        db_path = data_dir / "ckb_explorer.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT NOT NULL, fetched_at INTEGER NOT NULL);
        """)

        # Tx1: spends a cell that was created by tx0 (NOT cached) -- creates a
        # "missing previous transaction" gap on purpose.
        tx1_inputs = [{
            "lock": {"code_hash": SECP_CODE_HASH, "hash_type": "type", "args": "0x01"},
            "address_hash": "ckb1qsender",
            "capacity": "100000000000.0",
            "previous_output": {"tx_hash": "0xTX0", "index": 0},
            "since": 0,
        }]
        tx1_outputs = [
            {"lock": {"code_hash": SECP_CODE_HASH, "hash_type": "type", "args": "0x02"},
             "address_hash": "ckb1qrecipient", "capacity": "90000000000.0", "cell_index": 0},
            {"lock": {"code_hash": SECP_CODE_HASH, "hash_type": "type", "args": "0x01"},
             "address_hash": "ckb1qsender", "capacity": "9999900000.0", "cell_index": 1,
             "type": {"code_hash": "0xUDTCODE", "hash_type": "type", "args": "0xudtargs"}},
        ]
        conn.execute(
            "INSERT INTO raw_transactions VALUES (?, ?, ?)",
            ("0xTX1", make_tx("0xTX1", 1000, tx1_inputs, tx1_outputs), 1),
        )

        # Tx2: spends tx1's output #1 (IS cached) -- should resolve locally with no gap.
        tx2_inputs = [{
            "lock": {"code_hash": SECP_CODE_HASH, "hash_type": "type", "args": "0x01"},
            "address_hash": "ckb1qsender",
            "capacity": "9999900000.0",
            "generated_tx_hash": "0xTX1", "cell_index": "1",
            "since": (1 << 63) | (0 << 61) | 5,  # relative, block_number metric, 5 blocks
        }]
        tx2_outputs = [
            {"lock": {"code_hash": SECP_CODE_HASH, "hash_type": "type", "args": "0x03"},
             "address_hash": "ckb1qother", "capacity": "9999800000.0", "cell_index": 0},
        ]
        conn.execute(
            "INSERT INTO raw_transactions VALUES (?, ?, ?)",
            ("0xTX2", make_tx("0xTX2", 2000, tx2_inputs, tx2_outputs), 1),
        )
        conn.commit()

        registry = cr.load_lock_registry(Path(__file__).parent / "lock_script_registry.json")
        bcg.rebuild(conn, registry)

        n_cells = conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        assert n_cells == 3, f"expected 3 output cells (2 from TX1 + 1 from TX2), got {n_cells}"

        # TX1's output #1 should carry a type script (xUDT-like).
        row = conn.execute(
            "SELECT has_type_script, type_code_hash FROM cells WHERE out_tx_hash='0xTX1' AND out_index=1"
        ).fetchone()
        assert row == (1, "0xUDTCODE"), row

        # TX2's input should resolve prev_tx_hash/prev_index via the flat-field
        # candidate (generated_tx_hash + cell_index).
        row = conn.execute(
            "SELECT prev_tx_hash, prev_index, prev_match_method, since_relative, since_metric, since_raw_value "
            "FROM tx_inputs WHERE tx_hash='0xTX2' AND input_index=0"
        ).fetchone()
        assert row[0] == "0xTX1" and row[1] == 1, row
        assert row[2].startswith("flat_fields:"), row
        assert row[3] == 1 and row[4] == "block_number" and row[5] == 5, row

        # TX1's input references 0xTX0 which is NOT cached -> should show up
        # as a missing previous transaction.
        missing_path = data_dir / "missing.txt"
        n_missing = bcg.export_missing_prev_tx(conn, missing_path)
        assert n_missing == 1, n_missing
        assert missing_path.read_text().strip() == "0xTX0"

        # TX2's input references 0xTX1 which IS cached -> must NOT show up as missing.
        assert "0xTX1" not in missing_path.read_text()

        conn.close()
        print("OK: end-to-end rebuild (cells/tx_inputs/tx_outputs populated correctly, "
              "type script detected, since decoded, prev-outpoint resolved via flat-field "
              "fallback, and the genuinely-missing previous transaction correctly identified)")


def test_since_diagnose_hexzero_not_counted_as_present():
    # Regression test for the bug caught against real data: Explorer returns
    # since as a hex string like "0x0" for "no timelock" -- decode_since must
    # treat that as absent, not present.
    assert cr.decode_since("0x0") is None
    assert cr.decode_since("0") is None
    print("OK: hex-string zero since value correctly treated as absent")


def test_backfill_from_addresses():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        db_path = data_dir / "ckb_explorer.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT NOT NULL, fetched_at INTEGER NOT NULL);
            CREATE TABLE raw_addresses (address TEXT PRIMARY KEY, lock_hash TEXT, raw_json TEXT NOT NULL, fetched_at INTEGER NOT NULL);
        """)

        # A tx entirely between two addresses we DO have address-detail for.
        tx_inputs = [{"address_hash": "ckb1qsender", "capacity": "100000000000.0",
                      "previous_output": {"tx_hash": "0xTX0", "index": 0}, "since": "0x0"}]
        tx_outputs = [{"address_hash": "ckb1qrecipient", "capacity": "90000000000.0", "cell_index": 0},
                      {"address_hash": "ckb1qunknown_counterparty", "capacity": "9999900000.0", "cell_index": 1}]
        conn.execute("INSERT INTO raw_transactions VALUES (?, ?, ?)",
                     ("0xTX1", make_tx("0xTX1", 1000, tx_inputs, tx_outputs), 1))

        # raw_addresses has real lock-script detail for sender + recipient
        # (as collect_target_wallets.py would populate), but NOT for the
        # counterparty -- exactly the situation --diagnose surfaced.
        addr_detail = lambda code_hash, args: json.dumps({
            "data": {"attributes": {"lock_script": {"code_hash": code_hash, "hash_type": "type", "args": args}}}
        })
        conn.execute("INSERT INTO raw_addresses VALUES (?, ?, ?, ?)",
                     ("ckb1qsender", None, addr_detail(SECP_CODE_HASH, "0x01"), 1))
        conn.execute("INSERT INTO raw_addresses VALUES (?, ?, ?, ?)",
                     ("ckb1qrecipient", None, addr_detail(SECP_CODE_HASH, "0x02"), 1))
        conn.commit()

        registry = cr.load_lock_registry(Path(__file__).parent / "lock_script_registry.json")
        bcg.rebuild(conn, registry)

        # Before backfill: everything should be address_fallback / lock_hash NULL.
        n_unresolved = conn.execute("SELECT COUNT(*) FROM cells WHERE lock_hash IS NULL").fetchone()[0]
        assert n_unresolved == 2, n_unresolved

        bcg.backfill_lock_hash_from_addresses(conn, registry)

        sender_row = conn.execute(
            "SELECT lock_hash, lock_family FROM tx_inputs WHERE tx_hash='0xTX1' AND input_index=0"
        ).fetchone()
        assert sender_row[0] is not None and sender_row[1] == "secp256k1_blake160_sighash_all", sender_row

        recipient_cell = conn.execute(
            "SELECT lock_hash, lock_family FROM cells WHERE out_tx_hash='0xTX1' AND out_index=0"
        ).fetchone()
        assert recipient_cell[0] is not None, recipient_cell

        # The counterparty we never fetched address detail for must stay
        # unresolved (not silently guessed) -- confirms the reported gap is honest.
        counterparty_cell = conn.execute(
            "SELECT lock_hash FROM cells WHERE out_tx_hash='0xTX1' AND out_index=1"
        ).fetchone()
        assert counterparty_cell[0] is None, counterparty_cell

        # tx_outputs (joined through cells, no address_hash column of its own) should match too.
        recipient_output = conn.execute(
            "SELECT lock_hash FROM tx_outputs WHERE tx_hash='0xTX1' AND output_index=0"
        ).fetchone()
        assert recipient_output[0] is not None, recipient_output

        conn.close()
        print("OK: backfill resolves lock_hash for known target-wallet addresses in "
              "cells/tx_inputs/tx_outputs, and correctly leaves un-fetched counterparties "
              "unresolved rather than guessing")


if __name__ == "__main__":
    test_lock_extraction_nested()
    test_lock_extraction_address_fallback()
    test_type_extraction_present_and_absent()
    test_previous_outpoint_candidates()
    test_since_decode()
    test_lock_family_registry()
    test_end_to_end_rebuild()
    test_since_diagnose_hexzero_not_counted_as_present()
    test_backfill_from_addresses()
    print("\nAll Phase 1 sanity tests passed.")
