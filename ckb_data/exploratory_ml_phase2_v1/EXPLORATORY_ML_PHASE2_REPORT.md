# Exploratory ML Phase 2 — Behavioural Structure Discovery

## Frozen contract

- `ckb-exploratory-structure-v1`
- Manifest `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe`
- No imputation, labels, rules, activity diagnostics, or prior clusters entered discovery.

## HDBSCAN sensitivity

The audit contains 192 grid runs across 8 selected representations. 3 selected representations met the resampling stability threshold. The full ten-feature High-Confidence scaled solution was unstable. PCA3, PCA4, and PCA6 were robust but produced 2, 3, and 2 groups respectively, so the number of groups remains representation-dependent.

## Evidence-review representation

PCA4 is used only for evidence review because it was predeclared as the approximately 80%-variance representation. Its labels are profiled against the original ten scaled High-Confidence features; this choice was not optimized for cluster count.

```json
[
  {
    "group": 0,
    "initial_name": "BEHAVIOUR_GROUP_01",
    "promoted_archetype": "LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE",
    "strongest_feature": "capacity__target_consumed_capacity",
    "standardized_difference": -2.1244382714547387,
    "activity_dependence": "LOW_ACTIVITY_DEPENDENCE",
    "promotion_status": "EVIDENCE_SUPPORTED_DESCRIPTIVE"
  },
  {
    "group": 1,
    "initial_name": "BEHAVIOUR_GROUP_02",
    "promoted_archetype": "SCRIPT_TYPE_DIVERSE_STRUCTURE",
    "strongest_feature": "scripts__type_family_count",
    "standardized_difference": 1.9612208184751214,
    "activity_dependence": "LOW_ACTIVITY_DEPENDENCE",
    "promotion_status": "EVIDENCE_SUPPORTED_DESCRIPTIVE"
  },
  {
    "group": 2,
    "initial_name": "BEHAVIOUR_GROUP_03",
    "promoted_archetype": "UNINTERPRETED",
    "strongest_feature": "scripts__type_family_count",
    "standardized_difference": -0.5007292737035348,
    "activity_dependence": "LOW_ACTIVITY_DEPENDENCE",
    "promotion_status": "UNINTERPRETED"
  }
]
```

## GMM sensitivity

GMM was fit independently on the full scaled family matrices. Its selected solutions disagree materially with HDBSCAN, so it is a sensitivity check rather than confirmation.

```json
[
  {
    "representation": "HIGH_CONFIDENCE_SCALED",
    "gmm_choice": {
      "representation": "HIGH_CONFIDENCE_SCALED",
      "components": 10,
      "covariance_type": "diag",
      "bic": -10278.553947339366,
      "aic": -11164.771598980056,
      "converged": true,
      "minimum_component_size": 25,
      "mean_assignment_entropy": 0.005450913041832471
    },
    "hdbscan_comparison_representation": "HIGH_CONFIDENCE_PCA4",
    "hdbscan_available": true,
    "ari": 0.28698282004041126,
    "ami": 0.5113378640334088
  },
  {
    "representation": "TEMPORAL_STRUCTURE_SCALED",
    "gmm_choice": {
      "representation": "TEMPORAL_STRUCTURE_SCALED",
      "components": 1,
      "covariance_type": "full",
      "bic": 13576.839833618149,
      "aic": 11364.361961741848,
      "converged": true,
      "minimum_component_size": 249,
      "mean_assignment_entropy": 0.0
    },
    "hdbscan_comparison_representation": "TEMPORAL_STRUCTURE_SCALED",
    "hdbscan_available": true,
    "ari": 0.0,
    "ami": 0.0
  },
  {
    "representation": "CELL_STRUCTURE_SCALED",
    "gmm_choice": {
      "representation": "CELL_STRUCTURE_SCALED",
      "components": 5,
      "covariance_type": "diag",
      "bic": -1488.5318186831817,
      "aic": -2067.670802416857,
      "converged": true,
      "minimum_component_size": 5,
      "mean_assignment_entropy": 0.0031761564982487533
    },
    "hdbscan_comparison_representation": "CELL_STRUCTURE_SCALED",
    "hdbscan_available": true,
    "ari": 0.21431766010682693,
    "ami": 0.2318060643515892
  }
]
```

## Negative-result policy

Unstable, pathological, and disagreeing results remain in the audit. No parameter was selected to maximize cluster count, minimize noise, or improve agreement.

## Submission readiness

- **BEHAVIOURAL STRUCTURE: PARTIAL** — stable low-dimensional structure exists, but group count and assignments depend on representation.
- **HDBSCAN STABILITY: PARTIAL** — three PCA views are robust; the full scaled view and other blocks are not consistently robust.
- **GMM SENSITIVITY: PARTIAL** — independently selected mixture solutions do not confirm HDBSCAN partitions.
- **ACTIVITY-INDEPENDENCE: PARTIAL** — activity was excluded from discovery and audited post hoc; group-specific effects remain documented.
- **RAW EVIDENCE VALIDATION: PARTIAL** — central, boundary, and extreme examples include bounded feature and transaction-hash evidence, but no manual semantic adjudication was performed.
- **ARCHETYPE INTERPRETATION: PARTIAL** — names are descriptive structural summaries, not identities.
- **UMAP VISUALIZATION: READY** — visualization only; UMAP coordinates were never clustered.
- **SUPERVISED CLASSIFICATION: NOT READY**.
- **NERVOS FINAL SUBMISSION: PARTIAL**.

No identity claims, UMAP clustering, supervised learning, collection, retry, commit, merge, or push occurred.
