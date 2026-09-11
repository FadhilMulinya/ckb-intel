from __future__ import annotations

import sqlite3
import unittest

from ckb_native import (
    OBSERVATION_CONTRACT_VERSION,
    ObservationContract,
    install_schema,
    normalize_transaction,
    persist_transaction,
    resolve_inputs_from_cells,
    script_hash,
)


LOCK_A = {"code_hash": "0x" + "11" * 32, "hash_type": "type", "args": "0xaaaa"}
LOCK_B = {"code_hash": "0x" + "22" * 32, "hash_type": "type", "args": "0xbbbb"}
LOCK_C = {"code_hash": "0x" + "33" * 32, "hash_type": "type", "args": "0xcccc"}
TYPE_X = {"code_hash": "0x" + "44" * 32, "hash_type": "type", "args": "0x1234"}


def cell(capacity, lock, *, tx="0xprev", index=0, type_script=None, data="0x"):
    return {
        "capacity": str(capacity), "lock": lock, "type": type_script,
        "output_data": data,
        "previous_output": {"tx_hash": tx, "index": index},
    }


def payload(inputs, outputs, fee=None, tx_hash="0xtx"):
    attrs = {
        "transaction_hash": tx_hash,
        "block_number": "100",
        "block_timestamp": "1700000000000",
        "transaction_index": "2",
        "display_inputs": inputs,
        "display_outputs": outputs,
    }
    if fee is not None:
        attrs["transaction_fee"] = str(fee)
    return {"data": {"id": tx_hash, "attributes": attrs}}


class NativeTransactionTests(unittest.TestCase):
    def test_single_input_participation_and_conservation(self):
        tx = normalize_transaction(
            payload([cell(100, LOCK_A)], [cell(90, LOCK_B)], fee=10),
            target_lock_hash=script_hash(LOCK_A),
        )
        self.assertTrue(tx["inputs"][0]["target_controls_input"])
        self.assertFalse(tx["outputs"][0]["target_controls_output"])
        self.assertEqual(tx["fee_shannon"], 10)
        self.assertEqual(tx["capacity_conservation_status"], "complete")

    def test_multiple_inputs_one_output_does_not_duplicate_capacity(self):
        tx = normalize_transaction(payload(
            [cell(60, LOCK_A, index=0), cell(50, LOCK_B, index=1)],
            [cell(100, LOCK_C)], fee=10))
        self.assertEqual(tx["input_capacity_shannon"], 110)
        self.assertEqual(tx["output_capacity_shannon"], 100)
        self.assertEqual(tx["pairwise_value_attribution"], "NOT_ESTABLISHED")
        self.assertNotIn("edges", tx)

    def test_one_input_multiple_outputs_preserves_fanout(self):
        tx = normalize_transaction(payload(
            [cell(100, LOCK_A)], [cell(40, LOCK_B), cell(50, LOCK_C)], fee=10))
        self.assertEqual(len(tx["outputs"]), 2)
        self.assertEqual(sum(o["capacity"] for o in tx["outputs"]), 90)

    def test_multiple_inputs_multiple_outputs_has_no_pairwise_mapping(self):
        tx = normalize_transaction(payload(
            [cell(70, LOCK_A), cell(40, LOCK_B)],
            [cell(30, LOCK_A), cell(70, LOCK_C)], fee=10))
        self.assertEqual(tx["pairwise_value_attribution"], "NOT_ESTABLISHED")
        self.assertEqual(len(tx["inputs"]), 2)
        self.assertEqual(len(tx["outputs"]), 2)

    def test_same_lock_output_is_control_not_claimed_change(self):
        tx = normalize_transaction(payload(
            [cell(100, LOCK_A)], [cell(30, LOCK_A), cell(60, LOCK_B)], fee=10),
            target_lock_hash=script_hash(LOCK_A))
        self.assertTrue(tx["outputs"][0]["target_controls_output"])
        self.assertNotIn("is_change", tx["outputs"][0])

    def test_missing_previous_output_is_explicitly_unresolved(self):
        unresolved = {"previous_output": {"tx_hash": "0xmissing", "index": 7}}
        tx = normalize_transaction(payload([unresolved], [cell(90, LOCK_B)]))
        self.assertEqual(tx["inputs"][0]["resolution_status"], "incomplete")
        self.assertEqual(tx["inputs"][0]["previous_output_index"], 7)
        self.assertIsNone(tx["input_capacity_shannon"])

    def test_cellbase_input_is_not_applicable_to_previous_output_resolution(self):
        cellbase = {"from_cellbase": True, "generated_tx_hash": "0xcellbase",
                    "target_block_number": "20025197"}
        tx = normalize_transaction(payload([cellbase], [cell(100, LOCK_A)]))
        self.assertTrue(tx["is_cellbase"])
        self.assertEqual(tx["inputs"][0]["resolution_status"], "not_applicable")
        self.assertEqual(tx["inputs"][0]["resolution_source"], "cellbase")
        self.assertEqual(tx["capacity_conservation_status"], "not_applicable")

    def test_previous_output_resolves_from_normalized_cache(self):
        conn = sqlite3.connect(":memory:")
        install_schema(conn)
        previous = normalize_transaction(payload(
            [cell(110, LOCK_A)], [cell(100, LOCK_B)], fee=10, tx_hash="0xprevious"))
        persist_transaction(conn, previous)
        unresolved = {"previous_output": {"tx_hash": "0xprevious", "index": 0}}
        spending = normalize_transaction(payload(
            [unresolved], [cell(90, LOCK_C)], fee=10, tx_hash="0xspending"))
        self.assertEqual(resolve_inputs_from_cells(conn, spending), 1)
        self.assertEqual(spending["inputs"][0]["resolved_capacity"], 100)
        self.assertEqual(spending["fee_shannon"], 10)

    def test_type_script_and_data_survive_round_trip(self):
        tx = normalize_transaction(payload(
            [cell(100, LOCK_A)],
            [cell(90, LOCK_B, type_script=TYPE_X, data="0xdeadbeef")], fee=10))
        self.assertEqual(tx["outputs"][0]["type_script"], TYPE_X)
        self.assertEqual(tx["outputs"][0]["output_data"], "0xdeadbeef")
        conn = sqlite3.connect(":memory:")
        install_schema(conn)
        persist_transaction(conn, tx)
        row = conn.execute("SELECT type_script_hash, output_data FROM cells").fetchone()
        self.assertEqual(row, (script_hash(TYPE_X), "0xdeadbeef"))

    def test_conservation_mismatch_is_failed(self):
        tx = normalize_transaction(payload(
            [cell(100, LOCK_A)], [cell(90, LOCK_B)], fee=9))
        self.assertEqual(tx["capacity_conservation_status"], "failed")


class ObservationContractTests(unittest.TestCase):
    def test_exact_thirty_day_window(self):
        observation = ObservationContract(
            address="ckb1fixture", canonical_lock_identifier=script_hash(LOCK_A),
            window_start_timestamp=1_700_000_000,
            window_end_timestamp=1_700_000_000 + 30 * 86400,
        )
        self.assertEqual(observation.as_record()["observation_contract_version"],
                         OBSERVATION_CONTRACT_VERSION)

    def test_non_thirty_day_window_rejected(self):
        with self.assertRaises(ValueError):
            ObservationContract(
                address="ckb1fixture", canonical_lock_identifier=script_hash(LOCK_A),
                window_start_timestamp=1, window_end_timestamp=2)


if __name__ == "__main__":
    unittest.main()
