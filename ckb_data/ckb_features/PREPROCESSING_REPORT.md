# CKB Wallet Preprocessing Report

## 0. Input counts

- Active wallets (clustering population): **764**
- Unused wallets (kept, labeled, excluded from clustering matrix): **123**
- Malformed wallets: dropped upstream by classify_wallet_status.py, not read by this script at all.

## 1. Data-quality audit (read this before trusting monetary features)

- 1 of 764 active wallets (0%) fell below the detail-coverage threshold of 30% (n_tx_detail_fetched / n_tx_in_window). For these wallets, edge-derived monetary/graph features (sent/received totals, counterparty counts, concentration indices) were set to NaN and then median-imputed -- **do not read cluster assignments for these wallets as monetary behavior conclusions**, only as timing/rhythm conclusions, which remain reliable regardless of coverage. DAO features are exact regardless of coverage (separate, uncapped collection) and were not affected by this.
- Columns that required imputation for at least one wallet: gap_mean_s, gap_median_s, gap_cv, burstiness, sent_tx_count, received_tx_count, sent_edge_count, received_edge_count, sent_total_ckb, received_total_ckb, net_flow_ckb, sent_mean_ckb, sent_median_ckb, sent_cv, received_mean_ckb, received_median_ckb, received_cv, unique_counterparties_out, unique_counterparties_in, reciprocity_ratio, out_value_concentration_hhi, in_value_concentration_hhi, max_single_tx_ckb.
  - `gap_mean_s`: 169 wallet(s) missing before imputation
  - `gap_median_s`: 169 wallet(s) missing before imputation
  - `gap_cv`: 169 wallet(s) missing before imputation
  - `burstiness`: 169 wallet(s) missing before imputation
  - `sent_tx_count`: 1 wallet(s) missing before imputation
  - `received_tx_count`: 1 wallet(s) missing before imputation
  - `sent_edge_count`: 1 wallet(s) missing before imputation
  - `received_edge_count`: 1 wallet(s) missing before imputation
  - `sent_total_ckb`: 1 wallet(s) missing before imputation
  - `received_total_ckb`: 1 wallet(s) missing before imputation
  - `net_flow_ckb`: 1 wallet(s) missing before imputation
  - `sent_mean_ckb`: 103 wallet(s) missing before imputation
  - `sent_median_ckb`: 103 wallet(s) missing before imputation
  - `sent_cv`: 103 wallet(s) missing before imputation
  - `received_mean_ckb`: 14 wallet(s) missing before imputation
  - `received_median_ckb`: 14 wallet(s) missing before imputation
  - `received_cv`: 14 wallet(s) missing before imputation
  - `unique_counterparties_out`: 1 wallet(s) missing before imputation
  - `unique_counterparties_in`: 1 wallet(s) missing before imputation
  - `reciprocity_ratio`: 3 wallet(s) missing before imputation
  - `out_value_concentration_hhi`: 103 wallet(s) missing before imputation
  - `in_value_concentration_hhi`: 14 wallet(s) missing before imputation
  - `max_single_tx_ckb`: 3 wallet(s) missing before imputation

## 2. Feature engineering summary

**Timing features** (from `address_tx_seen`, exact unless `listing_truncated`):
- `n_tx_in_window`, `tx_per_window_day`, `active_span_days`, `tx_per_active_day`
- `gap_mean_s`, `gap_median_s`, `gap_cv` (inter-transaction gap statistics)
- `burstiness` (Goh–Barabási index: -1 periodic/bot-like, 0 memoryless, +1 human-bursty)
- `hour_of_day_entropy`, `day_of_week_entropy` (0 = concentrated/scripted, 1 = uniform)

**Monetary / graph features** (from `edges`, sample-limited -- see audit above):
- `sent_tx_count`/`received_tx_count` (distinct transactions -- commensurate with `n_tx_in_window`), `sent_edge_count`/`received_edge_count` (raw edge rows -- can exceed the transaction count for wallets with many distinct counterparties per transaction; see the note below), `sent_total_ckb`, `received_total_ckb`, `net_flow_ckb`
- `sent_mean_ckb`/`median`/`cv`, `received_mean_ckb`/`median`/`cv`
- `unique_counterparties_out`/`in`, `reciprocity_ratio`
- `out_value_concentration_hhi`/`in_value_concentration_hhi` (Herfindahl index -- 1 wallet dominating flow vs. many small counterparties)
- `max_single_tx_ckb`

**DAO features** (from `dao_events`, exact):
- `n_dao_events`, `dao_total_ckb`, `dao_event_rate`, `has_dao_activity`

**Known heuristic bias**: `edges.value_shannon` splits a transaction's output value proportionally across every distinct input lock_hash, without knowing each input's real contribution. Multi-input transactions therefore inflate summed sent/received volume, and the inflation scales with each wallet's average input-fan-in, which isn't itself measured here. Value features should be read as **relative, within-dataset signals**, not audited CKB amounts.

**Edge count vs. transaction count**: `resolve_transaction_to_edges` produces one edge per (transaction, distinct counterparty) pair, not one per transaction. A single transaction paying out to many distinct addresses -- or receiving from many distinct senders in one consolidation transaction -- can generate far more edges than the wallet had actual transactions (this is exactly what a wallet with 38,029 edges against 5,553 real transactions looked like: a consolidation-style address). `sent_tx_count`/`received_tx_count` are the distinct-transaction counts and are bounded by `n_tx_in_window` by construction; `sent_edge_count`/`received_edge_count` are the raw edge counts and are NOT bounded by it -- use the `_tx_count` columns for anything meant to represent "how many transactions," and the `_edge_count` columns only for fan-out/graph analysis where the distinction matters.

## 3. Transforms applied

- Log1p on heavy-tailed counts/amounts: n_tx_in_window, tx_per_window_day, tx_per_active_day, gap_mean_s, gap_median_s, sent_tx_count, received_tx_count, sent_edge_count, received_edge_count, sent_total_ckb, received_total_ckb, sent_mean_ckb, sent_median_ckb, received_mean_ckb, received_median_ckb, unique_counterparties_out, unique_counterparties_in, max_single_tx_ckb, n_dao_events, dao_total_ckb
- Signed-log1p on `net_flow_ckb` (can be negative)
- RobustScaler (median/IQR) on the full active feature matrix -- chosen over StandardScaler because whale wallets remain outliers even after log-transform and would otherwise dominate a mean/std scaling.

## 4. Suggested k for KMeans (from elbow + silhouette sweep)

- Silhouette-best k = **2** (silhouette = 0.927). Cross-check against the elbow in `plots/07_kmeans_k_selection.png` -- silhouette alone can favor a trivially small k.
- KMeans assumes spherical, similarly-sized clusters. Given how skewed wallet activity typically is (a few whales/bots, many quiet-but-active wallets), also try **GMM** (soft cluster boundaries) or **HDBSCAN** (no k required, and explicitly labels wallets that don't fit any cluster as noise instead of forcing them into the nearest one -- often the more honest choice here).

## 5. Output files

- `features_full.csv` -- every wallet (active + unused + unknown), all raw features + status/QC columns, nothing scaled or imputed. Use this for reporting and for keeping the unused group as a labeled third class.
- `features_for_clustering.csv` -- active wallets only, log-transformed, low-coverage value features nulled + median-imputed, RobustScaler-scaled. Feed this directly into KMeans/GMM/HDBSCAN.
- `feature_manifest.json` -- column lists, transform choices, imputation audit, scaler parameters (so the exact same transform can be re-applied to newly collected wallets later without refitting from scratch).
- `plots/` -- 01 status breakdown, 02 detail-coverage distribution, 03 coverage-vs-activity (shows the sampling bias directly), 04 raw-vs-log distributions, 05 correlation heatmap, 06 PCA projection, 07 KMeans k-selection sweep.
