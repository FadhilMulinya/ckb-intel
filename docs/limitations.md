# Limitations

- One fixed 30-day period cannot establish temporal generality.
- 227 observations failed and six are partial; all remain in the population.
- Feature support is sparse and differs by family and activity.
- No verified identity ground truth exists; no final human/bot classifier is claimed.
- xUDT recognition exists, but cached payload evidence is insufficient for supported typed-asset analysis.
- Cluster count and membership depend on representation; full scaled High-Confidence was unstable.
- HDBSCAN and GMM disagree, and one PCA4 group remains uninterpreted.
- Some PCA components retain moderate activity association, though none crossed the HIGH threshold.
- No economic sender/recipient attribution, pairwise value-flow claim, or global wallet taxonomy is made.
- Evidence review is bounded and structured, not external identity adjudication.
- The cohort comes from historical project discovery sources and is not a random or statistically representative sample of all CKB wallets; external generalization requires new sampling validation.
- The stored `mainnet` identity is configuration and source metadata; the repository does not perform a cryptographic genesis/network identity check.
- Normalized input rows retain previous transaction hashes, but their dedicated `previous_output_index` column is null in the frozen rows; the V2 loader recovers `cell_index` from cached raw JSON where available.
- The V1 classifier and registry service were removed. `classifier-service/`
  now exposes only the V2 descriptive behaviour pipeline; PCA and clustering
  remain research artifacts rather than identity predictions.
- CKB relative/absolute `since` semantics are not modeled. Protocol- or timelock-constrained Cells can therefore appear structurally long-lived, and the study does not distinguish enforced lifetime from discretionary wallet behaviour in those cases.
