import json
import unittest
from pathlib import Path

try:
    import numpy as np
    from exploratory_structure import effect, pathological, select_reference
    RUNTIME_AVAILABLE = True
except ImportError:
    RUNTIME_AVAILABLE = False


@unittest.skipUnless(RUNTIME_AVAILABLE, "Phase 2 numerical runtime required")
class ExploratoryStructureTests(unittest.TestCase):
    def test_pathology_gates(self):
        self.assertIn("FEWER_THAN_TWO_CLUSTERS", pathological(np.array([0] * 20)))
        self.assertIn("NOISE_ABOVE_80_PERCENT", pathological(np.array([-1] * 81 + [0] * 10 + [1] * 9)))
        self.assertIn("GIANT_CLUSTER_ABOVE_85_PERCENT", pathological(np.array([0] * 86 + [1] * 14)))
        self.assertEqual([], pathological(np.array([0] * 50 + [1] * 50)))

    def test_reference_selection_uses_predeclared_distance(self):
        runs = [
            {"run_id": "many", "min_cluster_size": 15, "min_samples": 5,
             "selection_method": "leaf", "cluster_count": 8, "pathological": False},
            {"run_id": "preset", "min_cluster_size": 25, "min_samples": 10,
             "selection_method": "eom", "cluster_count": 2, "pathological": False},
        ]
        self.assertEqual("preset", select_reference(runs)["run_id"])

    def test_standardized_effect_direction(self):
        self.assertGreater(effect(np.array([3., 4., 5.]), np.array([0., 1., 2.])), 0)
        self.assertLess(effect(np.array([0., 1., 2.]), np.array([3., 4., 5.])), 0)

    def test_contract_keeps_discovery_and_interpretation_separate(self):
        contract_path = Path(__file__).resolve().parent / "exploratory_ml_phase2_v1" / "experiment_contract.json"
        if not contract_path.exists():
            self.skipTest("Phase 2 artifacts not generated")
        contract = json.loads(contract_path.read_text())
        self.assertEqual("POST_HOC_ONLY", contract["rules_and_activity"])
        self.assertEqual(
            "HIGH_CONFIDENCE_PCA4_PREDECLARED_APPROX_80_PERCENT_VARIANCE",
            contract["interpretation_representation"],
        )


if __name__ == "__main__":
    unittest.main()
