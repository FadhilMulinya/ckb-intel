# CKB Wallet Behaviour Intelligence — Report V2
## Cell-Based Behavioural Modelling

> This is the **current, actively developed** methodology and supersedes the
> heuristic Random Forest classifier documented in `REPORT.md` (the
> legacy/abandoned baseline). `REPORT.md` is retained unmodified for
> historical record; it is not the final report or verified identity
> ground truth. See §9 below for a direct comparison between the two.

**Project:** CKB Wallet Behaviour Intelligence <br>
**Program:** Nervos Spark Program grant <br>
**Repo:** https://github.com/FadhilMulinya/ckb-intel <br>
**Report date:** September 7, 2026 <br>
**Predecessor report:** `REPORT.md` (August 2, 2026, revised August 10, 2026) <br>
**Author:** Fadhil Mulinya <br>
**Status:** active, in-progress research track — this documents work-in-progress
findings, not a finished deliverable.

---

## 1. Summary

This report documents the CKB-native, Cell-based behavioural modelling
pipeline that has replaced the proxy-label classifier in `REPORT.md`. The
core methodological shift is to **stop predicting a heuristic identity
label (human/bot) and instead describe observable CKB transaction/Cell
structure**, with every feature and rule explicitly qualified by how much
supporting evidence exists for it.

- **Data source:** real CKB mainnet only, fixed 30-day observation window
  (`2026-08-01T00:00:00Z` to `2026-08-31T00:00:00Z`)
- **Population:** 1,172 wallets; 939 complete / 6 partial / 224
  retry-exhausted / 3 invalid address
- **Feature space:** 9 CKB-native behavioural feature families, 121 numeric
  predictors, each with an explicit support/missingness state — no
  imputation, no zero-filling
- **Method:** transparent, non-inferential evidence rules (§4) plus
  exploratory PCA and clustering (§5-6) — no proxy labels, no
  `n_tx`-threshold ground truth, and no accuracy claims against unverified
  labels
- **Core finding:** the CKB-native feature space is real, reproducible,
  and rich enough for exploratory behavioural structure, but that
  structure is **representation-dependent** and the pipeline is
  **explicitly not suitable for supervised identity classification**
  (§7-8)

---

## 2. What changed vs. the legacy baseline

| | `REPORT.md` (legacy) | This report (current) |
|---|---|---|
| Ground truth | Heuristic tx-count threshold labels | None — label-free, evidence-driven |
| Transaction model | Account-style counterparty graph | CKB-native Cell model (inputs/outputs, locks, types) |
| Feature space | 10 hand-picked features, single flat table | 121 numeric predictors across 9 CKB-native feature families, each with explicit support/missingness state |
| Missing data | Rows with <2 tx dropped | Never zero-filled; `INSUFFICIENT_EVIDENCE` / `UNRESOLVED` / `PARTIAL` are explicit states, no imputation |
| Output | Random Forest classification (`bot_probability`) | Transparent rule scores (SUPPORTED/PARTIAL/INSUFFICIENT_EVIDENCE) + exploratory PCA/clustering structure |
| Claim made | "95.24% accuracy" identity classifier | Descriptive behavioural structure; explicitly **not** suitable for identity/supervised classification (see §7) |

---

## 3. Dataset and collection

- Dataset: `ckb-behaviour-dataset-v1`; population version
  `ckb-wallet-population-local-v1`; manifest hash
  `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe`.
- 1,172 wallets attempted; **939 complete / 6 partial / 224 retry-exhausted /
  3 invalid address** (first-pass terminal states for the full population).
- Fixed 30-day observation window (blocks 20,025,197-20,311,450), resolved
  via CKB's non-decreasing consensus timestamp metric (median of the
  preceding 37 canonical blocks, RFC 0017), with local CKB RPC tried first
  and Explorer as fallback.
- 51,816 transactions observed; of 92,515 total inputs, 56,407 are
  applicable (non-cellbase) previous outputs, and **100% (56,407/56,407)
  resolved** to source cells.
- Explorer reliability during full collection: 2,249 requests, 1,211
  successes, 243 failures, 791 retries, 0 rate-limit events. Failure
  causes: timeouts (203), invalid address (3), retry-exhausted (6), HTTP
  error (6), network error (9), unknown (6).
- Sampling-stratum diagnostics show a **selection-bias caveat**: completion
  rate among attempted wallets ranges from 70.6% (`501-1000` stratum) to
  100% (`1-10`, `11-50`, `5000+`); failed/partial wallets are retained in
  the manifest rather than dropped.
- A separate 30-day re-validation on the existing wallet inventory (1,172
  wallets from 5,458 source occurrences) reused 54,794 cached transaction
  records with 0 new Explorer requests, confirming the caching/resumability
  path is stable and leakage-free (changing legacy labels, lifetime counts,
  strata, predictions, or clusters does not change feature or rule output).

---

## 4. CKB-native behavioural feature engineering

Feature schema `ckb-behaviour-features-v1`, script registry
`ckb-script-registry-v1`, implemented against the actual CKB Cell model
(inputs/outputs, lock/type scripts, capacity) rather than an
account-balance abstraction. Nine feature families, 121 numeric predictors
total:

| Family | What it measures | Support model |
|---|---|---|
| Temporal | Interarrival gaps, sessions, bursts, hour/day concentration | Requires ≥8 tx for periodicity; unmeasurable = `null`, never 0 |
| Periodicity | Median/MAD dominant period, phase stability, autocorrelation, 4 weekly subwindows | `exp(-median_absolute_interval_deviation / dominant_period)`; single dominant cadence by design |
| Topology | Fan-in/fan-out Cell and lock structure | Structural only — does **not** assert who paid whom |
| Cell lifecycle | Creation→consumption lifetime, right-censoring of unconsumed cells | Requires local join evidence |
| Templates | SHA-256 canonical structural shape (Cell counts, script family, data length, 5%-rounded capacity shape) | Excludes tx hash, block, timestamp, witnesses, signatures |
| Scripts | Lock/type family diversity via exact code-hash+hash-type registry match (SECP256K1_BLAKE160, SECP256K1_MULTISIG, NERVOS_DAO from RFC 0024) | Unknown scripts kept as `UNKNOWN`, hash retained |
| Capacity | Structural input/output capacity distributions, target-controlled capacity | Structural, not an economic-value claim |
| Cell lineage | Directed bipartite hypergraph depth, branch/merge/split/continuation | Local observation only, no pairwise routes |
| Typed assets (xUDT) | First-16-byte uint128 decoding groundwork | Cached payloads currently insufficient — **excluded** from primary matrices |

V2 support results across the 1,172-wallet population (SUPPORTED /
INSUFFICIENT_EVIDENCE / UNRESOLVED / PARTIAL counts): topology and
templates each 300 supported; capacity 527; lineage 529; scripts 539
(+4 partial); temporal 249; periodicity 222; cell lifecycle 195; typed
assets only 5 partial (0 fully supported). Numeric predictors audited:
139; high-correlation feature pairs: 93; near-duplicate groups: 9.

### 4.1 Feature validation and ML readiness

Of the 121 ML-safe predictors: 17 `USABLE`, 99 `SPARSE`, 5 `CONSTANT`
(no automatic removal from canonical V2). Zero impossible values; 233
flagged extreme/manual-review cases (flagged, not removed/clipped).
Activity-leakage audit: 12 predictors `HIGH_ACTIVITY_DEPENDENCE`
(|Spearman ρ| ≥ 0.8, e.g. `temporal__transaction_count`,
`temporal__positive_gap_count`), 22 `MODERATE`, 87 `LOW`; raw
transaction/cell/input/output counts are excluded from primary candidate
matrices as diagnostics only.

Four candidate matrices were produced:

| Matrix | Features | Complete cases | Purpose |
|---|---|---|---|
| Broad | 104 | 493 wallets ≥20% support | Research/diagnostic |
| Core | 95 | 300 wallets ≥50% support | Exploratory ML |
| Low-Redundancy Core | 59 | 300 wallets ≥50% support | Family-block diagnostics |
| **High-Confidence** | **10** | **513 wallets, 100% support** | **Primary discovery reference** |

High-Confidence features: `capacity__target_consumed_capacity`,
`capacity__target_net_capacity_delta`, `capacity__capacity_repeat_ratio`,
`lineage__lineage_depth`, `lineage__continuation_count`,
`lineage__lineage_repetition`, `lineage__merge_count`,
`scripts__type_family_count`, `scripts__unique_lock_script_count`,
`scripts__unique_type_script_count`.

Four-week stability analysis found periodicity/template features
moderately-to-highly rank-stable (Spearman 0.75-0.93) across adjacent
weeks, while `topology_repeat_ratio` was unstable (0.15-0.32).

---

## 5. Transparent, non-inferential evidence rules

Twelve rule-based behaviour patterns (e.g. `PERIODIC_EXECUTION`,
`BATCH_DISTRIBUTION`, `FAN_IN_COLLECTION`, `CELL_FRAGMENTATION`,
`CELL_CONSOLIDATION`, `SCRIPT_TEMPLATE_REPETITION`) are scored as the
fraction of documented numeric checks a wallet passes. For example:

| Pattern | Exact requirements for full score |
|---|---|
| PERIODIC_EXECUTION | ≥8 transactions, periodicity strength ≥0.80, phase stability ≥0.75, interarrival CV ≤0.35 |
| BATCH_DISTRIBUTION | ≥3 transactions, fan-out ratio ≥0.50, mean external output locks ≥2.0, template repeat ratio ≥0.50 |
| FAN_IN_COLLECTION | ≥3 transactions, fan-in ratio ≥0.50, mean external input locks ≥2.0, topology repeat ratio ≥0.50 |

Results are `SUPPORTED` (all checks, full data), `PARTIAL` (incomplete
coverage), or `INSUFFICIENT_EVIDENCE` (too few transactions; null score) —
never a binary bot/human verdict.

Across the population, positive threshold matches were, for example:
`PERIODIC_EXECUTION` 32, `FAN_IN_COLLECTION` 28, `BATCH_DISTRIBUTION` 17,
`CELL_CONSOLIDATION` 15, `SCRIPT_TEMPLATE_REPETITION` 109 (these are
descriptive counts among evaluated observations, **not** a population
prevalence claim). A ±20% threshold sensitivity sweep on the validation
cohort found 27 of 27 detections stable and 0 threshold-sensitive.

Rules explicitly do **not** infer operators, economic counterparties,
automated ownership, or pairwise value transfer.

---

## 6. Exploratory ML

### 6.1 PCA

Experiment `ckb-exploratory-ml-pca-v1`, complete-case only (no
imputation), centered covariance eigendecomposition. On the
High-Confidence matrix (513 wallets × 10 features):

| Metric | Value |
|---|---|
| PC1 variance | 39.24% |
| PC1+PC2 | 58.03% |
| First 3 PCs | 72.37% |
| First 5 PCs | 86.74% |
| Components for 95% variance | 8 |
| Bootstrap stability (500 resamples), median loading cosine | 0.9839 |
| Max PC1-PC5 correlation with raw activity volume | 0.6997 |
| Components flagged `HIGH_ACTIVITY_ASSOCIATION` | 0 |

No single feature family dominates any of the top 5 components (lineage
strongest on PC1-PC3, scripts on PC4, capacity on PC5). A parallel 28×59
Low-Redundancy PCA experiment was **rejected** on a locked feasibility
gate (requires n≥100 and n/p≥5; observed n=28, p=59). Family-block
sensitivity experiments (e.g. an 18-feature, 172-wallet Cell-structure
block) were run as complements to, not replacements for, the
High-Confidence reference.

### 6.2 Clustering (HDBSCAN / GMM)

Contract `ckb-exploratory-structure-v1`; no imputation, labels, rules,
activity diagnostics, or prior clusters entered discovery.

- An HDBSCAN sensitivity audit ran 192 grid combinations across 8
  representations; only **3** met the resampling stability threshold, all
  PCA views (PCA3, PCA4, PCA6), producing 2, 3, and 2 groups respectively.
  The full 10-feature scaled High-Confidence space itself was
  **unstable**, so group count is representation-dependent, not a fixed
  answer.
- Using PCA4 (the predeclared ~80%-variance view) for evidence review
  only, 3 groups were profiled against the original scaled features: one
  interpretable as low target-consumed-capacity structure, one as
  script-type-diverse structure, and one left `UNINTERPRETED`.
- An independently-fit GMM sensitivity check materially **disagreed**
  with HDBSCAN (e.g. ARI 0.29, AMI 0.51 on the High-Confidence view;
  ARI/AMI 0.0 on the temporal-only view) — treated as a disagreement to
  report, not resolved in favor of either method.
- UMAP was run for visualization only; its coordinates were never
  clustered.

---

## 7. Data quality and ML-suitability verdict

An independent September 7, 2026 data-quality and ML-suitability review rated:

| Criterion | Verdict |
|---|---|
| Data collection quality | ✅ GOOD — 100% input resolution, cryptographic manifest/database integrity verified |
| Preprocessing | ✅ COMPLETE & RIGOROUS — support-aware features, no imputation, documented scaling |
| Distribution analysis | ⚠️ PARTIAL — representation-dependent clustering, no HDBSCAN/GMM agreement |
| ML suitability | ⚠️ PARTIAL — exploratory only |

Suitable for exploratory behavioural-structure analysis, but **explicitly
not suitable for supervised human/bot classification** (no verified
ground truth) and **not generalizable to all CKB wallets** (non-random
sample, single 30-day period, 19% collection failure rate retained in the
population).

That review's final verdict table:

| Criterion | Verdict | Details |
|---|---|---|
| Data Quality | ✅ GOOD | Complete resolution, verified integrity, transparent provenance |
| Preprocessing | ✅ EXCELLENT | Rigorous, transparent, CKB-native, no imputation |
| Suitable for exploratory behavioural analysis | ✅ YES | Rich features, clear structures, interpretable patterns |
| Suitable for identity classification | ❌ NO | No verified ground truth, legacy labels heuristic only |
| Generalizable to all CKB wallets | ⚠️ NO | Non-random sample, single time period, collection failures |
| Reproducible | ✅ YES | 80 passing tests, cryptographic verification, offline path |
| Publication ready | ✅ YES | Comprehensive documentation, negative results explicit |

---

## 8. Readiness summary

| Component | Status |
|---|---|
| Dataset collection (1,172-wallet population) | PARTIAL — 939/1,172 complete, retained with explicit failure states |
| Behaviour features (V2, 9 families, 121 predictors) | PARTIAL — support-qualified, no leakage found |
| Feature validation / ML readiness | PARTIAL — candidate matrices exist; cohort/scaling choices not yet locked |
| PCA | PARTIAL — High-Confidence view executed and stable; not yet locked as final |
| UMAP | PARTIAL/READY for visualization only — never clustered |
| HDBSCAN | NOT READY — only 3/8 representations resampling-stable |
| GMM | NOT READY — disagrees materially with HDBSCAN |
| Supervised classification | NOT READY — no defensible ground-truth labels exist on this track either |

---

## 9. Comparison with the legacy baseline (`REPORT.md`)

### 9.1 Abandoned approach (`REPORT.md`)

- Random Forest classifier on heuristic labels (1-50 tx → human;
  ≥1,000 tx → bot)
- Reported 95.24% accuracy
- 264 labeled addresses (104 human, 160 bot)

**Problems with the legacy approach:**
- ❌ Heuristic labels not verified ground truth
- ❌ No CKB-native feature engineering
- ❌ No explicit evidence rules
- ❌ No sparse-feature handling
- ❌ Not reproducible from CKB mainnet
- ❌ Confused proxy labels with identity

### 9.2 This report's approach

**Improvements:**
- ✅ Label-free, evidence-driven analysis
- ✅ CKB-native transaction/cell model
- ✅ Support-aware feature engineering
- ✅ Explicit evidence documentation
- ✅ Reproducible from mainnet data
- ✅ Negative results reported honestly
- ✅ Behavioural structure (not identity) focus

**Trade-offs:**
- From 251 training samples → exploratory structures only
- From 95.24% "accuracy" → partial structural patterns
- From identity classification → behavioural description

---

## 10. Next steps

1. Lock a single cohort, missing-data strategy, and scaling choice before
   any further UMAP/HDBSCAN/GMM work, per the readiness gates in §8.
2. Extend collection beyond the single fixed 30-day window to test
   temporal generality of the behavioural structures found in §6.
3. Refill the 790 wallets identified as needing full 30-day collection
   and the 382 needing none, per the existing-wallet completion estimate.
4. Investigate CKB `since`-field semantics to separate protocol-driven
   from discretionary behaviour, and continue treating any cluster/PCA
   output as descriptive structure, not identity or ownership inference.
5. Do not reuse `REPORT.md`'s heuristic labels for any part of this
   track; the label-free framing is a deliberate methodological choice,
   not a gap to be filled in.
6. Collect verified ground-truth labels via independent methods, if
   possible, before any supervised-classification work is attempted.
