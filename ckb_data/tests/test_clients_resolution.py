from __future__ import annotations

import json
import sqlite3
import unittest

from ckb_clients import (ClientUnavailable, binary_search_block,
                         consensus_median_time, resolve_observation_boundaries)
from ckb_native import install_schema, normalize_transaction, persist_transaction
from input_resolver import resolve_transaction_inputs
from ckb_data.tests.test_ckb_native import LOCK_A, LOCK_B, cell, payload


class BlockClient:
    def __init__(self, timestamps): self.timestamps = timestamps
    def get_tip_block_number(self): return len(self.timestamps) - 1
    def get_block_by_number(self, number): return {"header": {"timestamp": hex(self.timestamps[number] * 1000)}}
    def resolve_block_for_timestamp(self, timestamp, side): return binary_search_block(self, timestamp, side=side)


class DownClient:
    def resolve_block_for_timestamp(self, timestamp, side): raise ClientUnavailable("down")


class TxClient:
    def __init__(self, result=None, unavailable=False): self.result, self.unavailable = result, unavailable
    def get_transaction(self, tx_hash):
        if self.unavailable: raise ClientUnavailable("down")
        return self.result


def unresolved_spend():
    raw = {"previous_output": {"tx_hash": "0xprevious", "index": 0}}
    return normalize_transaction(payload([raw], [cell(90, LOCK_B)], fee=10, tx_hash="0xspend"))


class BoundaryTests(unittest.TestCase):
    def test_canonical_start_and_end_boundaries(self):
        timestamps = [1_700_000_000 + height * 10 for height in range(100)]
        client = BlockClient(timestamps)
        target = consensus_median_time(client, 60)
        start = binary_search_block(client, target, side="start")
        end = binary_search_block(client, target, side="end")
        self.assertLess(consensus_median_time(client, start - 1), target)
        self.assertGreaterEqual(consensus_median_time(client, start), target)
        self.assertLessEqual(consensus_median_time(client, end), target)
        self.assertGreater(consensus_median_time(client, end + 1), target)

    def test_rpc_then_explorer_fallback_and_unresolved(self):
        timestamps = [1_700_000_000 + height * 10 for height in range(100)]
        result = resolve_observation_boundaries(1_700_000_200, 1_700_000_600,
                                                rpc=DownClient(), explorer=BlockClient(timestamps))
        self.assertEqual(result["boundary_resolution_source"], "explorer")
        result = resolve_observation_boundaries(1_700_000_200, 1_700_000_600,
                                                rpc=DownClient(), explorer=DownClient())
        self.assertEqual(result["boundary_resolution_status"], "unresolved")


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        install_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def rpc_payload(self):
        return {"transaction": {"outputs": [{"capacity": hex(100), "lock": LOCK_A, "type": None}],
                                "outputs_data": ["0x"]}}

    def explorer_payload(self):
        return payload([cell(110, LOCK_B)], [cell(100, LOCK_A)], fee=10,
                       tx_hash="0xprevious")

    def test_normalized_local_cells(self):
        persist_transaction(self.conn, normalize_transaction(self.explorer_payload()))
        tx = unresolved_spend()
        counts = resolve_transaction_inputs(self.conn, tx, TxClient(unavailable=True), TxClient(unavailable=True))
        self.assertEqual(counts["normalized_local_cells"], 1)

    def test_raw_cache(self):
        self.conn.execute("CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT)")
        self.conn.execute("INSERT INTO raw_transactions VALUES (?, ?)",
                          ("0xprevious", json.dumps(self.explorer_payload())))
        tx = unresolved_spend()
        counts = resolve_transaction_inputs(self.conn, tx, TxClient(unavailable=True), TxClient(unavailable=True))
        self.assertEqual(counts["raw_cached_transaction"], 1)

    def test_rpc(self):
        self.conn.execute("CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT)")
        tx = unresolved_spend()
        counts = resolve_transaction_inputs(self.conn, tx, TxClient(self.rpc_payload()), TxClient(unavailable=True))
        self.assertEqual(counts["ckb_rpc"], 1)

    def test_explorer_fallback(self):
        self.conn.execute("CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT)")
        tx = unresolved_spend()
        counts = resolve_transaction_inputs(self.conn, tx, TxClient(unavailable=True), TxClient(self.explorer_payload()))
        self.assertEqual(counts["explorer"], 1)

    def test_unresolved(self):
        self.conn.execute("CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT)")
        tx = unresolved_spend()
        counts = resolve_transaction_inputs(self.conn, tx, TxClient(unavailable=True), TxClient(unavailable=True))
        self.assertEqual(counts["unresolved"], 1)
        self.assertEqual(tx["inputs"][0]["resolution_status"], "failed_to_fetch")


if __name__ == "__main__": unittest.main()
