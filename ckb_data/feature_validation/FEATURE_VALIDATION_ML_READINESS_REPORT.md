# CKB Feature Validation and ML Readiness Report

This phase validates the frozen V2 feature space. It performs no imputation, PCA, UMAP, clustering, classification, collection, or Dataset V1 mutation.

## A. Predictor audit

All **121** ML-safe predictors were audited. The complete table is `/Users/fadhil/Personal/ckb-intel/ckb_data/feature_validation/predictor_audit_v1.csv`.

```json
{
  "CONSTANT": 5,
  "SPARSE": 99,
  "USABLE": 17
}
```

Classification thresholds are versioned in `validation_config_v1.json`; no feature was automatically removed from canonical V2.

## B. Missingness report

Feature coverage thresholds across all 121 predictors:

```json
{
  "at_least_20pct": 493,
  "at_least_40pct": 300,
  "at_least_50pct": 300,
  "at_least_60pct": 257,
  "at_least_70pct": 249,
  "at_least_80pct": 230,
  "at_least_90pct": 179
}
```

Missing means **not supported or not observed**, never zero behaviour. No imputation was performed.

## C. Support-cohort analysis

```json
{
  "coverage_threshold_sensitivity": {
    "at_least_20pct": 493,
    "at_least_40pct": 300,
    "at_least_50pct": 300,
    "at_least_60pct": 266,
    "at_least_70pct": 249,
    "at_least_80pct": 231,
    "at_least_90pct": 184
  },
  "named_cohorts": {
    "A_at_least_50pct_broad": 300,
    "B_topology_templates_scripts_capacity": 283,
    "C_temporal_topology_templates": 249,
    "D_at_least_6_supported_families": 254
  },
  "selection_status": "CANDIDATES_ONLY_NO_FINAL_COHORT_SELECTED",
  "supported_family_threshold_sensitivity": {
    "at_least_3_families": 526,
    "at_least_4_families": 302,
    "at_least_5_families": 300,
    "at_least_6_families": 254,
    "at_least_7_families": 226,
    "at_least_8_families": 167
  }
}
```

The named cohorts are candidates only; no final ML cohort was selected.

## D. Activity leakage analysis

Dependence classes: `{'MODERATE_ACTIVITY_DEPENDENCE': 22, 'LOW_ACTIVITY_DEPENDENCE': 87, 'HIGH_ACTIVITY_DEPENDENCE': 12}`. High dependence means absolute Spearman rho ≥ 0.8.

Most activity-associated predictors:

- `temporal__transaction_count`: max |rho| = 1.0000
- `temporal__positive_gap_count`: max |rho| = 0.9976
- `lifecycle__observed_cell_count`: max |rho| = 0.9732
- `capacity__target_occupied_capacity`: max |rho| = 0.9731
- `lineage__branch_count`: max |rho| = 0.9369
- `lineage__split_count`: max |rho| = 0.9120
- `temporal__activity_session_count`: max |rho| = 0.9048
- `lifecycle__consumed_cell_count`: max |rho| = 0.8982
- `templates__unique_template_count`: max |rho| = 0.8726
- `periodicity__multi_period_candidate_count`: max |rho| = 0.8628
- `scripts__lock_script_repeat_ratio`: max |rho| = 0.8535
- `templates__dominant_template_count`: max |rho| = 0.8051

Raw transaction count, observed controlled-Cell count, input count, and output count remain diagnostics and are excluded from primary candidate matrices.

## E. Redundancy report

Pairs at |correlation| ≥ 0.90: **121**; pairs at ≥ 0.95: **107**; near-duplicate groups: **20**.

Every KEEP_ONE removal is recorded in `candidate_feature_sets_v1.json`; canonical V2 remains unchanged.

## F. Distribution audit

Impossible values: **0**. Recorded extreme/manual-review cases: **233**.

Outliers were not clipped. Each issue record retains its wallet identifier and compact evidence provenance.

## G. Stability analysis

```json
{
  "activity_hour_concentration": {
    "adjacent_week_rank_stability": [
      {
        "left_week": 1,
        "overlap": 186,
        "right_week": 2,
        "spearman_rank_stability": 0.8036379136414841
      },
      {
        "left_week": 2,
        "overlap": 188,
        "right_week": 3,
        "spearman_rank_stability": 0.7862632861516757
      },
      {
        "left_week": 3,
        "overlap": 222,
        "right_week": 4,
        "spearman_rank_stability": 0.7568870780399146
      }
    ],
    "median_within_wallet_cv": 0.15609072770643168,
    "median_within_wallet_variance": 0.0029296875,
    "wallets_with_two_or_more_weeks": 282
  },
  "dominant_period_seconds": {
    "adjacent_week_rank_stability": [
      {
        "left_week": 1,
        "overlap": 113,
        "right_week": 2,
        "spearman_rank_stability": 0.9313409018690375
      },
      {
        "left_week": 2,
        "overlap": 118,
        "right_week": 3,
        "spearman_rank_stability": 0.9125602331437157
      },
      {
        "left_week": 3,
        "overlap": 123,
        "right_week": 4,
        "spearman_rank_stability": 0.9160258207194315
      }
    ],
    "median_within_wallet_cv": 0.10655194619066322,
    "median_within_wallet_variance": 218583.46875,
    "wallets_with_two_or_more_weeks": 150
  },
  "limitations": [
    "Four fixed seven-day windows cover days 1-28; days 29-30 are excluded from stability only.",
    "Stability is descriptive and support-aware; transient bursts need not be stable."
  ],
  "periodicity_strength": {
    "adjacent_week_rank_stability": [
      {
        "left_week": 1,
        "overlap": 113,
        "right_week": 2,
        "spearman_rank_stability": 0.7844302411361224
      },
      {
        "left_week": 2,
        "overlap": 118,
        "right_week": 3,
        "spearman_rank_stability": 0.7725984265329214
      },
      {
        "left_week": 3,
        "overlap": 123,
        "right_week": 4,
        "spearman_rank_stability": 0.7770324424396554
      }
    ],
    "median_within_wallet_cv": 0.08901008654235222,
    "median_within_wallet_variance": 0.0021373268088458438,
    "wallets_with_two_or_more_weeks": 150
  },
  "template_repeat_ratio": {
    "adjacent_week_rank_stability": [
      {
        "left_week": 1,
        "overlap": 140,
        "right_week": 2,
        "spearman_rank_stability": 0.8753424106051727
      },
      {
        "left_week": 2,
        "overlap": 144,
        "right_week": 3,
        "spearman_rank_stability": 0.86445177596301
      },
      {
        "left_week": 3,
        "overlap": 159,
        "right_week": 4,
        "spearman_rank_stability": 0.8091250981217395
      }
    ],
    "median_within_wallet_cv": 0.15185176183444088,
    "median_within_wallet_variance": 0.0009791836979269927,
    "wallets_with_two_or_more_weeks": 187
  },
  "topology_repeat_ratio": {
    "adjacent_week_rank_stability": [
      {
        "left_week": 1,
        "overlap": 140,
        "right_week": 2,
        "spearman_rank_stability": 0.15474489086753132
      },
      {
        "left_week": 2,
        "overlap": 144,
        "right_week": 3,
        "spearman_rank_stability": 0.19992346451279214
      },
      {
        "left_week": 3,
        "overlap": 159,
        "right_week": 4,
        "spearman_rank_stability": 0.3187164806212761
      }
    ],
    "median_within_wallet_cv": 0.0,
    "median_within_wallet_variance": 0.0,
    "wallets_with_two_or_more_weeks": 187
  }
}
```

Four fixed weekly subwindows were evaluated for periodicity, template recurrence, topology recurrence, and activity concentration. Transient burst behaviour is not required to be stable.

## H. Feature-family contribution analysis

```json
{
  "capacity": {
    "assessment": "REVIEW_FAMILY_OVERLAP",
    "ckb_native_classification": "STRONGLY_CKB_NATIVE",
    "high_activity_dependence_count": 1,
    "median_missing_ratio": 0.6032423208191127,
    "predictor_count": 14,
    "strong_cross_family_redundancy_pairs": 9,
    "usable_or_sparse_count": 14
  },
  "cross_feature": {
    "assessment": "REVIEW_FAMILY_OVERLAP",
    "ckb_native_classification": "GENERIC_ACCOUNT_LIKE",
    "high_activity_dependence_count": 0,
    "median_missing_ratio": 0.7990614334470989,
    "predictor_count": 10,
    "strong_cross_family_redundancy_pairs": 16,
    "usable_or_sparse_count": 10
  },
  "lifecycle": {
    "assessment": "REVIEW_FAMILY_OVERLAP",
    "ckb_native_classification": "STRONGLY_CKB_NATIVE",
    "high_activity_dependence_count": 2,
    "median_missing_ratio": 0.8336177474402731,
    "predictor_count": 7,
    "strong_cross_family_redundancy_pairs": 17,
    "usable_or_sparse_count": 7
  },
  "lineage": {
    "assessment": "REVIEW_FAMILY_OVERLAP",
    "ckb_native_classification": "STRONGLY_CKB_NATIVE",
    "high_activity_dependence_count": 2,
    "median_missing_ratio": 0.5486348122866894,
    "predictor_count": 7,
    "strong_cross_family_redundancy_pairs": 3,
    "usable_or_sparse_count": 7
  },
  "periodicity": {
    "assessment": "CONTRIBUTES_DISTINCT_CANDIDATES",
    "ckb_native_classification": "WEAKLY_CKB_SPECIFIC",
    "high_activity_dependence_count": 1,
    "median_missing_ratio": 0.810580204778157,
    "predictor_count": 9,
    "strong_cross_family_redundancy_pairs": 1,
    "usable_or_sparse_count": 9
  },
  "scripts": {
    "assessment": "CONTRIBUTES_DISTINCT_CANDIDATES",
    "ckb_native_classification": "STRONGLY_CKB_NATIVE",
    "high_activity_dependence_count": 1,
    "median_missing_ratio": 0.5366894197952219,
    "predictor_count": 13,
    "strong_cross_family_redundancy_pairs": 0,
    "usable_or_sparse_count": 9
  },
  "templates": {
    "assessment": "CONTRIBUTES_DISTINCT_CANDIDATES",
    "ckb_native_classification": "STRONGLY_CKB_NATIVE",
    "high_activity_dependence_count": 2,
    "median_missing_ratio": 0.7440273037542662,
    "predictor_count": 9,
    "strong_cross_family_redundancy_pairs": 3,
    "usable_or_sparse_count": 9
  },
  "temporal": {
    "assessment": "REVIEW_FAMILY_OVERLAP",
    "ckb_native_classification": "GENERIC_ACCOUNT_LIKE",
    "high_activity_dependence_count": 3,
    "median_missing_ratio": 0.787542662116041,
    "predictor_count": 27,
    "strong_cross_family_redundancy_pairs": 29,
    "usable_or_sparse_count": 27
  },
  "topology": {
    "assessment": "CONTRIBUTES_DISTINCT_CANDIDATES",
    "ckb_native_classification": "STRONGLY_CKB_NATIVE",
    "high_activity_dependence_count": 0,
    "median_missing_ratio": 0.7440273037542662,
    "predictor_count": 25,
    "strong_cross_family_redundancy_pairs": 8,
    "usable_or_sparse_count": 24
  },
  "typed_assets": {
    "assessment": "NO_NUMERIC_PREDICTORS",
    "predictor_count": 0
  }
}
```

## I. Candidate feature matrices

- **BROAD_V2**: 104 features; missing ratio 0.7305395116828564; 300 wallets at least 50% complete
- **CORE_BEHAVIOUR**: 95 features; missing ratio 0.7225345787677384; 300 wallets at least 50% complete
- **LOW_REDUNDANCY_CORE**: 59 features; missing ratio 0.7169404755018222; 300 wallets at least 50% complete
- **HIGH_CONFIDENCE**: 10 features; missing ratio 0.5455631399317407; 543 wallets at least 50% complete
- **SECONDARY_EXPERIMENTAL_RULE_SCORES**: 12 features; missing ratio 0.7824232081911263; 300 wallets at least 50% complete

Rule scores are present only in SECONDARY_EXPERIMENTAL. Typed assets are retained canonically but excluded from PRIMARY candidates because no typed-asset observation is fully supported.

## J. Scaling and transformation recommendations

Every predictor has a versioned recommendation in `predictor_registry_v1.csv`: bounded ratios/entropies are preserved, heavy-tailed counts/capacity/lifetimes use log1p plus RobustScaler, and remaining unbounded shape statistics use StandardScaler or RobustScaler as indicated. Nothing was transformed in this phase.

## K. Manual behaviour review dataset

The review set contains **158** strong, borderline-score-proxy, and supported-negative records across all rules, with feature values, reason codes, support, and transaction hashes.

## L. Proposed exploratory ML workflow

1. Select a support-aware wallet cohort after reviewing cohort sensitivity.
2. Select the Low-Redundancy Core or High-Confidence candidate set.
3. Decide the missing-data strategy by support mechanism; never zero-fill unsupported evidence.
4. Apply the recorded log1p/scaling transformations.
5. Use PCA first for global variance and activity-axis inspection.
6. Use UMAP for visualization only after stability sensitivity.
7. Compare HDBSCAN density structure with GMM soft assignments.
8. Evaluate resampling, feature-set, scaling, and parameter stability.
9. Interpret any structure using raw evidence, never legacy labels.

## M. Clustering readiness

- **FEATURE DEFINITIONS: READY** — all 121 predictors have family, definition, support, unit, missing semantics, limitations, and transformation metadata.
- **MISSINGNESS UNDERSTOOD: READY** — feature, wallet, block-pattern, and cohort analyses are explicit.
- **ACTIVITY LEAKAGE: READY** — Pearson/Spearman diagnostics are complete; decisions remain for the ML phase.
- **FEATURE REDUNDANCY: READY** — overlap-qualified pairs and KEEP_ONE candidates are documented.
- **FEATURE STABILITY: PARTIAL** — four weekly windows are analyzed, but only one month is available and days 29–30 are outside weekly stability.
- **CORE FEATURE MATRIX: READY** — raw rule scores, typed assets, and activity-volume diagnostics are excluded.
- **HIGH-CONFIDENCE WALLET COHORT: READY** — candidate size at ≥50% Broad coverage is 300; final selection remains pending.
- **EXPLORATORY ML: PARTIAL** — candidate inputs exist, but cohort/missingness/scaling choices must be locked first.
- **PCA: PARTIAL** — recommended as the first analysis after preprocessing decisions; not run.
- **UMAP: NOT READY** — depends on cohort, scaling, missingness, and PCA inspection; not run.
- **HDBSCAN: NOT READY** — depends on a stable transformed feature space; not run.
- **GMM: NOT READY** — depends on a stable dense representation and component sensitivity; not run.
- **SUPERVISED CLASSIFICATION: NOT READY** — no defensible target labels exist.

Readiness gates and their threshold sensitivity are in `clustering_readiness_gates_v1.json`.

No Dataset V1/V2 source artifact was modified.
