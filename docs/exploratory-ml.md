# Exploratory ML

## PCA Phase 1

High-Confidence PCA used 513 complete-case wallets × 10 features with explicit transformations and no imputation. PC1 explains 39.24%; PC1–2 58.03%; PC1–3 72.37%; PC1–5 86.74%. Across 500 deterministic 80% resamples, median PC1–PC5 loading cosine similarity was 0.9839. Maximum PC1–PC5 activity association was approximately 0.70, below the predeclared 0.80 HIGH threshold.

## Structure Discovery Phase 2

HDBSCAN audited 192 configurations across eight scaled/PCA representations. Reference parameters were predeclared rather than chosen for cluster count. Pathological and unstable results remain recorded. Each selected solution used 100 deterministic 80%-wallet resamples with ARI, AMI, survival, noise, and co-assignment outputs.

| Representation | Stability |
|---|---|
| High-Confidence scaled | `UNSTABLE` |
| High-Confidence PCA3 | `ROBUST` |
| High-Confidence PCA4 | `ROBUST` |
| High-Confidence PCA6 | `ROBUST` |
| Temporal scaled | `MODERATELY_STABLE` |
| Temporal PCA3 | `UNSTABLE` |
| Cell scaled | `MODERATELY_STABLE` |
| Cell PCA7 | `UNSTABLE` |

The robust High-Confidence views produced 2, 3, and 2 groups within this frozen cohort and observation window. PCA4 was used only as the predeclared ~80%-variance evidence-review view. It supported `LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE`, `SCRIPT_TYPE_DIVERSE_STRUCTURE`, and one `UNINTERPRETED` group; all had low activity dependence. These are cohort-specific descriptive structures, not wallet identities or a taxonomy of CKB wallets generally.

GMM independently selected 10, 1, and 5 components for the High-Confidence, Temporal, and Cell scaled matrices and showed weak agreement with HDBSCAN. It is not confirmation. Nine UMAP views were visualization-only; UMAP coordinates were never clustered. No definitive global clustering solution was established.
