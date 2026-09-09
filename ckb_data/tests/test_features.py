from __future__ import annotations

import random
import unittest

from features import temporal, templates, topology
from features.base import SupportState
from features.rules import batch_distribution, fan_in_collection, periodic_execution
from features.scripts import identify


def script(name):
    return {"code_hash": "0x" + name * 64, "hash_type": "type", "args": "0x"}


def make_tx(tx_hash, timestamp, input_locks, output_locks, target="target", variant=""):
    return {"tx_hash": tx_hash, "block_timestamp": timestamp,
        "inputs": [{"resolved_capacity": 100, "resolved_lock_script": script("1"),
                    "resolved_lock_script_hash": lock,
                    "resolved_type_script": None, "resolved_type_script_hash": None,
                    "resolved_output_data": "0x", "target_controls_input": lock == target}
                   for lock in input_locks],
        "outputs": [{"capacity": 90, "lock_script": script("2"),
                     "lock_script_hash": lock, "type_script": None,
                     "type_script_hash": None, "output_data": "0x" + variant,
                     "target_controls_output": lock == target}
                    for lock in output_locks]}


def observation(txs):
    return {"transactions": txs, "metadata": {"detail_complete": True,
        "input_resolution_complete": True, "detail_coverage_ratio": 1.0,
        "input_resolution_ratio": 1.0}}


class TemporalTests(unittest.TestCase):
    def timestamps(self, values):
        return observation([make_tx(f"tx{i}", value, ["target"], ["other"])
                            for i, value in enumerate(values)])

    def test_perfect_periodic(self):
        result = temporal.extract(self.timestamps([1_000 + i * 600 for i in range(12)]))
        self.assertEqual(result.values["dominant_period_seconds"], 600)
        self.assertAlmostEqual(result.values["periodicity_strength"], 1.0)
        self.assertAlmostEqual(result.values["phase_stability"], 1.0)

    def test_jittered_periodic(self):
        values = [1_000 + i * 600 + (i % 3 - 1) * 8 for i in range(12)]
        result = temporal.extract(self.timestamps(values))
        self.assertGreater(result.values["periodicity_strength"], 0.9)
        self.assertGreater(result.values["phase_stability"], 0.8)

    def test_random_irregular(self):
        rng = random.Random(42)
        values = [1_000]
        for _ in range(15):
            values.append(values[-1] + rng.randint(30, 1800))
        result = temporal.extract(self.timestamps(values))
        self.assertGreater(result.values["interarrival_cv"], 0.35)

    def test_bursty(self):
        gaps = [5, 5, 5, 3000] * 3
        values = [1_000]
        for gap in gaps:
            values.append(values[-1] + gap)
        result = temporal.extract(self.timestamps(values))
        self.assertGreater(result.values["burstiness"], 0)

    def test_insufficient(self):
        result = temporal.extract(self.timestamps([1, 2, 3]))
        self.assertEqual(result.support_state, SupportState.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(result.values["periodicity_strength"])


class TopologyTemplateTests(unittest.TestCase):
    def test_topologies(self):
        cases = [(["target"], ["target"]),
                 (["target"], ["target", "a", "b"]),
                 (["target", "a", "b"], ["target"]),
                 (["target", "a"], ["target", "b"])]
        rows = [topology.transaction_topology(make_tx(f"t{i}", i, ins, outs))
                for i, (ins, outs) in enumerate(cases)]
        self.assertEqual((rows[0]["total_input_cell_count"], rows[0]["total_output_cell_count"]), (1, 1))
        self.assertEqual(rows[1]["external_output_lock_count"], 2)
        self.assertEqual(rows[2]["external_input_lock_count"], 2)
        self.assertEqual((rows[3]["unique_input_lock_count"], rows[3]["unique_output_lock_count"]), (2, 2))

    def test_hash_and_timestamp_excluded_from_template(self):
        a = make_tx("hash-a", 100, ["target"], ["a", "b"])
        b = make_tx("hash-b", 999, ["target"], ["a", "b"])
        self.assertEqual(templates.transaction_template_hash(a), templates.transaction_template_hash(b))

    def test_different_script_or_structure_changes_template(self):
        a = make_tx("a", 1, ["target"], ["a"])
        b = make_tx("b", 1, ["target"], ["different"])
        c = make_tx("c", 1, ["target"], ["a", "b"])
        self.assertNotEqual(templates.transaction_template_hash(a), templates.transaction_template_hash(b))
        self.assertNotEqual(templates.transaction_template_hash(a), templates.transaction_template_hash(c))

    def test_repeated_template_features(self):
        txs = [make_tx(f"hash-{i}", i * 100, ["target"], ["a", "b"]) for i in range(5)]
        result = templates.extract(observation(txs))
        self.assertEqual(result.values["unique_template_count"], 1)
        self.assertEqual(result.values["template_repeat_ratio"], 1.0)

    def test_known_scripts(self):
        match = identify({"code_hash": "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8",
                          "hash_type": "type", "args": "0x"})
        self.assertEqual(match["script_family"], "SECP256K1_BLAKE160")
        self.assertEqual(identify(script("f"))["script_family"], "UNKNOWN")


class RuleTests(unittest.TestCase):
    def test_periodic_rule(self):
        obs = observation([make_tx(f"p{i}", 1_000 + i * 600, ["target"], ["a"])
                           for i in range(10)])
        result = periodic_execution(obs, temporal.extract(obs))
        self.assertEqual(result.support_state, SupportState.SUPPORTED)

    def test_batch_rule(self):
        obs = observation([make_tx(f"b{i}", i * 100, ["target"], ["a", "b", "c"])
                           for i in range(5)])
        result = batch_distribution(obs, topology.extract(obs), templates.extract(obs))
        self.assertEqual(result.support_state, SupportState.SUPPORTED)
        self.assertEqual(len(result.supporting_transactions), 5)

    def test_fanin_rule(self):
        obs = observation([make_tx(f"f{i}", i * 100, ["target", "a", "b"], ["target"])
                           for i in range(5)])
        result = fan_in_collection(obs, topology.extract(obs), templates.extract(obs))
        self.assertEqual(result.support_state, SupportState.SUPPORTED)

    def test_mixed_and_insufficient_rules(self):
        mixed = observation([make_tx(f"m{i}", i * 100, ["target", "a", "b"],
                                     ["target", "c", "d"]) for i in range(5)])
        self.assertEqual(batch_distribution(mixed, topology.extract(mixed), templates.extract(mixed)).support_state,
                         SupportState.SUPPORTED)
        self.assertEqual(fan_in_collection(mixed, topology.extract(mixed), templates.extract(mixed)).support_state,
                         SupportState.SUPPORTED)
        small = observation([make_tx("one", 1, ["target"], ["a"])])
        self.assertEqual(periodic_execution(small, temporal.extract(small)).support_state,
                         SupportState.INSUFFICIENT_EVIDENCE)


if __name__ == "__main__":
    unittest.main()
