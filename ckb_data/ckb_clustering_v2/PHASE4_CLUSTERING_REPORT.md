# Phase 4 -- Neutral Re-clustering & Archetype Cross-Validation

## Method

Gaussian Mixture Model (full covariance) fit on a RobustScaler-scaled, median-imputed matrix combining features_full.csv (temporal) and features_cell_layer.csv (Phase 2 Cell layer) -- unsupervised, no labels used in fitting. Wallets are split into populations using `wallet_status` (not merely n_tx_in_window==0, which cannot distinguish a genuinely-collected zero-transaction wallet from one that was simply never collected): **685** ordinary active wallets were clustered; **79** extreme wallets (same detection logic as flag_outlier_wallets.py, run BEFORE the fit -- see below) are 'Outlier_Excluded'; **123** are 'Inactive' (wallet_status=='unused', a real collected fact); **0** are 'Insufficient_Data' (wallet_status outside {active, unused} -- e.g. not_collected or malformed).

**Outlier exclusion matters here**: a first pass at clustering the full active population (before this exclusion) produced silhouette >0.93 at every k tested, with the smallest cluster always under 1% of wallets -- the classic signature of a handful of extreme wallets (unbounded counterparty counts, likely exchange/pool-scale addresses) dominating the distance metric rather than genuine behavioral structure. Excluding them before the fit is what makes the sweep below meaningful. The excluded wallets themselves are good Phase 5 ground-truth candidates -- see outlier_wallets_v2.txt.

**Chosen k = 2** (balanced-silhouette-best k=2 (BIC-best was k=4); pass --k to override)

**HDBSCAN diagnostic** (comparison only): found 4 clusters, 23.9% of active wallets marked noise.

## Model selection sweep

|   k |   gmm_bic |   gmm_aic |   gmm_silhouette |   gmm_min_cluster_frac |   gmm_max_cluster_frac |   kmeans_inertia |   kmeans_silhouette |
|----:|----------:|----------:|-----------------:|-----------------------:|-----------------------:|-----------------:|--------------------:|
|   2 |  -41495.4 |  -46273.9 |            0.486 |                  0.317 |                  0.683 |          43745.6 |               0.763 |
|   3 |  -44649.7 |  -51819.8 |            0.416 |                  0.139 |                  0.679 |          32046.9 |               0.655 |
|   4 |  -55699.7 |  -65261.3 |            0.066 |                  0.124 |                  0.476 |          24909.8 |               0.524 |
|   5 |  -49765.5 |  -61718.6 |            0.059 |                  0.026 |                  0.482 |          19310.4 |               0.526 |
|   6 |  -47433.7 |  -61778.4 |            0.055 |                  0.013 |                  0.466 |          16721.6 |               0.521 |
|   7 |  -46673.6 |  -63409.9 |            0.057 |                  0.013 |                  0.476 |          15056.2 |               0.247 |
|   8 |  -46932.3 |  -66060   |            0.03  |                  0.026 |                  0.337 |          13770.1 |               0.245 |

## Cluster names (auto-generated, neutral -- NOT behavioral labels)

- cluster 0: `high_in_counterparties_cell+high_in_counterparties`
- cluster 1: `low_out_hhi_cell+low_out_hhi`

These names describe each cluster's own most-distinguishing scaled features. They are deliberately NOT Human/Bot/Miner -- that mapping requires Phase 5 ground truth first.

## Cross-validation against Phase 3 archetypes

Normalized mutual information between cluster assignment and Phase 3's `top_archetype`: **0.090** (0 = no relationship, 1 = perfect agreement). This measures whether two INDEPENDENT methods (rule-based scoring vs. unsupervised clustering) found similar structure -- it is not an accuracy score against ground truth, which doesn't exist yet (Phase 5).

Row-normalized (%) -- for each cluster, the archetype breakdown of its members:

| cluster_label                                      |   BATCH_DISTRIBUTION |   CELL_CONSOLIDATION |   CELL_FRAGMENTATION |   FAN_IN_COLLECTION |   INSUFFICIENT_EVIDENCE |   IRREGULAR_ACTIVITY |   PERIODIC_EXECUTION |   ROUND_TRIP |
|:---------------------------------------------------|---------------------:|---------------------:|---------------------:|--------------------:|------------------------:|---------------------:|---------------------:|-------------:|
| high_in_counterparties_cell+high_in_counterparties |                  0   |                  4.1 |                 16.2 |                 0.2 |                    10.5 |                 56.8 |                  8.3 |          3.8 |
| low_out_hhi_cell+low_out_hhi                       |                  0.5 |                  0.9 |                  9.7 |                 0   |                     2.3 |                 51.6 |                  2.8 |         32.3 |

A cluster dominated by one archetype is a good sign the two methods agree. A cluster split across several archetypes, or an archetype spread across several clusters, isn't automatically a bug in either method -- it's exactly the kind of case Phase 5's ground-truth sampling should prioritize checking by hand.

## Caveats

- This is a sanity check, not a classification. No wallet in this output should be reported as Human/Bot/Miner/Inactive except the Inactive rule above, which predates clustering and isn't derived from it.
- Monetary features inherit the value-splitting caveats already documented for the existing pipeline.
- GMM cluster assignment is hard (argmax) in the output CSV; each wallet's soft-responsibility max is included as cluster_confidence -- a low value means the wallet sits ambiguously between clusters.
