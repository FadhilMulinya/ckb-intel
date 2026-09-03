from __future__ import annotations

import unittest

from features_v2 import capacity, lifecycle, lineage, periodicity, templates, temporal, topology, typed_assets
from features_v2.pipeline import assess_observation_v2
from feature_engineering_v2 import unresolved_assessment
from features_v2.scripts import XUDT_CODE_HASH
from features_v2.stats import quantile, repeat_ratio
from features_v2.support import SupportState


def script(code="11", hash_type="type", args="0x"):
    return {"code_hash": "0x" + code * 32, "hash_type": hash_type, "args": args}


def tx(index, timestamp, inputs=1, outputs=1):
    return {"tx_hash": f"0x{index:064x}", "block_timestamp": timestamp,
            "block_number": 1000 + index, "transaction_index": index,
            "inputs": [{"resolved_capacity": 1000, "resolved_lock_script": script(),
                        "resolved_lock_script_hash": "target", "resolved_type_script": None,
                        "resolved_type_script_hash": None, "resolved_output_data": "0x",
                        "target_controls_input": True, "resolution_status": "complete",
                        "previous_tx_hash": f"0x{index+j+100:064x}", "previous_output_index": 0,
                        "raw": {"occupied_capacity": "600"}} for j in range(inputs)],
            "outputs": [{"output_index": j, "capacity": 900, "lock_script": script(),
                         "lock_script_hash": "target", "type_script": None,
                         "type_script_hash": None, "output_data": "0x",
                         "target_controls_output": True,
                         "raw": {"occupied_capacity": "600"}} for j in range(outputs)]}


def observation(txs):
    return {"transactions": txs, "metadata": {"detail_complete": True,
            "input_resolution_complete": True, "window_start_timestamp": 0,
            "window_end_timestamp": 2592000, "collection_state": "COMPLETE"},
            "lifecycle_records": [], "observed_target_cells": [],
            "right_censored_target_cells": []}


class StatsV2Tests(unittest.TestCase):
    def test_quantile_and_repeat(self):
        self.assertEqual(quantile([1, 2, 3, 4], .5), 2.5)
        self.assertEqual(repeat_ratio([100, 101, 500]), 2 / 3)


class TemporalV2Tests(unittest.TestCase):
    def test_sessions_bursts_and_periodicity(self):
        times = [0, 10, 20, 4000, 4010, 4020, 8000, 8010, 8020]
        obs = observation([tx(i, value) for i, value in enumerate(times)])
        result = temporal.extract(obs)
        self.assertEqual(result.values["activity_session_count"], 3)
        self.assertEqual(result.values["burst_count"], 3)
        periodic = periodicity.extract(obs)
        self.assertEqual(periodic.support_state, SupportState.SUPPORTED)
        self.assertIsNotNone(periodic.values["dominant_interval_cluster"])
        self.assertIsNone(periodic.values["spectral_power"])


class StructuralV2Tests(unittest.TestCase):
    def test_topology_fragmentation_and_template_identity_exclusion(self):
        obs = observation([tx(i, i * 100, 1, 3) for i in range(5)])
        result = topology.extract(obs)
        self.assertEqual(result.values["one_to_many_ratio"], 1)
        self.assertEqual(result.values["fragmentation_event_count"], 5)
        a = tx(1, 10); b = tx(2, 999)
        a["inputs"][0]["resolved_lock_script_hash"] = "wallet-a"
        b["inputs"][0]["resolved_lock_script_hash"] = "wallet-b"
        self.assertEqual(templates.fingerprint(a)[0], templates.fingerprint(b)[0])

    def test_lineage_is_hypergraph_not_pairwise(self):
        obs = observation([tx(i, i * 100, 2, 3) for i in range(3)])
        result = lineage.extract(obs)
        self.assertEqual(result.values["merge_count"], 3)
        self.assertEqual(result.values["split_count"], 3)
        self.assertEqual(result.evidence["lineage_edge_count"], 15)


class CellV2Tests(unittest.TestCase):
    def test_lifecycle_and_censoring(self):
        obs = observation([tx(i, i * 100) for i in range(3)])
        obs["observed_target_cells"] = [("a", 0), ("b", 0), ("c", 0), ("d", 0)]
        obs["right_censored_target_cells"] = [("d", 0)]
        obs["lifecycle_records"] = [
            {"cell_lifetime_seconds": 0, "cell_lifetime_blocks": 0},
            {"cell_lifetime_seconds": 100, "cell_lifetime_blocks": 1},
            {"cell_lifetime_seconds": 90000, "cell_lifetime_blocks": 100},
        ]
        result = lifecycle.extract(obs)
        self.assertEqual(result.values["same_block_consumption_ratio"], 1 / 3)
        self.assertEqual(result.values["right_censored_cell_count"], 1)

    def test_xudt_little_endian_and_capacity(self):
        cell = tx(1, 100)
        amount = 123456
        type_script = {"code_hash": XUDT_CODE_HASH, "hash_type": "data1", "args": "0x" + "22" * 32}
        for item, resolved in [(cell["inputs"][0], True), (cell["outputs"][0], False)]:
            prefix = "resolved_" if resolved else ""
            item[prefix + "type_script"] = type_script
            item[prefix + "type_script_hash"] = "asset"
            item[prefix + "output_data"] = "0x" + amount.to_bytes(16, "little").hex()
            item["raw"] = {"xudt_info": {"amount": str(amount)}, "occupied_capacity": "600"}
        obs = observation([cell, cell.copy(), cell.copy()])
        typed = typed_assets.extract(obs)
        self.assertEqual(typed.values["token_input_total"], amount * 3)
        cap = capacity.extract(obs)
        self.assertEqual(cap.values["target_net_capacity_delta"], -300)


class PipelineV2Tests(unittest.TestCase):
    def test_assessment_is_label_free(self):
        obs = observation([tx(i, i * 600) for i in range(10)])
        first = assess_observation_v2(obs)
        periodic = next(rule for rule in first["rules"] if rule["rule"] == "PERIODIC_EXECUTION")
        self.assertIn("THRESHOLDS_MET", periodic["reason_codes"])
        obs["metadata"].update(legacy_proxy_label="bot_like", sampling_stratum="5000+")
        second = assess_observation_v2(obs)
        self.assertEqual(first, second)

    def test_unresolved_wallet_retains_all_rule_rows(self):
        assessment = unresolved_assessment("INVALID_FROZEN_ADDRESS")
        self.assertEqual(12, len(assessment["rules"]))
        self.assertTrue(all(rule["support_state"] == "UNRESOLVED"
                            for rule in assessment["rules"]))


if __name__ == "__main__":
    unittest.main()
