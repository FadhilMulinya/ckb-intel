# Bot vs. Human Detection - Model Development

Classifies CKB addresses as bot/exchange-operated or human-operated from their
transaction behavior. The model is a **supervised binary classifier
trained exclusively on real mainnet data** (`bot_like` / `human_like`
addresses collected by `fetch_real_data.py`). No synthetic data is used
anywhere in this pipeline .

---

## 1. Repo layout

```
fetch_real_data.py                         <- pulls real addresses from CKB Explorer mainnet API
data/real/
├── bot_like/    manifest.json, addr_*.json
└── human_like/  manifest.json, addr_*.json

classifier-service/
├── requirements.txt
├── extract_features.py                    <- shared feature-vector definition
├── extract_features_real.py               <- real addresses -> real_features.json
├── train_eval.py                          <- trains, evaluates, and serializes the model
├── predict.py                             <- classify a live address (CLI); writes back to registry-service if REGISTRY_SERVICE_URL is set
├── ckb_intel_client.py                    <- thin write-back client (see §4)
├── app.py                                 <- FastAPI wrapper around predict.py
├── Dockerfile                             <- container build for deployment
├── real_features.json      (generated, REQUIRED for training)
├── eval_results.json       (generated) -- also served live over HTTP by registry-service's GET /api/v1/model/evaluation
├── model.joblib             (generated)
└── pca_plot.png             (generated)
```

---

## 2. Environment setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r classifier-service/requirements.txt
```

---

## 3. Execution steps

Run everything from the repo root:

```bash
# Step 1 - fetch real mainnet wallet data
python3 fetch_real_data.py
# -> writes data/real/{bot_like,human_like}/

# Step 2 - extract behavioral features from that real data
python3 classifier-service/extract_features_real.py
# -> writes classifier-service/real_features.json (REQUIRED for training)

# Step 3 - train, evaluate, visualize
python3 classifier-service/train_eval.py
# -> prints model comparison + held-out metrics + history-length breakdown
# -> writes eval_results.json, model.joblib, pca_plot.png

# Step 4 - classify a live address
python3 classifier-service/predict.py <ckb-address>
```

`train_eval.py` **requires** `real_features.json` to exist - it hard-fails
with a clear message telling you to run `extract_features_real.py` first,
rather than silently falling back to any other data source.

Optional flag:

```bash
python3 classifier-service/train_eval.py --min-tx 5   # drop addresses with <5 tx
```

---

## 4. Running the API

```bash
cd classifier-service
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Full interactive reference: `http://localhost:8000/api/v1/docs`. Optionally set `REGISTRY_SERVICE_URL` to have `predict.py`/`app.py` write each verdict back to the separate `registry-service` wallet registry after scoring - see the top-level [`README.md`](../README.md) for how the two services fit together; this model doesn't need it to function.

For an automated end-to-end suite covering this service, `registry-service`, and the write-back between them, see [`../tests/e2e_test.py`](../tests/e2e_test.py) and run it with `../scripts/e2e.sh` from the repo root.

---

## 5. Methodology

### 5.1 Why supervised, real-data-only

An earlier version of this project trained a one-class model on synthetic
simulator bots, because no human-labeled data existed at the time. That
approach was abandoned: evaluated against real mainnet data it topped out
at 20-62% accuracy, because a synthetic training manifold is far tighter
and cleaner than real bot behavior - the model learned "artificially
perfect simulator archetype," not "bot." `fetch_real_data.py` now collects
real mainnet addresses bucketed into **both** `bot_like` and `human_like`
(heuristically, via an `is_special` flag / lifetime transaction count -
see label caveats in §6), so this is ordinary supervised binary
classification trained and evaluated entirely on real data.

### 5.2 Data

- `real_features.json`: real mainnet addresses only, currently 160
  `bot_like` rows and 104 `human_like` rows (see `data/real/`).
- 10 behavioral features (ratios/shape statistics, not raw magnitudes -
  see `extract_features.py`): `interval_cv`, `interval_mean_log`,
  `capacity_cv`, `fee_cv`, `n_unique_counterparties`,
  `counterparty_entropy_norm`, `mean_outputs_per_tx`,
  `interval_max_over_mean`, `inbound_only_tx_frac`, `max_over_mean_outputs`.
- `n_tx` (raw transaction count) is **deliberately excluded** from the
  model inputs even though it's highly predictive, because the labeling
  heuristic itself is partly defined by lifetime tx count. Including it
  would let the model just relearn the labeling rule, not behavioral
  structure.
- Many `human_like` rows have only a handful of transactions on record,
  which makes interval-based features degenerate by construction (not
  enough data points to compute a meaningful variance). This isn't hidden
  - `train_eval.py` prints an explicit accuracy breakdown by history
  length so you can see whether performance depends on those rows.

### 5.3 Model selection

Four candidates are compared with 5-fold stratified cross-validation on
the training split, scored on F1 (class-imbalance-aware): Logistic
Regression, Random Forest, Gradient Boosting, RBF SVM. All use
`class_weight="balanced"`. The best-scoring model is refit on the full
training split, evaluated once on a held-out test split (never touched
during model selection), then refit again on **all** available
real-labeled data for the artifact that ships in `model.joblib`.

### 5.4 Results

(most recent run - regenerate with `train_eval.py` to reproduce; see
`eval_results.json` for the full machine-readable output, or
`GET /api/v1/model/evaluation` on `registry-service` for the same data served live
over HTTP - see [`../registry-service/README.md`](../registry-service/README.md))

| model | CV accuracy | CV F1 | CV ROC-AUC |
|---|---|---|---|
| Logistic Regression | 0.856 | 0.879 | 0.928 |
| **Random Forest (selected)** | **0.952** | **0.964** | **0.986** |
| Gradient Boosting | 0.942 | 0.956 | 0.983 |
| RBF SVM | 0.872 | 0.895 | 0.955 |

Held-out test set (Random Forest, n=40 bot / n=23 human):
**95.2% accuracy, 95.1% precision, 97.5% recall, 96.3% F1, 0.992 ROC-AUC**.
Confusion matrix: 39/40 bots correctly identified, 21/23 humans correctly
identified.

Accuracy by history length (checks the model isn't just exploiting
degenerate short-history rows):

| bucket | n | accuracy |
|---|---|---|
| n_tx < 5 (degenerate) | 11 | 100.0% |
| n_tx 5-20 | 4 | 100.0% |
| n_tx 21+ | 48 | 93.8% |

Feature importance (Random Forest): `interval_max_over_mean` (0.29) and
`n_unique_counterparties` (0.16) dominate, followed by `interval_cv`
(0.15) and `interval_mean_log` (0.15). `fee_cv` contributes nothing in the
current sample - fees don't vary enough to be discriminating yet.

---

## 6. Limitations (read before treating any number as a guarantee)

- **Labels are heuristic, not verified ground truth.** `bot_like` /
  `human_like` come from an `is_special` flag / lifetime-tx-count
  threshold, not confirmed identity. Every metric above is bounded by how
  good that heuristic is.
- **Small sample.** ~264 real-labeled rows total, well below the
  1,000-wallet target in the original proposal.
  Cross-validation is used precisely because a single train/test split on
  this few rows would be noisy; treat these numbers as a strong
  directional signal, not a certified error rate.
- **Class imbalance** (~1.8:1 bot:human currently), handled via
  `class_weight="balanced"` rather than discarding data.
- **Short-history degeneracy.** A meaningful share of `human_like` rows
  have very few transactions, making interval-based features close to
  meaningless by construction for those rows. `--min-tx` lets you exclude
  them if you want a stricter (smaller) evaluation.
- **`n_tx` excluded from features on purpose** (see §5.2) - this trades
  away a strong raw predictor to avoid circularity with the labeling rule,
  which is the right call, but means the model may be weaker in cases
  where tx-count really is the dominant honest signal.
- **Binary, not 3-class.** The model currently distinguishes only
  `bot_like` vs `human_like`. It does not yet produce a separate
  exchange-wallet class.

## 7. Recommended next steps

1. **Grow the real-data sample**, especially `human_like` (currently the
   minority class and the one most affected by short-history degeneracy).
2. **Revisit the labeling heuristic** if a less tx-count-entangled signal
   becomes available (e.g. manual review of a subset), so `n_tx` could
   safely be reintroduced as a feature without circularity.
3. **Re-run the full pipeline** after each change - both scripts are
   deterministic (fixed seed 42) and cheap to re-run end to end.
4. **Track calibration**, not just accuracy - `predict.py` returns
   `bot_probability`, not just a hard label; if the real-world use case
   needs a specific precision/recall trade-off, tune the uncertain band
   in `train_eval.py` against a validation set.
