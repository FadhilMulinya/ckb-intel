# Existing Wallet 30-Day Validation Report

Fixed window: `2026-08-01T00:00:00Z` to `2026-08-31T00:00:00Z`.

## A. Existing wallet inventory

1172 unique wallets from 5458 source occurrences; 4286 duplicate occurrences. Historical labels are preserved only as `legacy_proxy_label`.

## B. Activity-spectrum coverage

| Stratum | Wallets | Percent | Inventory heuristic |
|---|---:|---:|---|
| 1-10 | 154 | 13.14% | sufficient |
| 11-50 | 44 | 3.75% | sufficient |
| 51-200 | 29 | 2.47% | sufficient |
| 201-500 | 27 | 2.3% | sufficient |
| 501-1000 | 17 | 1.45% | sufficient |
| 1001-5000 | 141 | 12.03% | sufficient |
| 5000+ | 54 | 4.61% | sufficient |
| unknown | 706 | 60.24% | not assessed |

The ten-wallet threshold is an inventory heuristic, not a statistical-power claim.

## C. Existing data reuse

Raw wallet evidence: 380; wallets with native normalized observations currently: 13. The local JSONL contains 54794 records, 45001 unique transaction hashes, and 9793 shared/duplicate records. This run added 0 transactions and reused 54794 cache entries.

## D. Explorer requirements

Zero-request candidates: 382; partial refill: 0; full collection: 790. The known-count listing upper bound is 31927 requests; transaction-detail totals remain dependent on 30-day activity and shared-cache reuse.

## E. One-wallet validation

- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqwdr5q4rwruykhehd8hn6gxh892wtmdprcw3h3ce` — stratum 5000+; 64 tx; detail=1.0; inputs=1.0; Explorer requests=0; PERIODIC_EXECUTION=PARTIAL(0.0), BATCH_DISTRIBUTION=PARTIAL(0.3333333333333333), FAN_IN_COLLECTION=PARTIAL(0.3333333333333333)

## F. 5–10 wallet validation

- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2yr93x7eusaallmfayyemrlff66pd7v9s34kwg9` — stratum 1-10; 0 tx; detail=None; inputs=None; Explorer requests=0; PERIODIC_EXECUTION=INSUFFICIENT_EVIDENCE(None), BATCH_DISTRIBUTION=INSUFFICIENT_EVIDENCE(None), FAN_IN_COLLECTION=INSUFFICIENT_EVIDENCE(None)
- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq0uddvtx7dvuxl3cyasr6820dwuslmvvnqa8qtus` — stratum 11-50; 9 tx; detail=1.0; inputs=1.0; Explorer requests=0; PERIODIC_EXECUTION=SUPPORTED(1.0), BATCH_DISTRIBUTION=PARTIAL(0.3333333333333333), FAN_IN_COLLECTION=PARTIAL(0.3333333333333333)
- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqgrz3hvgkrdt2k7cfdpwj8dfnunvjtssssjl8n5h` — stratum 51-200; 0 tx; detail=None; inputs=None; Explorer requests=0; PERIODIC_EXECUTION=INSUFFICIENT_EVIDENCE(None), BATCH_DISTRIBUTION=INSUFFICIENT_EVIDENCE(None), FAN_IN_COLLECTION=INSUFFICIENT_EVIDENCE(None)
- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqdjsydf39sklhfvtfnk57vvd7d2vn4kxwqpr3prn` — stratum 201-500; 30 tx; detail=1.0; inputs=1.0; Explorer requests=1; PERIODIC_EXECUTION=PARTIAL(0.0), BATCH_DISTRIBUTION=PARTIAL(0.3333333333333333), FAN_IN_COLLECTION=PARTIAL(0.6666666666666666)
- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqgzgak4nyyfjzlcnx6lel86kkl9wmn8cmqg5mv52` — stratum 501-1000; 27 tx; detail=1.0; inputs=1.0; Explorer requests=1; PERIODIC_EXECUTION=PARTIAL(0.0), BATCH_DISTRIBUTION=PARTIAL(0.0), FAN_IN_COLLECTION=PARTIAL(0.0)
- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2pgrf442dam0aa0l8gd2s8jlxfu7hha3c7hg4qq` — stratum 1001-5000; 25 tx; detail=1.0; inputs=1.0; Explorer requests=0; PERIODIC_EXECUTION=PARTIAL(0.0), BATCH_DISTRIBUTION=PARTIAL(0.3333333333333333), FAN_IN_COLLECTION=PARTIAL(0.3333333333333333)
- `ckb1qpl0dc3xe2dr299vwe6e7zc42rnsex4pptlcjyglahevnkqq6ft0wqgw8xxul` — stratum 5000+; 9 tx; detail=1.0; inputs=1.0; Explorer requests=0; PERIODIC_EXECUTION=PARTIAL(0.0), BATCH_DISTRIBUTION=PARTIAL(0.6666666666666666), FAN_IN_COLLECTION=SUPPORTED(1.0)
- `ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqwjzhp5ljeurdf9yznes3xhs7cn6ye9mssmxkwgz` — stratum 1001-5000; 15 tx; detail=1.0; inputs=1.0; Explorer requests=0; PERIODIC_EXECUTION=PARTIAL(0.0), BATCH_DISTRIBUTION=PARTIAL(0.3333333333333333), FAN_IN_COLLECTION=PARTIAL(0.6666666666666666)

## G. Cache statistics

The successful live acquisition used 56 Explorer requests (54 shared boundary requests and 2 wallet-listing requests), with 57 missing transactions persisted globally. The final resumability pass then produced:

```json
{
  "explorer_failures": 0,
  "explorer_requests": 0,
  "explorer_retries": 0,
  "explorer_successes": 0,
  "normalized_cache_hits": 55358,
  "previous_output_cache_hits": 563,
  "previous_output_cache_misses": 0,
  "rate_limit_events": 0,
  "raw_cache_hits": 0,
  "transaction_cache_hits": 54794,
  "transaction_cache_misses": 0
}
```

## H. Leakage audit

**PASS** — changing legacy labels, lifetime counts, strata, predictions, and clusters did not change feature or rule output.

## I. Threshold sensitivity

Across wallet/rule combinations, 27 detections were stable and 0 were threshold-sensitive when every current threshold was varied ±20%. Defaults were not changed; per-wallet results are in `validation_results_v1.json`.

## J. Existing dataset completion estimate

382 wallets need no remote refill, 0 need partial refill, and 790 need full 30-day collection. Known lifetime counts imply at most 31927 listing-page requests before cache reuse; detail cost remains unresolved for unknown-count wallets. Expected cache reuse increases as shared transactions accumulate.

## K. Missing sampling strata

Underrepresented: none; do not collect new wallets.

## L. Readiness

- **EXISTING WALLET MANIFEST: READY** — 1172 deduplicated records have explicit missing-value states.
- **30-DAY OBSERVATION: READY** — The validation wallets use one fixed window and shared proven block boundaries.
- **EXPLORER PIPELINE: READY** — The bounded live run had no failures, retries, or rate limits.
- **CACHE / RESUMABILITY: READY** — The repeated validation needed zero Explorer requests and reused global evidence.
- **INPUT RESOLUTION: READY** — All inputs in transaction-bearing validation observations resolved.
- **BEHAVIOUR FEATURES: PARTIAL** — All families ran without label leakage, but script/minimum-support evidence is incomplete for part of the cohort.
- **CURRENT LOCAL DATASET: PARTIAL** — 382 wallets are locally complete; 790 require refill.
- **NEW WALLET COLLECTION REQUIRED: NO** — Every known stratum exceeds the ten-wallet inventory heuristic.
- **ML / CLUSTERING: NOT READY** — Model work was prohibited and evidence is not complete population-wide.

Recommended research gates: exact observation boundary and complete listing; detail coverage 1.0; input resolution 1.0 for topology/template rules; and each feature family's existing minimum transaction support. Wallets failing a gate remain in the manifest as PARTIAL, INSUFFICIENT_EVIDENCE, or UNRESOLVED.

No ML, clustering, wallet discovery, pairwise attribution, identity inference, or population-level validation was performed.
