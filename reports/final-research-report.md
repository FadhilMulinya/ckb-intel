# CKB Wallet Behaviour Intelligence

## 1. Executive Summary

This project delivers a reproducible CKB-native wallet-behaviour research pipeline. It replaced an inadequate lifetime-transaction-count proxy classifier with fixed-window transaction/Cell reconstruction, support-aware feature engineering, validation, PCA diagnostics, cautious unsupervised discovery, and evidence review. Reproducible structure exists in portions of the feature space, but the evidence does not support a definitive global wallet taxonomy or human/bot identity classifier.

## 2. Research Objective and Methodology Revision

The objective is to describe observable CKB mainnet behaviour. The historical 95.24% result measured a Random Forest against heuristic `human_like`/`bot_like` thresholds, not verified identities. It is retained as an abandoned baseline and is not a grant-completion metric.

## 3. Dataset and CKB-Native Data Model

The frozen August 2026 dataset contains 1,172 wallets: 939 complete, 6 partial, 224 retry-exhausted, and 3 invalid. It contains 51,816 transactions. All 56,407 applicable inputs resolve; 36,108 Cellbase inputs are `NOT_APPLICABLE`. Manifest and database hashes are `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe` and `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`.

The population was assembled from overlapping historical local sources, including an earlier recent-mainnet-activity discovery run, rather than random global sampling. Of 1,172 wallets, 425 retain provenance-only legacy proxy metadata (222 `bot_like`, 203 `human_like`); 747 have none. These fields were excluded from Feature V2, PCA, HDBSCAN, GMM, and final interpretation. The cohort is reproducible but not statistically representative of all CKB wallets, limiting external generalization.

Transactions consume prior Cells and create new Cells with capacity and lock/type scripts. Wallet control is lock-based. This hypergraph-like model avoids unsupported pairwise sender/recipient or economic-transfer attribution.

## 4. Feature Engineering V2

V2 covers temporal and periodic structure, Cell lifecycle, topology, canonical transaction templates, scripts, capacity, and Cell lineage, plus typed-asset groundwork. Twelve transparent rules retain transaction/Cell evidence. Typed assets were excluded from primary ML because cached raw payload evidence was insufficient for full support. Missing means unsupported/unobserved, not zero.

## 5. Feature Validation

Of 121 numeric predictors, 17 are usable, 99 sparse, and 5 constant; none had impossible values. Candidate matrices contain 104 Broad, 95 Core, 59 Low-Redundancy, and 10 High-Confidence predictors. Activity dependence was HIGH for 12, MODERATE for 22, and LOW for 87. The High-Confidence matrix has 513 complete cases; the 59-feature complete-case experiment was rejected at 28 wallets without imputation.

Broad and Core are sparse research/diagnostic candidate spaces, not equally strong final analysis matrices. The strongest conclusions use the High-Confidence reference: 10 predictors, 513 complete-case wallets, no imputation, and documented support/activity selection.

## 6. PCA Diagnostics

High-Confidence PC1 explains 39.24%; PC1–2 58.03%; PC1–3 72.37%; PC1–5 86.74%. Median PC1–PC5 bootstrap loading cosine similarity is 0.9839 across 500 resamples. Maximum activity association is about 0.70, below the 0.80 HIGH threshold.

## 7. Behavioural Structure Discovery

HDBSCAN audited 192 configurations and eight representations. Full scaled High-Confidence was unstable. PCA3, PCA4, and PCA6 were robust but yielded 2, 3, and 2 groups, demonstrating representation dependence. Temporal and Cell views were mixed. GMM selected substantially different structures and did not confirm HDBSCAN. UMAP was visualization-only.

## 8. Evidence-Supported Structural Groups

- `LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE`: PCA4 group distinguished by substantially lower target-consumed-capacity structure; it is not a low-value or identity claim.
- `SCRIPT_TYPE_DIVERSE_STRUCTURE`: PCA4 group distinguished by higher type-script-family diversity; it does not identify an application or owner.
- `UNINTERPRETED`: separation was insufficiently specific for a stronger descriptive name.

All three groups had LOW post-hoc activity dependence. Activity fields and transparent rules did not enter clustering.

## 9. Negative Results and Limitations

The full scaled primary space was unstable; retained-PC choices changed group count; GMM disagreed; Low-Redundancy complete cases were infeasible; typed-asset analysis remained unsupported; 230 observations are partial/retry-exhausted; one group is uninterpreted; and there is no identity ground truth. The single 30-day window limits generality.

CKB absolute and relative `since` semantics are outside the feature model. Timelocked or protocol-constrained Cell lifetimes can therefore appear as long-lived structure; the project does not distinguish protocol-enforced lifetime from discretionary wallet behaviour in those cases. The historically sourced cohort is also not a representative global sample.

## 10. Reproducibility and Deliverables

Run `./scripts/verify_final_research.sh .venv/bin/python` after installing `requirements-research.txt`. The offline verifier checks hashes, contracts, row alignment, SQLite integrity, and 80 tests.

The approximately 863 MB frozen database is distributed separately at `<DATASET_RELEASE_URL>` as `ckb-behaviour-dataset-v1.sqlite`. Reviewers place it at `ckb_data/ckb_data_v2/ckb_explorer.sqlite`; the verifier checks SHA-256 `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`.

| Grant area | Status | Verification |
|---|---|---|
| Dataset | Complete frozen first pass | 1,172 rows, contracts, hashes, explicit failures |
| Feature extraction | Complete V2 | 121 audited numeric predictors and structured evidence |
| Behaviour analysis | Partial scientific result | PCA/HDBSCAN stability, ARI/AMI, noise, activity and evidence review |
| Baseline/model analysis | Methodology revised | Proxy classifier retained only as legacy; no invalid accuracy/F1 claim |
| API/CLI/reproduction | Offline research path ready | Phase scripts, verifier, artifact index |

## 11. How to Verify

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-research.txt
./scripts/verify_final_research.sh .venv/bin/python
```

## 12. Final Conclusion

The project establishes a reproducible CKB-native wallet-behaviour analysis pipeline and demonstrates that stable structural patterns can emerge from Cell, script, capacity, lineage, temporal, and transaction-template evidence. However, the observed unsupervised structure is representation-dependent and does not support a definitive global wallet taxonomy or human/bot identity classifier.
