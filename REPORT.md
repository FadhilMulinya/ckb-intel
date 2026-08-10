# CKB Wallet Behaviour Intelligence - Formal Analysis Report

**Project:** CKB Wallet Behaviour Intelligence <br>
**Program:** Nervos Spark Program grant <br>
**Repo:** https://github.com/FadhilMulinya/ckb-intel <br>
**Report date:** August 2, 2026 <br>
**Revised:** August 10, 2026 - corrects §2.2's "manually verified / gold
standard" labeling claim, adds §2.4 (label sensitivity analysis) and the
sampling limitations in §2.3, per the committee's review response <br>
**Author:** Fadhil Mulinya <br>

---

## 1. Summary

This report documents the current state of the CKB Wallet Behaviour
Intelligence model, per the committee's July 2026 pivot ruling: the
project now trains and evaluates exclusively on real CKB mainnet
transaction data, with all synthetic/bot-simulator data paths removed.

- **Data source:** real CKB mainnet only (via `mainnet-api.explorer.nervos.org`)
- **Dataset size:** 264 labeled addresses on disk (104 human-like, 160
  bot-like); 251 rows actually used in the most recent training run
  (91 human-like, 160 bot-like) - see §2.1 for why those numbers differ
- **Model:** Random Forest classifier, selected via cross-validation
  against Logistic Regression, Gradient Boosting, and SVM-RBF
- **Core deliverable:** documented behavioral dimensions and feature
  weights (Section 5), positioned per the committee's guidance as the
  reusable foundation for future ecosystem projects - independent of
  the specific model architecture

---

## 2. Dataset

### 2.1 Composition

| Label | Addresses on disk (`data/real/`) | Rows used in most recent training run |
|---|---|---|
| Human-like | 104 | 91 |
| Bot-like / automated | 160 | 160 |
| **Total** | **264** | **251** |

The gap (104 vs. 91 human-like) is not a discrepancy to be resolved -
it's `extract_features_real.py` doing what it's supposed to: it skips
any address with fewer than 2 transactions, because interval-based
features are undefined with 0-1 transactions. 13 of the 104 labeled
human-like addresses on disk didn't clear that bar for this training
run. All metrics in this report (§4, §5) reflect the 251-row trained
set, not the 264 on-disk count.

### 2.2 Labeling methodology

**Correction to an earlier version of this report:** this section
previously stated that all labels were "manually verified" against a
"gold standard." That description is not accurate, and is inconsistent
with `train_eval.py`, the classifier README, and `eval_results.json`,
all of which correctly describe the labels as heuristic proxy labels
rather than verified ground truth. The text below replaces the
earlier, inaccurate description.

Labels are generated via a heuristic - a lifetime-transaction-count
threshold (1-50 lifetime transactions -> `human_like`; ≥1,000 -> `bot_like`;
addresses in between are excluded). These thresholds are initial
proxy-label boundaries, not derived from a formal CKB-specific study,
known-identity dataset, or established research source; see §4 for the
sensitivity analysis that tests how robust the resulting labels and
model are to changes in them.

Two people (the author and a second contributor) separately inspected
the trained addresses' transaction histories (timing pattern, amounts,
counterparty behavior) alongside the heuristic label, as a supporting
sanity check rather than a formal, blind, independent annotation
study - the heuristic label was visible during review, no formal
disagreement-resolution procedure was applied, and no inter-annotator
agreement statistic was calculated. No disagreements were found between
the heuristic label and reviewer judgment, but the absence of a
disagreement in this informal review is not equivalent to verified
ground truth, and is not being represented as such.

**The accurate framing:** labels are heuristic proxy labels, individually
spot-checked by two reviewers with zero recorded disagreements, not a
gold-standard verified dataset. The 95.24% held-out accuracy reported in
§4.2 is accuracy against these heuristic proxy labels, not a verified
accuracy for identifying human vs. automated wallet ownership.

### 2.3 Known limitations

Publicly discoverable CKB wallets skew toward exchange/service wallets
rather than representative individual users, which constrains the
diversity of the human-like class. This is a data-availability
constraint noted from the start of the project, not a methodology gap.

Two additional sampling limitations, surfaced by the sensitivity
analysis in §4:

- **Transaction-window asymmetry.** `human_like` wallets (≤50 lifetime
  tx) have their complete history captured within the 300-tx return cap
  used at collection time. `bot_like` wallets (≥1,000 lifetime tx) only
  ever have up to 300 transactions represented out of a much larger
  history, so timing/interval features for the bot class are computed
  from a partial window, not full lifetime behavior.
- **Label decay over time.** Because lifetime transaction count only
  grows, the `human_like`/excluded boundary is not stable even at fixed
  thresholds. Re-deriving labels from freshly-fetched transaction counts
  shows roughly 5.5% of the trained `human_like` class (5 of 91) has
  already drifted out of range since original collection (none moved to
  `bot_like` - that class shows zero drift at any threshold ≥1,000,
  since an address that already cleared it can't fall back below it).
  The "91 human-like addresses" figure in §2.1 should be read as a
  snapshot as of the original collection date, not a static property of
  those addresses going forward.

### 2.4 Label sensitivity / robustness analysis

To test how robust the resulting labels and model are to the threshold
choices in §2.2, all 9 combinations of `bot_min_tx` in {500, 1,000,
2,000} x `human_max_tx` in {20, 50, 100} were re-run through the same
model-selection/evaluation code used in §4, against the existing
264-address committed pool. Random Forest was selected in every case;
held-out accuracy stayed in the 95.2%-100% range throughout.

| bot_min_tx | human_max_tx | n_bot | n_human | held-out acc | changed vs. current |
|---|---|---|---|---|---|
| 500 | 20 | 160 | 66 | 98.3% | 25 |
| 500 | 50 | 160 | 86 | 95.2% | 5 |
| 500 | 100 | 160 | 91 | 95.2% | 0 |
| 1000 | 20 | 160 | 66 | 98.3% | 25 |
| **1000** | **50 (current)** | **160** | **86** | **95.2%** | **5** |
| 1000 | 100 | 160 | 91 | 95.2% | 0 |
| 2000 | 20 | 90 | 66 | 100% | 95 |
| 2000 | 50 | 90 | 86 | 95.5% | 75 |
| 2000 | 100 | 90 | 91 | 95.7% | 70 |

**Findings:**

- Raising `bot_min_tx` to 2,000 is a meaningful test: only 90 of the
  original 160 `bot_like` addresses (56%) still clear a doubled
  threshold.
- The `bot_min_tx = 500` rows are **not** evidence of robustness to a
  looser bot threshold. This analysis can only relabel addresses
  already in the 264-address committed pool, and every currently
  labeled `bot_like` address already has a transaction count ≥1,000 by
  construction, so testing a lower threshold against this same pool
  necessarily returns the identical 160 addresses. It can't reveal
  whether addresses with a true lifetime count in [500, 999) exist in
  the wider population, since such addresses would have landed in the
  excluded gap and never been fetched. This sweep is informative for
  raising thresholds above the originals, not lowering them.

---

## 3. Feature Engineering

Four behavioral dimensions were targeted, per the original proposal.
Current implementation status:

| Category | Status | Features |
|---|---|---|
| Timing | Implemented | `interval_cv`, `interval_mean_log`, `interval_max_over_mean` |
| Frequency | Partial - folded into timing | No standalone frequency dimension; `n_tx` deliberately excluded to avoid label circularity |
| Wallet interaction graph | Partial - 1-hop only | `n_unique_counterparties`, `counterparty_entropy_norm`; no multi-hop or centrality analysis |
| Cell usage / tx flow | Partial, leans thin | `capacity_cv`, `mean_outputs_per_tx`, `max_over_mean_outputs`, `fee_cv`, `inbound_only_tx_frac` cover flow shape; cell-*kind* classification (SUDT/NFT/DAO, live/dead lifecycle) not yet implemented |

---

## 4. Model

### 4.1 Selection process

Four candidate model families were cross-validated (5-fold stratified,
scored on F1) on the 251-row trained dataset:

| Model | CV Accuracy | CV Precision | CV Recall | CV F1 | CV ROC-AUC |
|---|---|---|---|---|---|
| Logistic Regression | 0.8562 | 0.9447 | 0.8250 | 0.8794 | 0.9284 |
| **Random Forest (selected)** | **0.9523** | **0.9378** | **0.9917** | **0.9637** | **0.9863** |
| Gradient Boosting | 0.9418 | 0.9489 | 0.9667 | 0.9558 | 0.9833 |
| SVM-RBF | 0.8724 | 0.9387 | 0.8583 | 0.8953 | 0.9546 |

**Random Forest was selected.** Rationale: strong performance on a
small (251-row) tabular dataset relative to the other candidates,
robustness to mixed feature scales without preprocessing, and - most
relevant to this grant's documentation deliverable - directly
interpretable per-feature importance scores.

Note on terminology: an earlier committee message referenced "the
neural network methodology." The deployed and evaluated model is a
Random Forest, not a neural network. This is flagged explicitly here
to avoid ambiguity going forward.

### 4.2 Evaluation metrics

Held-out test split (never touched during model selection), 63 rows
(40 bot-like, 23 human-like - 25% of the 251-row trained set):

| Metric | Value |
|---|---|
| Accuracy | 95.24% |
| Precision (bot class) | 95.12% |
| Recall (bot class) | 97.50% |
| F1 score (bot class) | 96.30% |
| ROC-AUC | 0.9924 |

**Confusion matrix** (held-out test split):

|              | Predicted human | Predicted bot |
|---|---|---|
| **Actual human** | 21 | 2 |
| **Actual bot**    | 1  | 39 |

**Accuracy by transaction-history length** (checks the model isn't
just exploiting degenerate short-history rows):

| Bucket | n | Accuracy |
|---|---|---|
| n_tx < 5 (degenerate) | 11 | 100.0% |
| n_tx 5-20 | 4 | 100.0% |
| n_tx 21+ | 48 | 93.75% |

---

## 5. Feature Importance & Behavioral Dimensions

This is the reusable methodology deliverable the committee identified
as the core value of this grant, independent of the specific model.

| Feature | Importance | Behavioral dimension | Rationale |
|---|---|---|---|
| `interval_max_over_mean` | 0.2873 | Timing | Burstiness: ratio of max to mean inter-transaction interval. Metronomic (bot-like) sending pushes this toward ~1.0; irregular human activity pushes it higher. |
| `n_unique_counterparties` | 0.1601 | Wallet interaction graph | Fan-out/fan-in breadth - how many distinct addresses this wallet has transacted with. |
| `interval_cv` | 0.1537 | Timing | Coefficient of variation of inter-transaction intervals - the core "how close to a metronome is this?" signal. |
| `interval_mean_log` | 0.1464 | Timing | Log-scaled average time between transactions - overall pace, log-transformed so extreme values don't dominate. |
| `counterparty_entropy_norm` | 0.0799 | Wallet interaction graph | How evenly spread the wallet's activity is across its counterparties (0 = concentrated on one/few, e.g. a market-maker or fan-in sink; higher = evenly rotating). |
| `capacity_cv` | 0.0699 | Cell usage / tx flow | Coefficient of variation of output capacities - amount regularity. |
| `mean_outputs_per_tx` | 0.0558 | Cell usage / tx flow | Average number of outputs per transaction - basic fan-out shape. |
| `max_over_mean_outputs` | 0.0370 | Cell usage / tx flow | Ratio of max to mean outputs-per-tx. Distinguishes a payroll/batch-payer (one tx with many outputs) from a bot with a similar mean reached via many small-fanout sends. |
| `inbound_only_tx_frac` | 0.0100 | Cell usage / tx flow | Fraction of transactions where this address only receives (sends nothing externally) - the custodial/cold-storage "quiet bot" signature. |
| `fee_cv` | 0.0000 | Cell usage / tx flow | Fee variation. Contributes nothing in the current sample - fees don't vary enough in this dataset to be discriminating yet. |

`n_tx` (raw transaction count) is deliberately excluded from the model
inputs - see §2.2 - because the labeling heuristic itself is partly
defined by lifetime tx count; including it would let the model
relearn the labeling rule rather than actual behavioral structure.

Also served live via `registry-service`'s `GET /api/v1/model/evaluation`
(`featureImportance` field), documented in its OpenAPI spec at
`/api/v1/docs`.

---

## 6. API Verification

- **Endpoints (current):** both services run locally only -
  `classifier-service` on `localhost:8000`, `registry-service` on
  `localhost:3000`. No public deployment exists yet (see below).
- **Public deployment status: not yet deployed** - no public endpoint,
  domain, or demo video exists at time of this report. This is
  lower priority relative to the committee's Week 4-5 scope cut
  (finetuning/partner integration/dashboard were pushed to a future
  DAO proposal), but is noted here as planned-not-done rather than
  silently skipped.
- **Example request/response** (captured against a live local run):

  ```
  GET http://localhost:8000/classify/ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2hhwwfmxw3e2v6wya8kjw4wc7vlz9jqmgfk8t3y

  {
    "address": "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2hhwwfmxw3e2v6wya8kjw4wc7vlz9jqmgfk8t3y",
    "n_tx_fetched": 30,
    "bot_probability": 0.0615,
    "verdict": "human",
    "warning": null,
    "reason": null
  }
  ```

  Full endpoint documentation (Scalar) is served live at
  `/api/v1/docs` on both services once running.

---

## 7. Compliance Summary

Per the committee's July 2026 ruling:

| Requirement | Status |
|---|---|
| Synthetic/bot-simulator data removed | Complete |
| Real mainnet-only data pipeline | Complete |
| Gold-standard labeled dataset | Not complete - labels are heuristic proxy labels, spot-checked by two reviewers with zero recorded disagreements, but not a formally verified gold-standard dataset (see §2.2) |
| Label sensitivity / robustness analysis | Complete - 9 threshold combinations tested, Random Forest selected in every case, held-out accuracy in the 95.2%-100% range (see §2.4) |
| Documented behavioral dimensions & weights | Complete (see §5) |
| Model methodology clarification (RF, not NN) | Documented (see §4.1) |

---

## 8. Repository Links

Both services are folded into this single monorepo (no separate repos):

- Root repo: https://github.com/FadhilMulinya/ckb-intel
- Registry service (Node): https://github.com/FadhilMulinya/ckb-intel/tree/main/registry-service
- Classifier service (Python): https://github.com/FadhilMulinya/ckb-intel/tree/main/classifier-service

---

## 9. Next Steps

1. **Grow the real-data sample**, especially human-like (currently the
   minority class and the one most affected by short-history rows
   being dropped at feature-extraction time).
2. **Revisit the labeling heuristic** if a less tx-count-entangled
   signal becomes available, so `n_tx` could safely be reintroduced as
   a feature without circularity.
3. **Public API deployment** - VPS + domain, per the original budget
   line, currently unstarted.
4. **Track calibration**, not just accuracy - `predict.py` returns
   `bot_probability`, not just a hard label; tune the uncertain band
   in `train_eval.py` against a validation set if a specific
   precision/recall trade-off is needed downstream.