# CKB Behaviour Feature Engineering V2 Report

## A. Dataset snapshot

- Dataset: `ckb-behaviour-dataset-v1`
- Wallets: 1172
- Complete / partial / failed: 939 / 6 / 227
- Manifest: `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe`

## B. Implemented V2 feature families

Temporal, periodicity, lifecycle, topology, fragmentation/consolidation, templates, scripts, typed assets, capacity, and Cell lineage.

Exact executable definitions are versioned in `feature_definitions_v2.json`:

- **temporal** — positive interarrival gaps; 30-minute sessions; 60-second bursts of at least three transactions; values: `transaction_count`, `positive_gap_count`, `interarrival_mean_seconds`, `interarrival_median_seconds`, `interarrival_std_seconds`, `interarrival_cv`, `interarrival_p10`, `interarrival_p25`, `interarrival_p75`, `interarrival_p90`, `interarrival_skewness`, `interarrival_kurtosis`, `gap_entropy`, `activity_session_count`, `mean_session_duration`, `median_session_duration`, `mean_transactions_per_session`, `max_transactions_per_session`, `burst_count`, `mean_burst_size`, `max_burst_size`, `mean_burst_duration`, `transactions_in_bursts_ratio`, `hour_of_day_entropy`, `weekday_entropy`, `active_hour_concentration`, `active_day_concentration`

- **periodicity** — V1 median/MAD baseline, 5%-tolerant interval clusters, gap-sequence autocorrelation, four fixed weekly subwindows; Lomb-Scargle omitted; values: `dominant_period_seconds`, `periodicity_strength`, `phase_stability`, `autocorrelation_peak_strength`, `autocorrelation_peak_lag`, `interval_cluster_concentration`, `dominant_interval_cluster`, `dominant_interval_cluster_ratio`, `multi_period_candidate_count`, `period_stability_score`, `period_presence_count`, `eligible_subwindow_count`, `spectral_power`, `spectral_peak_ratio`

- **topology** — structural Cell and unique-lock counts only; no sender-recipient mapping; values: `one_to_one_ratio`, `one_to_many_ratio`, `many_to_one_ratio`, `many_to_many_ratio`, `other_topology_ratio`, `dominant_topology`, `dominant_topology_ratio`, `input_cell_count_mean`, `input_cell_count_median`, `input_cell_count_cv`, `output_cell_count_mean`, `output_cell_count_median`, `output_cell_count_cv`, `external_input_lock_mean`, `external_output_lock_mean`, `topology_entropy`, `topology_repeat_ratio`, `topology_transition_entropy`, `fragmentation_event_count`, `fragmentation_event_ratio`, `consolidation_event_count`, `consolidation_event_ratio`, `mean_fragmentation_factor`, `max_fragmentation_factor`, `mean_consolidation_factor`, `max_consolidation_factor`

- **lifecycle** — consumption timestamp/block minus creation timestamp/block; unconsumed target outputs are right-censored; values: `observed_cell_count`, `consumed_cell_count`, `right_censored_cell_count`, `mean_cell_lifetime_seconds`, `median_cell_lifetime_seconds`, `cell_lifetime_std`, `cell_lifetime_cv`, `cell_lifetime_p25`, `cell_lifetime_p75`, `cell_lifetime_p90`, `mean_cell_lifetime_blocks`, `median_cell_lifetime_blocks`, `short_lived_cell_ratio`, `long_lived_cell_ratio`, `rapid_consumption_ratio`, `same_block_consumption_ratio`, `cell_lifetime_entropy`, `cell_lifetime_repeat_ratio`

- **templates** — SHA-256 of canonical structural shape with TARGET sentinel, script family/hash, data length, topology, and 5%-rounded relative capacity; values: `unique_template_count`, `dominant_template_ratio`, `template_repeat_ratio`, `template_entropy`, `rare_template_ratio`, `template_transition_entropy`, `consecutive_template_repeat_ratio`, `template_periodicity_support`, `dominant_template_coverage`, `dominant_template_count`, `transition_repeat_ratio`

- **scripts** — exact code-hash/hash-type registry match; unmatched scripts remain canonical hashes; values: `unique_lock_script_count`, `unique_type_script_count`, `lock_family_count`, `type_family_count`, `lock_family_entropy`, `type_family_entropy`, `dominant_lock_family_ratio`, `dominant_type_family_ratio`, `unknown_lock_script_ratio`, `unknown_type_script_ratio`, `lock_script_repeat_ratio`, `type_script_repeat_ratio`, `script_transition_entropy`

- **typed_assets** — first 16 data bytes as uint128 little-endian; cached metadata is cross-check only; values: `typed_asset_count`, `asset_diversity`, `typed_cell_ratio`, `token_input_total`, `token_output_total`, `net_token_delta`, `token_turnover`, `repeated_token_amount_ratio`, `token_amount_entropy`, `token_fanout_ratio`, `token_fanin_ratio`

- **capacity** — structural Shannon-capacity distributions; occupied capacity only from explicit cached raw evidence; values: `input_capacity_mean`, `input_capacity_median`, `input_capacity_cv`, `output_capacity_mean`, `output_capacity_median`, `output_capacity_cv`, `capacity_repeat_ratio`, `capacity_input_entropy`, `capacity_output_entropy`, `target_created_capacity`, `target_consumed_capacity`, `target_net_capacity_delta`, `target_occupied_capacity`, `target_excess_capacity`

- **lineage** — directed bipartite hypergraph; depth in transaction hops; no pairwise routes; values: `lineage_depth`, `branch_count`, `merge_count`, `split_count`, `continuation_count`, `continuation_ratio`, `lineage_repetition`

## C. Cell lifecycle results

```json
{
  "INSUFFICIENT_EVIDENCE": 974,
  "SUPPORTED": 195,
  "UNRESOLVED": 3
}
```

## D. Temporal results

```json
{
  "INSUFFICIENT_EVIDENCE": 920,
  "SUPPORTED": 249,
  "UNRESOLVED": 3
}
```

Periodicity support:

```json
{
  "INSUFFICIENT_EVIDENCE": 947,
  "SUPPORTED": 222,
  "UNRESOLVED": 3
}
```

## E. Topology results

```json
{
  "INSUFFICIENT_EVIDENCE": 869,
  "SUPPORTED": 300,
  "UNRESOLVED": 3
}
```

## F. Template results

```json
{
  "INSUFFICIENT_EVIDENCE": 869,
  "SUPPORTED": 300,
  "UNRESOLVED": 3
}
```

## G. Script/type results

```json
{
  "INSUFFICIENT_EVIDENCE": 626,
  "PARTIAL": 4,
  "SUPPORTED": 539,
  "UNRESOLVED": 3
}
```

Typed-asset support:

```json
{
  "INSUFFICIENT_EVIDENCE": 1164,
  "PARTIAL": 5,
  "UNRESOLVED": 3
}
```
The verified xUDT deployment is present, but cached Cells lack the raw 16-byte data payload; Explorer amount metadata is retained as cross-check evidence, so typed-asset results remain support-limited.

## H. Capacity results

```json
{
  "INSUFFICIENT_EVIDENCE": 642,
  "SUPPORTED": 527,
  "UNRESOLVED": 3
}
```

## I. Cell lineage results

```json
{
  "INSUFFICIENT_EVIDENCE": 640,
  "SUPPORTED": 529,
  "UNRESOLVED": 3
}
```

## J. Behaviour-evidence rules

```json
{
  "BATCH_DISTRIBUTION": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  },
  "BURST_EXECUTION": {
    "INSUFFICIENT_EVIDENCE": 920,
    "SUPPORTED": 249,
    "UNRESOLVED": 3
  },
  "CELL_CONSOLIDATION": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  },
  "CELL_FRAGMENTATION": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  },
  "FAN_IN_COLLECTION": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  },
  "IRREGULAR_ACTIVITY": {
    "INSUFFICIENT_EVIDENCE": 947,
    "SUPPORTED": 222,
    "UNRESOLVED": 3
  },
  "MIXED": {
    "INSUFFICIENT_EVIDENCE": 1131,
    "SUPPORTED": 38,
    "UNRESOLVED": 3
  },
  "PASS_THROUGH_CANDIDATE": {
    "INSUFFICIENT_EVIDENCE": 974,
    "SUPPORTED": 195,
    "UNRESOLVED": 3
  },
  "PERIODIC_EXECUTION": {
    "INSUFFICIENT_EVIDENCE": 947,
    "SUPPORTED": 222,
    "UNRESOLVED": 3
  },
  "RAPID_CELL_TURNOVER": {
    "INSUFFICIENT_EVIDENCE": 974,
    "SUPPORTED": 195,
    "UNRESOLVED": 3
  },
  "SCRIPT_TEMPLATE_REPETITION": {
    "INSUFFICIENT_EVIDENCE": 869,
    "PARTIAL": 4,
    "SUPPORTED": 296,
    "UNRESOLVED": 3
  },
  "STATE_MACHINE_ACTIVITY": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  }
}
```

Positive threshold matches among evaluated observations (descriptive, not population prevalence):

```json
{
  "BATCH_DISTRIBUTION": 17,
  "BURST_EXECUTION": 4,
  "CELL_CONSOLIDATION": 15,
  "CELL_FRAGMENTATION": 1,
  "FAN_IN_COLLECTION": 28,
  "PASS_THROUGH_CANDIDATE": 1,
  "PERIODIC_EXECUTION": 32,
  "RAPID_CELL_TURNOVER": 11,
  "SCRIPT_TEMPLATE_REPETITION": 109,
  "STATE_MACHINE_ACTIVITY": 2
}
```

## K. Feature support matrix

```json
{
  "capacity": {
    "INSUFFICIENT_EVIDENCE": 642,
    "SUPPORTED": 527,
    "UNRESOLVED": 3
  },
  "lifecycle": {
    "INSUFFICIENT_EVIDENCE": 974,
    "SUPPORTED": 195,
    "UNRESOLVED": 3
  },
  "lineage": {
    "INSUFFICIENT_EVIDENCE": 640,
    "SUPPORTED": 529,
    "UNRESOLVED": 3
  },
  "periodicity": {
    "INSUFFICIENT_EVIDENCE": 947,
    "SUPPORTED": 222,
    "UNRESOLVED": 3
  },
  "scripts": {
    "INSUFFICIENT_EVIDENCE": 626,
    "PARTIAL": 4,
    "SUPPORTED": 539,
    "UNRESOLVED": 3
  },
  "templates": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  },
  "temporal": {
    "INSUFFICIENT_EVIDENCE": 920,
    "SUPPORTED": 249,
    "UNRESOLVED": 3
  },
  "topology": {
    "INSUFFICIENT_EVIDENCE": 869,
    "SUPPORTED": 300,
    "UNRESOLVED": 3
  },
  "typed_assets": {
    "INSUFFICIENT_EVIDENCE": 1164,
    "PARTIAL": 5,
    "UNRESOLVED": 3
  }
}
```

## L. Feature-quality audit

Numeric features audited: 139. Suspicious features are flagged, not removed.

## M. Feature redundancy report

High-correlation pairs: 93; near-duplicates: 9.

## N. ML-safe V2 export

- `/Users/fadhil/Personal/ckb-intel/ckb_data/feature_engineering_v2/wallet_behaviour_features_v2_ml.csv`
- Numeric predictors: 121
- No imputation was performed.

## O. Readiness

- **DATASET V1: READY** — content-addressed logical snapshot verified.
- **CELL LIFECYCLE: PARTIAL**
- **TEMPORAL V2: PARTIAL**
- **TOPOLOGY V2: PARTIAL**
- **TEMPLATES V2: PARTIAL**
- **SCRIPT FEATURES V2: PARTIAL**
- **TYPED ASSETS: PARTIAL**
- **CAPACITY V2: PARTIAL**
- **CELL LINEAGE: PARTIAL**
- **BEHAVIOUR EVIDENCE V2: PARTIAL** — support-qualified observable rules only.
- **ML FEATURE ANALYSIS: PARTIAL** — export is safe; missingness and redundancy require review.
- **CLUSTERING: NOT READY** — not run in this phase.

No Explorer collection, wallet retry, identity inference, ML, clustering, commit, or merge was performed.
