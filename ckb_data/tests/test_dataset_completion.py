import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wallet_intelligence.collection import Store
from dataset_completion import (
    OBSERVATION_WINDOW_ID,
    POPULATION_VERSION,
    SCHEDULER_SCHEMA,
    export_feature_datasets,
    finalize_exhausted_states,
    flatten_feature_row,
    freeze_contracts,
    next_wallets,
    population_hash,
    recover_interrupted_state,
    run_batch,
    safety_check,
    stable_population_rows,
)
from wallet_intelligence.cache import CacheStats
from validate_existing_wallets import network_safe_address, sensitivity, validate_wallet


def manifest_item(address="wallet-a", stratum="1-10"):
    return {
        "address": address,
        "canonical_lock_hash": f"lock-{address}",
        "source_dataset": ["source-b", "source-a"],
        "source_run": ["run-1"],
        "legacy_proxy_label": "human",
        "lifetime_tx_count": 5,
        "sampling_stratum": stratum,
    }


class DatasetCompletionTests(unittest.TestCase):
    def test_store_context_manager_closes_connection_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            with Store(Path(temporary) / "cache.sqlite") as store:
                store.conn.execute("SELECT 1").fetchone()
            store.close()
            with self.assertRaises(sqlite3.ProgrammingError):
                store.conn.execute("SELECT 1")

    def test_population_hash_is_order_independent_and_metadata_sensitive(self):
        first = manifest_item("a")
        second = manifest_item("b")
        baseline = population_hash(stable_population_rows([first, second]))
        self.assertEqual(baseline,
                         population_hash(stable_population_rows([second, first])))
        second["sampling_stratum"] = "11-50"
        self.assertNotEqual(baseline,
                            population_hash(stable_population_rows([first, second])))

    def test_population_creation_timestamp_is_stable_across_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "cache.sqlite")
            item = manifest_item()
            first = freeze_contracts(store.conn, [item], Path(temporary) / "out")
            second = freeze_contracts(store.conn, [item], Path(temporary) / "out")
            self.assertEqual(first["creation_timestamp"], second["creation_timestamp"])
            self.assertIsInstance(second["source_dataset_versions"], dict)
            store.close()

    def test_scheduler_prioritizes_local_then_partial_then_full(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEDULER_SCHEMA)
        for address, category, state in (
                ("full", "NEEDS_FULL_REFILL", "NOT_STARTED"),
                ("partial", "NEEDS_PARTIAL_REFILL", "PARTIAL"),
                ("local", "COMPLETE_LOCAL", "NOT_STARTED")):
            conn.execute("""INSERT INTO wallet_collection_state
                (address,population_version,observation_window_id,completion_category,
                 collection_state,evidence_state,updated_at) VALUES (?,?,?,?,?,?,?)""",
                         (address, POPULATION_VERSION, OBSERVATION_WINDOW_ID, category,
                          state, "UNRESOLVED", "now"))
        self.assertEqual(next_wallets(conn, 3), ["local", "full"])
        conn.execute("UPDATE wallet_collection_state SET attempt_count=3 WHERE address='partial'")
        self.assertEqual(next_wallets(conn, 3, max_attempts=3), ["local", "full"])
        conn.close()

    def test_stale_in_progress_state_is_recovered(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEDULER_SCHEMA)
        conn.execute("""INSERT INTO wallet_collection_state
            (address,population_version,observation_window_id,completion_category,
             collection_state,evidence_state,updated_at) VALUES (?,?,?,?,?,?,?)""",
            ("wallet", POPULATION_VERSION, OBSERVATION_WINDOW_ID,
             "NEEDS_FULL_REFILL", "IN_PROGRESS", "UNRESOLVED", "now"))
        conn.execute("INSERT INTO batch_checkpoints VALUES (?,?,?,?,?,?,?,?,?)",
                     ("batch", POPULATION_VERSION, OBSERVATION_WINDOW_ID, "now", None,
                      "IN_PROGRESS", 1, None, None))
        recovered = recover_interrupted_state(conn)
        self.assertEqual(recovered, {"recovered_wallets": 1, "paused_batches": ["batch"]})
        self.assertEqual(conn.execute("SELECT collection_state FROM wallet_collection_state")
                         .fetchone()[0], "PARTIAL")
        self.assertEqual(conn.execute("SELECT status FROM batch_checkpoints").fetchone()[0],
                         "PAUSED")
        conn.close()

    def test_retry_exhausted_partial_becomes_explicit_failure(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEDULER_SCHEMA)
        conn.execute("""INSERT INTO wallet_collection_state
            (address,population_version,observation_window_id,completion_category,
             collection_state,evidence_state,attempt_count,last_error,updated_at)
             VALUES (?,?,?,?,?,?,?,?,?)""",
            ("wallet", POPULATION_VERSION, OBSERVATION_WINDOW_ID,
             "NEEDS_FULL_REFILL", "PARTIAL", "PARTIAL", 3, None, "now"))
        self.assertEqual(finalize_exhausted_states(conn, 3), 1)
        state, evidence, error = conn.execute(
            "SELECT collection_state,evidence_state,last_error FROM wallet_collection_state"
        ).fetchone()
        self.assertEqual((state, evidence), ("FAILED_RETRY_EXHAUSTED", "PARTIAL"))
        self.assertIn("exhausted", error)
        conn.close()

    def test_safety_stop_on_abnormal_request_failure_rate(self):
        conn = sqlite3.connect(":memory:")
        summary = {"statistics": {"explorer_requests": 10, "explorer_successes": 8,
                                  "explorer_failures": 2,
                                  "rate_limit_events": 0},
                   "transaction_bearing_wallets": 0, "mean_input_resolution": 1,
                   "detail_incomplete": 0, "wallets_attempted": 10,
                   "boundary_inconsistent": 0, "global_request_failures": 2,
                   "wallet_network_failures": 0, "parser_failures": 0}
        config = {"max_global_failure_rate": .10, "max_rate_limit_events": 3,
                  "max_rate_limit_rate": .20, "outage_min_wallets": 5,
                  "outage_wallet_failure_rate": .80, "max_parser_failure_rate": .10,
                  "minimum_input_resolution": .95, "max_detail_failure_rate": .10}
        self.assertIn("global request failure rate", safety_check(conn, summary, config))
        conn.close()

    def test_individual_threshold_sweeps_are_present(self):
        result = {"features": {
            "temporal": {"values": {"periodicity_strength": .8,
                                     "phase_stability": .8, "interarrival_cv": .2}},
            "topology": {"values": {"fanout_transaction_ratio": .5,
                                     "mean_external_output_locks": 3,
                                     "fanin_transaction_ratio": .5,
                                     "mean_external_input_locks": 3,
                                     "topology_repeat_ratio": .8}},
            "templates": {"values": {"template_repeat_ratio": .8}},
        }}
        swept = sensitivity(result)
        self.assertEqual(set(swept["PERIODIC_EXECUTION"]["individual_cutoffs"]),
                         {"periodicity_strength", "phase_stability", "interarrival_cv"})
        self.assertTrue(all(len(item["lower_default_upper"]) == 3 for item in
                            swept["PERIODIC_EXECUTION"]["individual_cutoffs"].values()))

    def test_invalid_frozen_address_is_rejected_before_network(self):
        self.assertFalse(network_safe_address("ckb1valid\tannotation"))
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "cache.sqlite")
            record = manifest_item("ckb1valid\tannotation")
            class NoNetwork:
                def get_address_transactions(self, *_args, **_kwargs):
                    self.fail("network must not be called")
            with self.assertRaisesRegex(ValueError, "invalid frozen wallet address"):
                validate_wallet(store, record, NoNetwork(), CacheStats(), {
                    "window_start_block": 20_025_197,
                    "window_end_block": 20_311_450,
                    "boundary_resolution_status": "complete",
                })
            store.close()

    def test_interrupted_batch_is_closed_and_wallet_is_resumable(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "cache.sqlite")
            store.conn.executescript(SCHEDULER_SCHEMA)
            item = manifest_item("ckb1wallet")
            store.conn.execute("""INSERT INTO wallet_collection_state
                (address,population_version,observation_window_id,completion_category,
                 collection_state,evidence_state,updated_at) VALUES (?,?,?,?,?,?,?)""",
                (item["address"], POPULATION_VERSION, OBSERVATION_WINDOW_ID,
                 "NEEDS_FULL_REFILL", "NOT_STARTED", "UNRESOLVED", "now"))
            config = {"max_global_failure_rate": .10, "max_rate_limit_events": 3,
                      "max_rate_limit_rate": .20, "outage_min_wallets": 5,
                      "outage_wallet_failure_rate": .80, "max_parser_failure_rate": .10,
                      "minimum_input_resolution": .95, "max_detail_failure_rate": .10,
                      "max_wallet_attempts": 3}
            with patch("dataset_completion.validate_wallet", side_effect=KeyboardInterrupt):
                summary = run_batch(store, {item["address"]: item}, [item["address"]],
                                    object(), CacheStats(), Path(temporary), config)
            self.assertIn("interrupted", summary["safety_stop"])
            self.assertEqual(store.conn.execute(
                "SELECT collection_state FROM wallet_collection_state").fetchone()[0], "PARTIAL")
            self.assertEqual(store.conn.execute(
                "SELECT status FROM batch_checkpoints").fetchone()[0], "PAUSED")
            store.close()

    def test_wallet_specific_failures_do_not_stop_batch_and_preserve_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "cache.sqlite")
            store.conn.executescript(SCHEDULER_SCHEMA)
            items = [manifest_item("ckb1first"), manifest_item("ckb1second")]
            for item in items:
                store.conn.execute("""INSERT INTO wallet_collection_state
                    (address,population_version,observation_window_id,completion_category,
                     collection_state,evidence_state,updated_at) VALUES (?,?,?,?,?,?,?)""",
                    (item["address"], POPULATION_VERSION, OBSERVATION_WINDOW_ID,
                     "NEEDS_FULL_REFILL", "NOT_STARTED", "UNRESOLVED", "now"))
            stats = CacheStats()

            def failed_listing(*_args):
                stats.increment("explorer_requests", 4)
                stats.increment("explorer_retries", 3)
                stats.increment("explorer_failures")
                return {
                    "observation": {
                        "listing_complete": False, "detail_complete": True,
                        "input_resolution_complete": None,
                        "boundary_resolution_status": "complete",
                        "window_start_block": 20_025_197,
                        "window_end_block": 20_311_450,
                        "transactions_observed": 0,
                        "detail_coverage_ratio": None,
                        "input_resolution_ratio": None,
                    },
                    "features": {name: {"support_state": "INSUFFICIENT_EVIDENCE"}
                                 for name in ("temporal", "topology", "templates",
                                              "scripts", "capacity")},
                    "listing_error": "Explorer timed out",
                }

            config = {"max_global_failure_rate": .10, "max_rate_limit_events": 3,
                      "max_rate_limit_rate": .20, "outage_min_wallets": 5,
                      "outage_wallet_failure_rate": .80, "max_parser_failure_rate": .10,
                      "minimum_input_resolution": .95, "max_detail_failure_rate": .10,
                      "max_wallet_attempts": 3}
            with patch("dataset_completion.validate_wallet", side_effect=failed_listing) as mocked:
                summary = run_batch(store, {item["address"]: item for item in items},
                                    [item["address"] for item in items], object(), stats,
                                    Path(temporary), config)
            self.assertEqual(mocked.call_count, 2)
            self.assertIsNone(summary["safety_stop"])
            state, error = store.conn.execute(
                "SELECT collection_state,last_error FROM wallet_collection_state "
                "WHERE address='ckb1first'").fetchone()
            self.assertEqual((state, error),
                             ("FAILED_RETRY_EXHAUSTED", "Explorer timed out"))
            self.assertEqual(store.conn.execute(
                "SELECT collection_state FROM wallet_collection_state "
                "WHERE address='ckb1second'").fetchone()[0],
                "FAILED_RETRY_EXHAUSTED")
            store.close()

    def test_ml_export_excludes_all_legacy_and_identifier_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "cache.sqlite")
            store.conn.executescript(SCHEDULER_SCHEMA)
            item = manifest_item()
            store.conn.execute("""INSERT INTO wallet_collection_state
                (address,population_version,observation_window_id,completion_category,
                 collection_state,evidence_state,updated_at) VALUES (?,?,?,?,?,?,?)""",
                (item["address"], POPULATION_VERSION, OBSERVATION_WINDOW_ID,
                 "NEEDS_FULL_REFILL", "NOT_STARTED", "UNRESOLVED", "now"))
            exported = export_feature_datasets(store.conn, [item], Path(temporary))
            with Path(exported["ml_path"]).open() as handle:
                header = next(csv.reader(handle))
            forbidden = {"wallet", "canonical_lock_hash", "sampling_stratum",
                         "lifetime_tx_count", "legacy_proxy_label", "population_version",
                         "observation_window_id", "collection_state", "evidence_state"}
            self.assertTrue(forbidden.isdisjoint(header))
            self.assertFalse(any("timestamp" in column or "cluster" in column or
                                 "prediction" in column for column in header))
            self.assertFalse(any("coverage" in column for column in header))
            store.close()

    def test_insufficient_feature_values_export_as_missing_not_zero(self):
        item = manifest_item()
        observation = {"metadata": {"transactions_observed": 0}}
        assessment = {
            "features": {name: {"support_state": "INSUFFICIENT_EVIDENCE",
                                "values": {"example": 0}, "evidence": {}}
                         for name in ("temporal", "topology", "templates",
                                      "scripts", "capacity")},
            "assessments": [],
        }
        row, _ = flatten_feature_row(
            item, observation, assessment,
            {"collection_state": "COMPLETE",
             "evidence_state": "INSUFFICIENT_EVIDENCE"})
        self.assertIsNone(row["temporal__example"])


if __name__ == "__main__":
    unittest.main()
