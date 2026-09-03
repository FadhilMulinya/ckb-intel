import unittest

from validate_features_v2 import (ACTIVITY_PREDICTORS, candidate_feature_sets,
                                  manual_review_set, predictor_audit, ranks, spearman,
                                  theoretical_domain)


class ValidationStatisticsTests(unittest.TestCase):
    def test_average_ranks_and_spearman(self):
        self.assertEqual([1.5, 1.5, 3.0], ranks([2, 2, 9]))
        self.assertAlmostEqual(-1.0, spearman([1, 2, 3], [9, 5, 1]))

    def test_predictor_audit_preserves_missing_as_missing(self):
        rows = [{"temporal__interarrival_cv": ""} for _ in range(90)]
        rows += [{"temporal__interarrival_cv": str(index / 10)} for index in range(10)]
        definitions = {"temporal": {"sample_universe": "timestamps", "method": "gaps"}}
        audit, registry = predictor_audit(rows, ["temporal__interarrival_cv"], definitions)
        self.assertEqual(90, audit[0]["missing_count"])
        self.assertEqual("VERY_SPARSE", audit[0]["classification"])
        self.assertEqual("NOT_SUPPORTED_OR_NOT_OBSERVED", registry[0]["missing_semantics"])

    def test_ratio_domain_is_bounded(self):
        self.assertEqual((0.0, 1.0, "bounded ratio"),
                         theoretical_domain("topology__one_to_many_ratio"))
        self.assertEqual((0.0, None, "non-negative magnitude"),
                         theoretical_domain("temporal__mean_session_duration"))


class CandidateMatrixTests(unittest.TestCase):
    def test_primary_sets_exclude_rules_activity_and_typed_assets(self):
        predictors = ["temporal__transaction_count", "temporal__interarrival_cv",
                      "typed_assets__typed_cell_ratio", "rule__BURST_EXECUTION__score"]
        rows = [{predictor: 0.5 for predictor in predictors} for _ in range(100)]
        audits = [{"predictor": predictor, "classification": "USABLE",
                   "non_missing_count": 100, "missing_ratio": 0.0} for predictor in predictors]
        leakage = [{"predictor": predictor, "activity_dependence": "LOW_ACTIVITY_DEPENDENCE"}
                   for predictor in predictors]
        candidates, _ = candidate_feature_sets(rows, predictors, audits, leakage, [])
        broad = candidates["BROAD_V2"]["features"]
        self.assertEqual(["temporal__interarrival_cv"], broad)
        self.assertTrue(ACTIVITY_PREDICTORS.isdisjoint(broad))
        self.assertEqual(["rule__BURST_EXECUTION__score"],
                         candidates["SECONDARY_EXPERIMENTAL_RULE_SCORES"]["features"])

    def test_manual_review_separates_positive_and_negative(self):
        evidence = [{"wallet": "a", "rules": [{"rule": "X", "support_state": "SUPPORTED",
                     "score": .9, "reason_codes": ["THRESHOLDS_MET"], "supporting_features": {},
                     "supporting_transaction_hashes": [], "supporting_transaction_count": 0}]}]
        evidence += [{"wallet": f"n{index}", "rules": [{"rule": "X", "support_state": "SUPPORTED",
                      "score": index / 10, "reason_codes": ["THRESHOLDS_NOT_MET"],
                      "supporting_features": {}, "supporting_transaction_hashes": [],
                      "supporting_transaction_count": 0}]} for index in range(7)]
        review = manual_review_set(evidence)
        self.assertEqual({"STRONG", "BORDERLINE_SCORE_PROXY", "SUPPORTED_NEGATIVE"},
                         {row["review_category"] for row in review})


if __name__ == "__main__":
    unittest.main()
