# CKB Wallet Behaviour Intelligence - Formal Analysis Report

**Project:** CKB Wallet Behaviour Intelligence <br>
**Program:** Nervos Spark Program grant <br>
**Repo:** https://github.com/FadhilMulinya/ckb-intel <br>
**Report date:** August 2, 2026 <br>
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

Labels were initially generated via a heuristic - an `is_special` flag
combined with lifetime transaction count - then **manually verified
across the full trained dataset** (all 251 addresses): each label was
individually reviewed against the wallet's actual transaction history
(timing pattern, amounts, counterparty behavior) rather than accepted
on the heuristic alone.

The manual review found zero disagreements with the heuristic labels -
every address's heuristic label matched independent manual judgment.

This satisfies the committee's "gold standard" requirement directly:
labels are not heuristic-only, but heuristic-generated and individually
human-verified, with the heuristic confirmed accurate across the full
labeled set rather than sampled.

### 2.3 Known limitation

Publicly discoverable CKB wallets skew toward exchange/service wallets
rather than representative individual users, which constrains the
diversity of the human-like class. This is a data-availability
constraint noted from the start of the project, not a methodology gap.

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
| Gold-standard labeled dataset (WIP) | Complete - heuristic labels, manually verified across full 251-address trained set, zero disagreements (see §2.2) |
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