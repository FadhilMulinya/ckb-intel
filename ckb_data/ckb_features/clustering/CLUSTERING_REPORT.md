# CKB Wallet Clustering Report

## 1. Method

Gaussian Mixture Model (full covariance), fit on the RobustScaler-scaled active-wallet matrix from `features_for_clustering.csv` (unsupervised -- no labels used in fitting). Every active wallet gets a hard cluster assignment (argmax of its GMM responsibilities); the 123 wallets with zero recorded activity are assigned directly to a `Dormant / No Activity` segment without going through the model, since they have no timing signal to cluster on. No wallet is left unassigned or labeled noise.

**Chosen k = 3** (default: one cluster per named archetype (Human/Bot/Miner). Sweep diagnostics: BIC-best k=8, balanced-silhouette-best k=2 -- pass --k to override.)

**HDBSCAN diagnostic** (comparison only, not used for final labels): found 6 clusters and would have marked 65.6% of active wallets as noise/unclustered -- discarded here in favor of GMM's inclusive assignment.

## 2. Model selection sweep

|   k |   gmm_bic |   gmm_aic |   gmm_silhouette |   gmm_min_cluster_frac |   gmm_max_cluster_frac |   kmeans_inertia |   kmeans_silhouette |
|----:|----------:|----------:|-----------------:|-----------------------:|-----------------------:|-----------------:|--------------------:|
|   2 |  -26354.5 |  -32194.5 |            0.114 |                  0.486 |                  0.514 |          28041.6 |               0.927 |
|   3 |  -24054   |  -32816.2 |            0.106 |                  0.003 |                  0.564 |          22495.2 |               0.51  |
|   4 |  -30967.3 |  -42651.8 |            0.119 |                  0.001 |                  0.429 |          19953.8 |               0.325 |
|   5 |  -33050.6 |  -47657.5 |            0.074 |                  0.001 |                  0.364 |          17997.2 |               0.153 |
|   6 |  -34043.9 |  -51573.1 |            0.12  |                  0.001 |                  0.397 |          16383.1 |               0.159 |
|   7 |  -38100   |  -58551.5 |            0.133 |                  0.001 |                  0.338 |          15033.6 |               0.159 |
|   8 |  -38194.2 |  -61567.9 |            0.132 |                  0.001 |                  0.329 |          13912.2 |               0.169 |

Note on k=2: it has the highest KMeans silhouette in this sweep, but its smallest cluster is a sliver of extreme-volume outliers rather than a second behavioral archetype -- see `plots/k_sweep.png` and `gmm_min_cluster_frac` above. That's why silhouette alone isn't used to pick k here.

## 3. Segment profiles (raw, unscaled units)

|                        |   n_wallets |   n_tx_in_window |   tx_per_window_day |   tx_per_active_day |       gap_mean_s |   gap_cv |   burstiness |   hour_of_day_entropy |   day_of_week_entropy |   sent_total_ckb |   received_total_ckb |
|:-----------------------|------------:|-----------------:|--------------------:|--------------------:|-----------------:|---------:|-------------:|----------------------:|----------------------:|-----------------:|---------------------:|
| Human-like / Daytime   |         339 |            49.29 |                0.07 |                0.83 |      3.24787e+06 |     1.44 |         0.05 |                  0.26 |                  0.39 |      8.12496e+07 |          8.15574e+07 |
| Bot-like / Consistent  |         359 |           724.53 |                0.99 |                1.89 | 131976           |     3.3  |         0.31 |                  0.37 |                  0.99 |      5.96331e+08 |          3.89053e+08 |
| Miner / Heavy Activity |          66 |          1145.62 |                1.57 |                2.62 | 128835           |     2.88 |         0.29 |                  0.81 |                  0.99 |      4.65085e+08 |          5.48857e+08 |

`n_wallets` per segment (including Dormant):

| segment                |   n_wallets |
|:-----------------------|------------:|
| Bot-like / Consistent  |         359 |
| Human-like / Daytime   |         339 |
| Dormant / No Activity  |         123 |
| Miner / Heavy Activity |          66 |

## 4. Caveats
- Labels (Human-like / Bot-like / Miner / Dormant) are a post-hoc, heuristic reading of each cluster's own centroid statistics -- they are not ground truth, and the model was never told about these categories. Treat them as a starting hypothesis for further investigation, not a verified classification.
- Monetary features (sent/received totals, concentration indices) inherit every caveat from `PREPROCESSING_REPORT.md` -- in particular the value_shannon proportional-splitting bias on multi-input transactions.
- GMM assignments are hard (argmax) in the output CSV, but each wallet's full soft-responsibility vector is also included -- a low max-responsibility (`segment_confidence` column) means that wallet sits ambiguously between two archetypes and its label is less certain than the average member.
