"""
Sanity tests for Phase 2 (preprocess_cell_features.py) against a small,
hand-constructed cells/tx_inputs table set shaped like Phase 1's real output.
Validates topology, lifecycle (with support states), lock, type presence,
since, network, and capacity features all compute correctly and that
INSUFFICIENT_EVIDENCE fires exactly where expected.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import preprocess_cell_features as pcf

SECP = "secp256k1_blake160_sighash_all"
MULTISIG = "secp256k1_blake160_multisig_all"


def build_synthetic_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE cells (
            out_tx_hash TEXT, out_index INTEGER, lock_hash TEXT, lock_code_hash TEXT,
            lock_hash_type TEXT, lock_args TEXT, lock_family TEXT, lock_match_method TEXT,
            type_hash TEXT, type_code_hash TEXT, type_hash_type TEXT, type_args TEXT,
            has_type_script INTEGER, type_match_method TEXT, capacity INTEGER,
            address_hash TEXT, created_block_timestamp INTEGER,
            PRIMARY KEY (out_tx_hash, out_index)
        );
        CREATE TABLE tx_inputs (
            tx_hash TEXT, input_index INTEGER, prev_tx_hash TEXT, prev_index INTEGER,
            prev_match_method TEXT, lock_hash TEXT, lock_family TEXT, address_hash TEXT,
            capacity INTEGER, since_raw TEXT, since_relative INTEGER, since_metric TEXT,
            since_raw_value INTEGER, is_cellbase INTEGER, block_timestamp INTEGER,
            PRIMARY KEY (tx_hash, input_index)
        );
    """)

    # --- Wallet "alice" (ckb1qalice): looks like a scripted/bot wallet ---
    # TX_A0: funding tx creates alice's first cell (materialized locally, so
    # lifecycle IS resolvable for what alice later spends from it).
    conn.execute("INSERT INTO cells VALUES ('TX_A0', 0, 'LOCK_ALICE', null,null,null,'unknown',null,"
                 "null,null,null,null,0,'no_type_script', 100000000000, 'ckb1qalice', 1000)")
    # TX_A1..TX_A5: alice repeatedly spends her own single cell and creates
    # exactly one new output back to herself -- classic 1_to_1 periodic bot
    # shape, with a repeated non-trivial since value each time.
    prev_tx, prev_idx, ts = "TX_A0", 0, 1000
    for i in range(1, 6):
        tx = f"TX_A{i}"
        ts += 3600  # exactly hourly -- periodic
        conn.execute(
            "INSERT INTO tx_inputs VALUES (?, 0, ?, ?, 'flat_fields:x', 'LOCK_ALICE', ?, 'ckb1qalice', "
            "99000000000, '1234', 1, 'block_number', 10, 0, ?)",
            (tx, prev_tx, prev_idx, SECP, ts),
        )
        conn.execute(
            "INSERT INTO cells VALUES (?, 0, 'LOCK_ALICE', null,null,null,?,null,"
            "null,null,null,null,0,'no_type_script', 98000000000, 'ckb1qalice', ?)",
            (tx, SECP, ts),
        )
        prev_tx, prev_idx = tx, 0

    # --- Wallet "bob" (ckb1qbob): human-like, irregular, N-to-N, receives an
    # xUDT-looking cell once, uses multisig once ---
    conn.execute("INSERT INTO cells VALUES ('TX_B0', 0, 'LOCK_BOB', null,null,null,?,null,"
                 "null,null,null,null,0,'no_type_script', 50000000000, 'ckb1qbob', 2000)".replace("?", "'"+SECP+"'"))
    # Bob spends his cell plus a counterparty's cell (N inputs) into 2 outputs
    # (N_to_N shape), one of which carries a type script (xUDT-like).
    conn.execute("INSERT INTO tx_inputs VALUES ('TX_B1', 0, 'TX_B0', 0, 'flat_fields:x', 'LOCK_BOB', ?, "
                 "'ckb1qbob', 49000000000, '0x0', 0, null, 0, 0, 5000)".replace("?", "'"+SECP+"'"))
    conn.execute("INSERT INTO tx_inputs VALUES ('TX_B1', 1, 'TX_COUNTERPARTY_SRC', 0, 'flat_fields:x', "
                 "null, 'unknown', 'ckb1qcounterparty', 5000000000, '0x0', 0, null, 0, 0, 5000)")
    conn.execute("INSERT INTO cells VALUES ('TX_B1', 0, 'LOCK_BOB', null,null,null,?,null,"
                 "'TYPE_UDT_1', null,null,null,1,'nested_script:type', 40000000000, 'ckb1qbob', 5000)"
                 .replace("?", "'"+SECP+"'"))
    conn.execute("INSERT INTO cells VALUES ('TX_B1', 1, 'LOCK_OTHER', null,null,null,'unknown',null,"
                 "null,null,null,null,0,'no_type_script', 13000000000, 'ckb1qother', 5000)")

    # Bob uses multisig once, much later, irregular gap.
    conn.execute("INSERT INTO cells VALUES ('TX_B2', 0, 'LOCK_BOB_MULTISIG', null,null,null,?,null,"
                 "null,null,null,null,0,'no_type_script', 20000000000, 'ckb1qbob', 9000)"
                 .replace("?", "'"+MULTISIG+"'"))
    conn.execute("INSERT INTO tx_inputs VALUES ('TX_B3', 0, 'TX_B2', 0, 'flat_fields:x', "
                 "'LOCK_BOB_MULTISIG', ?, 'ckb1qbob', 19000000000, '0x0', 0, null, 0, 0, 55000)"
                 .replace("?", "'"+MULTISIG+"'"))
    conn.execute("INSERT INTO cells VALUES ('TX_B3', 0, 'LOCK_BOB', null,null,null,?,null,"
                 "null,null,null,null,0,'no_type_script', 18000000000, 'ckb1qbob', 55000)"
                 .replace("?", "'"+SECP+"'"))

    # --- Wallet "carol" (ckb1qcarol): touches a cellbase input directly (miner signal) ---
    conn.execute("INSERT INTO tx_inputs VALUES ('TX_C1', 0, 'CELLBASE_TX', 0, 'flat_fields:x', null, "
                 "'unknown', 'ckb1qcarol', 500000000000, '0x0', 0, null, 0, 1, 20000)")
    conn.execute("INSERT INTO cells VALUES ('TX_C1', 0, 'LOCK_CAROL', null,null,null,?,null,"
                 "null,null,null,null,0,'no_type_script', 499000000000, 'ckb1qcarol', 20000)"
                 .replace("?", "'"+SECP+"'"))

    conn.commit()
    conn.close()


def test_topology_and_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ckb_explorer.sqlite"
        build_synthetic_db(db_path)
        addresses = ["ckb1qalice", "ckb1qbob", "ckb1qcarol"]

        conn = sqlite3.connect(str(db_path))
        tx_inputs, cells = pcf.load_core_tables(conn)
        conn.close()

        tx_shape = pcf.compute_tx_shape(tx_inputs, cells)
        topo = pcf.per_wallet_topology(addresses, tx_inputs, cells, tx_shape)

        # Alice: every tx is a 1-in-1-out spend-and-return -> 1_to_1 dominant.
        assert topo.loc["ckb1qalice", "shape_1_to_1_ratio"] == 1.0, topo.loc["ckb1qalice"]
        # Bob's TX_B1 is 2-in-2-out -> n_to_n.
        assert topo.loc["ckb1qbob", "shape_n_to_n_ratio"] > 0, topo.loc["ckb1qbob"]
        print("OK: topology shapes correct (alice 1_to_1, bob has n_to_n)")

        lifecycle = pcf.per_wallet_lifecycle(addresses, tx_inputs, cells)
        # Alice's 5 spends should ALL resolve lifecycle (every prev tx is
        # locally materialized in this synthetic set) and all be exactly
        # 3600s -- a dead giveaway of scripted/bot timing.
        assert lifecycle.loc["ckb1qalice", "lifecycle_state"] == "OK", lifecycle.loc["ckb1qalice"]
        assert lifecycle.loc["ckb1qalice", "cell_lifetime_mean_s"] == 3600.0, lifecycle.loc["ckb1qalice"]
        assert lifecycle.loc["ckb1qalice", "cell_lifetime_cv"] == 0.0, "bot-like: zero variance expected"
        # Carol has only 1 input (cellbase) and its prev tx (CELLBASE_TX) is
        # never materialized -> INSUFFICIENT_EVIDENCE, not a fake zero.
        assert lifecycle.loc["ckb1qcarol", "lifecycle_state"] == "INSUFFICIENT_EVIDENCE", lifecycle.loc["ckb1qcarol"]
        print("OK: lifecycle resolved correctly for alice (bot-like zero variance), "
              "correctly INSUFFICIENT_EVIDENCE for carol (unresolvable cellbase source)")


def test_lock_type_since_cellbase():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ckb_explorer.sqlite"
        build_synthetic_db(db_path)
        addresses = ["ckb1qalice", "ckb1qbob", "ckb1qcarol"]
        conn = sqlite3.connect(str(db_path))
        tx_inputs, cells = pcf.load_core_tables(conn)
        conn.close()

        lock = pcf.per_wallet_lock(addresses, tx_inputs, cells)
        assert lock.loc["ckb1qbob", "n_distinct_lock_hashes"] >= 2, lock.loc["ckb1qbob"]
        assert lock.loc["ckb1qbob", "multisig_usage_ratio"] > 0, lock.loc["ckb1qbob"]
        assert lock.loc["ckb1qalice", "multisig_usage_ratio"] == 0.0, lock.loc["ckb1qalice"]
        print("OK: lock family / multisig usage / distinct-lock-count detected correctly for bob vs alice")

        type_presence = pcf.per_wallet_type_presence(addresses, cells)
        assert type_presence.loc["ckb1qbob", "has_type_script_ratio"] > 0, type_presence.loc["ckb1qbob"]
        assert type_presence.loc["ckb1qalice", "has_type_script_ratio"] == 0.0, type_presence.loc["ckb1qalice"]
        print("OK: type-script (asset) presence detected for bob's xUDT-like cell, absent for alice")

        since = pcf.per_wallet_since(addresses, tx_inputs)
        assert since.loc["ckb1qalice", "since_state"] == "OK"
        assert since.loc["ckb1qalice", "uses_since_ratio"] == 1.0, since.loc["ckb1qalice"]
        assert since.loc["ckb1qalice", "repeated_since_value_ratio"] == 1.0, since.loc["ckb1qalice"]
        assert since.loc["ckb1qbob", "since_state"] == "INSUFFICIENT_EVIDENCE"  # only 2 inputs, min is 3
        print("OK: since usage -- alice's repeated fixed-value since flagged (bot signal), "
              "bob correctly INSUFFICIENT_EVIDENCE with too few inputs")

        cellbase = pcf.per_wallet_cellbase_touch(addresses, tx_inputs)
        assert cellbase.loc["ckb1qcarol", "touches_cellbase_directly"] == True, cellbase.loc["ckb1qcarol"]
        assert cellbase.loc["ckb1qalice", "touches_cellbase_directly"] == False
        print("OK: direct cellbase touch detected for carol only")


def test_network_and_capacity():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ckb_explorer.sqlite"
        build_synthetic_db(db_path)
        addresses = ["ckb1qalice", "ckb1qbob", "ckb1qcarol"]
        conn = sqlite3.connect(str(db_path))
        tx_inputs, cells = pcf.load_core_tables(conn)
        conn.close()

        id_map = pcf.build_wallet_identity_map(addresses, tx_inputs, cells)
        assert id_map["ckb1qalice"] == "LOCK_ALICE"
        network = pcf.per_wallet_network(addresses, tx_inputs, cells, id_map)
        # Bob's TX_B1 involves a counterparty and a third-party recipient ->
        # at least 2 distinct counterparties across in+out.
        assert network.loc["ckb1qbob", "unique_counterparties_out_cell"] >= 1
        assert network.loc["ckb1qbob", "unique_counterparties_in_cell"] >= 1
        print("OK: network counterparty detection works with lock-hash-aware identity")

        capacity = pcf.per_wallet_capacity(addresses, tx_inputs, cells)
        assert capacity.loc["ckb1qalice", "sent_capacity_ckb_cell"] > 0
        assert capacity.loc["ckb1qalice", "received_capacity_ckb_cell"] > 0
        print("OK: capacity aggregation computes sent/received/net correctly")


def test_full_assemble_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ckb_explorer.sqlite"
        build_synthetic_db(db_path)
        addresses = ["ckb1qalice", "ckb1qbob", "ckb1qcarol", "ckb1qneverseen"]
        df = pcf.assemble(addresses, db_path)
        assert len(df) == 4
        assert "ckb1qneverseen" in df.index
        # A wallet with zero rows anywhere should be all-NaN/INSUFFICIENT_EVIDENCE,
        # not crash the pipeline.
        assert pd.isna(df.loc["ckb1qneverseen", "n_tx_cell_layer"])
        pcf.print_support_summary(df)
        print("\nOK: full assemble() runs end-to-end for a mixed population including "
              "a wallet with no Cell-layer data at all")


if __name__ == "__main__":
    test_topology_and_lifecycle()
    test_lock_type_since_cellbase()
    test_network_and_capacity()
    test_full_assemble_end_to_end()
    print("\nAll Phase 2 sanity tests passed.")
