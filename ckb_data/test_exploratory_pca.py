import csv
import unittest
from pathlib import Path

try:
    import numpy as np
    from exploratory_pca import (align_first_five, complete_cases, feasible, fit_pca,
                                 signed_log1p, transform_column)
    NUMPY = True
except ImportError:
    NUMPY = False


@unittest.skipUnless(NUMPY, "bundled PCA runtime required")
class PcaMathTests(unittest.TestCase):
    def test_signed_log_accepts_negative_capacity_delta(self):
        values = np.array([-9.0, 0.0, 9.0])
        transformed = signed_log1p(values)
        self.assertAlmostEqual(-transformed[2], transformed[0])
        self.assertEqual(0.0, transformed[1])

    def test_zero_iqr_falls_back_to_standard_scaler(self):
        values = np.array([0.0] * 9 + [1.0])
        scaled, record = transform_column(values, "scripts__type_family_count")
        self.assertEqual("STANDARD_SCALER_ZERO_IQR_FALLBACK", record["scaler"])
        self.assertAlmostEqual(0.0, float(np.mean(scaled)), places=12)

    def test_signed_shape_statistic_uses_identity_standardization(self):
        values = np.array([-2.0, 0.0, 3.0])
        _, record = transform_column(values, "temporal__interarrival_kurtosis")
        self.assertEqual("IDENTITY", record["initial_transform"])
        self.assertEqual("STANDARD_SCALER", record["scaler"])

    def test_pca_is_orthonormal_and_variance_consistent(self):
        matrix = np.array([[1., 2.], [2., 4.], [3., 5.], [4., 8.]])
        fitted = fit_pca(matrix)
        identity = fitted["components"] @ fitted["components"].T
        self.assertTrue(np.allclose(identity, np.eye(2)))
        self.assertAlmostEqual(1.0, float(fitted["explained_variance_ratio"].sum()))
        self.assertTrue(np.allclose(np.var(fitted["scores"], axis=0, ddof=1), fitted["eigenvalues"]))

    def test_alignment_handles_sign_and_component_swap(self):
        reference = np.eye(5)
        candidate = reference[[1, 0, 2, 3, 4]].copy(); candidate[0] *= -1
        aligned, permutation, cosines = align_first_five(reference, candidate)
        self.assertEqual([1, 0, 2, 3, 4], permutation)
        self.assertTrue(np.allclose(aligned, reference))
        self.assertEqual([1.0] * 5, cosines)

    def test_feasibility_gate(self):
        self.assertTrue(feasible(249, 34)[0])
        self.assertTrue(feasible(172, 18)[0])
        self.assertFalse(feasible(28, 59)[0])
        self.assertFalse(feasible(46, 36)[0])

    def test_frozen_candidate_sizes(self):
        base = Path(__file__).resolve().parent / "feature_validation"
        with (base / "high_confidence.csv").open() as handle:
            reader = csv.DictReader(handle); rows = [[float(row[name]) if row[name] else None
                                                      for name in reader.fieldnames] for row in reader]
        self.assertEqual(10, len(rows[0])); self.assertEqual(513, len(complete_cases(rows)))


if __name__ == "__main__":
    unittest.main()
