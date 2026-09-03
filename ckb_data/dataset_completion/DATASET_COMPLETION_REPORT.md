# Existing Dataset Completion Report

## A. Population

- Total wallets: 1172
- Population version: `ckb-wallet-population-local-v1`
- Manifest hash: `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe`

## B. Collection results

```json
{
  "COMPLETE": 939,
  "FAILED_INVALID_ADDRESS": 3,
  "FAILED_RETRY_EXHAUSTED": 224,
  "PARTIAL": 6
}
```

## C. Explorer utilization

```json
{
  "explorer_requests": 2249,
  "explorer_successes": 1211,
  "explorer_failures": 243,
  "explorer_retries": 791,
  "rate_limit_events": 0,
  "transaction_cache_hits": 4580,
  "transaction_cache_misses": 46862,
  "previous_output_cache_hits": 111896,
  "previous_output_cache_misses": 0,
  "raw_cache_hits": 4580,
  "normalized_cache_hits": 111896,
  "block_cache_hits": 0,
  "block_cache_misses": 0,
  "address_page_cache_hits": 294,
  "address_page_cache_misses": 1458,
  "transactions_fetched": 46862,
  "transactions_reused": 4580
}
```

## D. Observation quality

Transactions observed: 51816. Coverage distributions, feature/coverage correlations, and missingness are in `dataset_quality_v1.json`.

Applicable-input resolution (cellbase excluded):

```json
{
  "total_inputs": 92515,
  "applicable_inputs": 56407,
  "not_applicable_cellbase_inputs": 36108,
  "resolved_applicable_inputs": 56407,
  "unresolved_applicable_inputs": 0,
  "input_resolution_ratio": 1.0
}
```

## E. Feature readiness

```json
{
  "temporal": {
    "SUPPORTED": 249,
    "INSUFFICIENT_EVIDENCE": 920,
    "UNRESOLVED": 3
  },
  "topology": {
    "SUPPORTED": 300,
    "INSUFFICIENT_EVIDENCE": 869,
    "UNRESOLVED": 3
  },
  "templates": {
    "SUPPORTED": 300,
    "INSUFFICIENT_EVIDENCE": 869,
    "UNRESOLVED": 3
  },
  "scripts": {
    "SUPPORTED": 152,
    "INSUFFICIENT_EVIDENCE": 626,
    "UNRESOLVED": 3,
    "PARTIAL": 391
  },
  "capacity": {
    "SUPPORTED": 543,
    "INSUFFICIENT_EVIDENCE": 626,
    "UNRESOLVED": 3
  }
}
```

## F. Behaviour results

Population score distributions and independent ±20% threshold sweeps are recorded in `dataset_quality_v1.json`; wallet-level sweep results are in `wallet_behaviour_evidence_v1.jsonl`. Prevalence is not validated while collection is partial.

## G. Sampling-stratum diagnostics

```json
{
  "1-10": {
    "wallets": 154,
    "attempted": 154,
    "complete": 154,
    "partial": 0,
    "failed": 0,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 0,
    "completion_rate_among_attempted": 1.0
  },
  "1001-5000": {
    "wallets": 141,
    "attempted": 141,
    "complete": 128,
    "partial": 1,
    "failed": 12,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 13,
    "completion_rate_among_attempted": 0.9078014184397163
  },
  "11-50": {
    "wallets": 44,
    "attempted": 44,
    "complete": 44,
    "partial": 0,
    "failed": 0,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 0,
    "completion_rate_among_attempted": 1.0
  },
  "201-500": {
    "wallets": 27,
    "attempted": 27,
    "complete": 22,
    "partial": 0,
    "failed": 5,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 5,
    "completion_rate_among_attempted": 0.8148148148148148
  },
  "5000+": {
    "wallets": 54,
    "attempted": 54,
    "complete": 54,
    "partial": 0,
    "failed": 0,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 0,
    "completion_rate_among_attempted": 1.0
  },
  "501-1000": {
    "wallets": 17,
    "attempted": 17,
    "complete": 12,
    "partial": 0,
    "failed": 5,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 5,
    "completion_rate_among_attempted": 0.7058823529411765
  },
  "51-200": {
    "wallets": 29,
    "attempted": 29,
    "complete": 26,
    "partial": 0,
    "failed": 3,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 3,
    "completion_rate_among_attempted": 0.896551724137931
  },
  "unknown": {
    "wallets": 706,
    "attempted": 706,
    "complete": 499,
    "partial": 5,
    "failed": 202,
    "not_started": 0,
    "mean_detail_coverage": 1.0,
    "mean_input_resolution": 1.0,
    "censored_or_incomplete": 207,
    "completion_rate_among_attempted": 0.7067988668555241
  }
}
```

Selection-bias diagnostic:

```json
{
  "methodological_concern": true,
  "completion_rate_range": [
    0.7058823529411765,
    1.0
  ],
  "note": "Sampling strata are diagnostics only; failed and partial wallets remain included."
}
```

## H. Feature-quality audit

Constant/near-constant features, outliers, impossible values, and missingness are in `dataset_quality_v1.json`.

## I. ML-safe dataset

- `/Users/fadhil/Personal/ckb-intel/ckb_data/dataset_completion/wallet_behaviour_features_ml_v1.csv`
- Companion metadata: `/Users/fadhil/Personal/ckb-intel/ckb_data/dataset_completion/wallet_behaviour_features_ml_metadata_v1.csv`

## J. Manual-review evidence set

See `manual_review_examples_v1.json`.

Retry candidates are listed in `retry_candidates_v1.csv` and are not executed automatically after the first pass.

## K. Dataset readiness decision

- **FROZEN POPULATION ATTEMPTED: READY** — 1172/1172 wallets have terminal first-pass states.
- **DATASET COMPLETENESS: PARTIAL** — 939/1172 observations are complete.
- **EXPLORER RELIABILITY: PARTIAL** — failures by cause: `{"EXPLORER_HTTP_ERROR": 6, "EXPLORER_NETWORK_ERROR": 9, "EXPLORER_TIMEOUT": 203, "INVALID_ADDRESS": 3, "RETRY_EXHAUSTED": 6, "UNKNOWN": 6}`.
- **OBSERVATION QUALITY: PARTIAL** — incomplete wallets and support limits remain explicit.
- **FEATURE DATASET: PARTIAL** — unsupported values remain missing rather than zero.
- **BEHAVIOUR ANALYSIS: PARTIAL** — conclusions remain coverage-qualified and provisional.
- **ML FEATURE ANALYSIS: PARTIAL** — export is ML-safe, but readiness depends on completion.
- **CLUSTERING: NOT READY** — not run; review is required first.
- **SUPERVISED CLASSIFICATION: NOT READY** — no ground-truth labels and not run.

No wallet discovery, PCA, UMAP, clustering, or supervised learning was performed.
