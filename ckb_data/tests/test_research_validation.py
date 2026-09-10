from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

<<<<<<< HEAD
from ckb_clients import ClientUnavailable, ExplorerClient, binary_search_explorer_block
from ckb_native import install_schema, normalize_transaction, persist_transaction
from features.pipeline import assess_observation
from input_resolver import resolve_transaction_inputs
from research_cache import CacheStats, install_statistics_schema, persist_statistics
from research_manifest import build_manifest, sampling_stratum
from ckb_data.tests.test_ckb_native import LOCK_A, LOCK_B, cell, payload


class ManifestTests(unittest.TestCase):
=======
from wallet_intelligence.clients import ClientUnavailable, ExplorerClient, binary_search_explorer_block
from wallet_intelligence.normalization import install_schema, normalize_transaction, persist_transaction
from research_pipeline.dataset_features.pipeline import assess_observation
from wallet_intelligence.resolution import resolve_transaction_inputs
from wallet_intelligence.cache import CacheStats, install_statistics_schema, persist_statistics
from research_manifest import build_manifest, sampling_stratum
from wallet_intelligence.test_support import LOCK_A, LOCK_B, cell, payload


class ManifestTests(unittest.TestCase):
    def test_offline_verifier_discovers_actual_test_directory(self):
        verifier = Path(__file__).resolve().parents[2] / "scripts/verify_final_research.py"
        source = verifier.read_text(encoding="utf-8")
        self.assertIn('"ckb_data/tests"', source)
        self.assertNotIn('discover", "-s", "ckb_data",', source)

>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6
    def test_stratum_boundaries_and_unknown(self):
        values = [(None, "unknown"), (0, "unknown"), (1, "1-10"), (10, "1-10"),
                  (11, "11-50"), (50, "11-50"), (51, "51-200"),
                  (200, "51-200"), (201, "201-500"), (500, "201-500"),
                  (501, "501-1000"), (1000, "501-1000"),
                  (1001, "1001-5000"), (5000, "1001-5000"), (5001, "5000+")]
        for value, expected in values:
            self.assertEqual(sampling_stratum(value), expected)

    def test_dedup_sources_and_legacy_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ckb_data/ckb_data_v2/provenance").mkdir(parents=True)
            (root / "ckb_data/ckb_features").mkdir(parents=True)
            (root / "data/real/human_like").mkdir(parents=True)
            address = "ckb1fixture"
            (root / "ckb_data/addresses.txt").write_text(address + "\n" + address + "\n")
            (root / "data/real/human_like/manifest.json").write_text(json.dumps([
                {"index": 0, "address": address, "label_source": "human_like", "tx_count": 9}
            ]))
            (root / "data/real/human_like/addr_0.json").write_text(
                json.dumps({"address": address}) + "\n")
            records, summary = build_manifest(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["legacy_proxy_label"], "human_like")
            self.assertEqual(records[0]["sampling_stratum"], "1-10")
            self.assertEqual(records[0]["evidence_tier"], "B")
            self.assertGreater(summary["duplicate_occurrences"], 0)


class LocalNormalizationTests(unittest.TestCase):
    def test_historical_root_payload_preserves_address_identifier(self):
        raw = {
            "transaction_hash": "0xlocal", "block_number": "10",
            "block_timestamp": "1786000000000", "transaction_fee": "10",
            "display_inputs": [{"capacity": "100", "address_hash": "ckb1target",
                                "generated_tx_hash": "0xprevious", "cell_index": "0"}],
            "display_outputs": [{"capacity": "90", "address_hash": "ckb1other",
                                 "cell_index": "0"}],
        }
        tx = normalize_transaction(raw, target_lock_hash="ckb1target")
        self.assertEqual(tx["tx_hash"], "0xlocal")
        self.assertEqual(tx["inputs"][0]["resolved_lock_identifier"], "ckb1target")
        self.assertTrue(tx["inputs"][0]["target_controls_input"])
        self.assertEqual(tx["outputs"][0]["lock_identifier"], "ckb1other")
        conn = sqlite3.connect(":memory:")
        install_schema(conn)
        persist_transaction(conn, tx)
        self.assertEqual(conn.execute("SELECT lock_identifier FROM cells").fetchone()[0],
                         "ckb1other")
        conn.close()


class CacheContractTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT, "
                          "fetched_at INTEGER DEFAULT 0, source_kind TEXT DEFAULT 'test')")
        install_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_normalized_cache_prevents_remote_call(self):
        previous = payload([cell(110, LOCK_B)], [cell(100, LOCK_A)], fee=10,
                           tx_hash="0xprevious")
        persist_transaction(self.conn, normalize_transaction(previous))
        spend = normalize_transaction(payload(
            [{"previous_output": {"tx_hash": "0xprevious", "index": 0}}],
            [cell(90, LOCK_B)], fee=10, tx_hash="0xspend"))

        class Never:
            def get_transaction(self, tx_hash):
                raise AssertionError("remote request was not allowed")

        stats = CacheStats()
        counts = resolve_transaction_inputs(self.conn, spend, explorer=Never(), stats=stats)
        self.assertEqual(counts["normalized_local_cells"], 1)
        self.assertEqual(stats.snapshot()["explorer_requests"], 0)

    def test_raw_previous_output_becomes_durable_normalized_cell(self):
        previous = payload([cell(110, LOCK_B)], [cell(100, LOCK_A)], fee=10,
                           tx_hash="0xprevious")
        self.conn.execute("INSERT INTO raw_transactions (tx_hash,raw_json) VALUES (?,?)",
                          ("0xprevious", json.dumps(previous)))
        spend = normalize_transaction(payload(
            [{"previous_output": {"tx_hash": "0xprevious", "index": 0}}],
            [cell(90, LOCK_B)], fee=10, tx_hash="0xspend"))
        resolve_transaction_inputs(self.conn, spend, explorer=None, stats=CacheStats())
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM cells WHERE creating_tx_hash='0xprevious' AND output_index=0"
        ).fetchone())

    def test_statistics_are_durable(self):
        install_statistics_schema(self.conn)
        persist_statistics(self.conn, "wallet", "ckb1fixture", CacheStats().snapshot())
        self.assertEqual(self.conn.execute("SELECT address FROM cache_statistics").fetchone()[0],
                         "ckb1fixture")

    def test_explorer_retry_rate_limit_and_success_counters(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"data":{"attributes":{"tip_block_number":"12"}}}'

        limited = urllib.error.HTTPError("https://example", 429, "limited", {}, None)
        stats = CacheStats()
        client = ExplorerClient("https://example", stats=stats, max_retries=1)
        with mock.patch("urllib.request.urlopen", side_effect=[limited, Response()]), \
                mock.patch("time.sleep"):
            self.assertEqual(client.get_tip_block_number(), 12)
        values = stats.snapshot()
        self.assertEqual(values["explorer_requests"], 2)
        self.assertEqual(values["explorer_successes"], 1)
        self.assertEqual(values["explorer_retries"], 1)
        self.assertEqual(values["rate_limit_events"], 1)

    def test_explorer_failure_counter(self):
        stats = CacheStats()
        client = ExplorerClient("https://example", stats=stats, max_retries=0)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(ClientUnavailable):
                client.get_tip_block_number()
        self.assertEqual(stats.snapshot()["explorer_failures"], 1)

    def test_bounded_explorer_boundary(self):
        class Blocks:
            def __init__(self): self.calls = 0
            def get_tip_block_number(self): return 999
            def get_block_by_number(self, number):
                self.calls += 1
                return {"data": {"attributes": {"timestamp": (1_700_000_000 + number * 10) * 1000}}}
        blocks = Blocks()
        self.assertEqual(binary_search_explorer_block(blocks, 1_700_005_000, side="start"), 500)
        self.assertLess(blocks.calls, 20)


class LeakageTests(unittest.TestCase):
    def test_legacy_metadata_cannot_change_features_or_rules(self):
        txs = []
        for index in range(10):
            raw = payload(
                [cell(100, LOCK_A)], [cell(90, LOCK_B)], fee=10,
                tx_hash=f"0x{index}")
            raw["data"]["attributes"]["block_timestamp"] = (1_000 + index * 600) * 1000
            tx = normalize_transaction(raw, target_lock_hash=None)
            txs.append(tx)
        base = {"transactions": txs, "metadata": {"detail_complete": True,
                "input_resolution_complete": True, "detail_coverage_ratio": 1.0,
                "input_resolution_ratio": 1.0}}
        polluted = json.loads(json.dumps(base))
        polluted["metadata"].update({"legacy_proxy_label": "bot_like",
                                     "lifetime_tx_count": 999999,
                                     "sampling_stratum": "5000+",
                                     "predicted_segment": "anything", "cluster_id": 4})
        self.assertEqual(assess_observation(base), assess_observation(polluted))


if __name__ == "__main__":
    unittest.main()
