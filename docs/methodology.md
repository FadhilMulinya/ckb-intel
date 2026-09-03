# Methodology

## Historical baseline

The early project assigned `human_like` to low lifetime-transaction-count addresses and `bot_like` to high-count addresses, then trained a classifier on those proxy labels. The reported 95.24% held-out accuracy was accuracy against the heuristic, not verified ownership ground truth. Transaction count is not a defensible human/bot boundary, and Explorer `is_special` is not a bot signal. This path is preserved as the **LEGACY / ABANDONED BASELINE** in `REPORT.md` and the service directories.

## Final methodology

The final label-free pipeline is: frozen CKB mainnet population → fixed 30-day observation → normalized transactions and Cells → applicable previous-output resolution → CKB-native features → support-aware validation → PCA diagnostics → cautious unsupervised sensitivity analysis → structured evidence review.

CKB transactions are treated as Cell transformations, not pairwise account transfers. Inputs consume previous outpoints; outputs create new Cells with capacity, lock script, optional type script, and data. A wallet observation is defined by target lock control. The resulting structure is naturally hypergraph-like, so the project does not infer unsupported sender/recipient pairs.

Feature results carry `SUPPORTED`, `PARTIAL`, `INSUFFICIENT_EVIDENCE`, or `UNRESOLVED`. Cellbase inputs have no previous output and are `NOT_APPLICABLE`. Missing predictors remain missing; they are never converted to zero or imputed in validation/PCA.

Transparent behaviour rules are evidence summaries, not labels. Raw activity diagnostics and rule outputs were excluded from PCA and clustering and used only post hoc. The final conclusion is descriptive: reproducible structure exists in portions of the feature space, but no definitive taxonomy or identity classifier was established.
