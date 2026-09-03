# Repository audit and cleanup plan

This plan was prepared before final-submission documentation changes. It is non-destructive: no file is deleted, moved, or rewritten merely because it is historical or reports a negative result.

| Classification | Paths | Reviewer action |
|---|---|---|
| `KEEP` | `ckb_data/ckb_data_v2/`, `ckb_data/dataset_completion/`, `ckb_data/feature_engineering_v2/`, `ckb_data/feature_validation/`, `ckb_data/exploratory_ml_pca_v1/`, `ckb_data/exploratory_ml_phase2_v1/` | Canonical frozen evidence and current derived research artifacts. Index them; do not relocate them. |
| `KEEP` | `ckb_data/research_cache.py`, `research_manifest.py`, `dataset_completion.py`, `feature_engineering_v2.py`, `validate_features_v2.py`, `exploratory_pca.py`, `exploratory_structure.py`, `features/`, `features_v2/` | Current reproducibility implementation. |
| `KEEP` | `ckb_data/test_*.py` | Offline research tests. |
| `KEEP_AS_LEGACY` | `classifier-service/`, `registry-service/`, `REPORT.md`, `ckb_data/wallet_classifier_v3/` | Historical proxy-classifier/API baseline. It is not the final methodology and must be described as abandoned. |
| `KEEP_AS_LEGACY` | `fetch_real_data.py`, `fetch_lifetime_stats.py`, `reconcile_bot_like_labels.py`, `sensitivity_analysis.py`, `label_sensitivity_analysis.xlsx` | Historical acquisition, proxy labeling, and sensitivity work retained for auditability. |
| `ARCHIVE_RECOMMENDED` | `ckb_data/ckb_features/`, `cluster_ckb_wallets.py`, `inspect_clusters.py`, `train_wallet_classifier.py`, `infer_wallet_class.py`, `merge_features_for_training.py` | Earlier feature/clustering/classification path. Leave in place for this phase; a later approved change may group it under `legacy/`. |
| `ARCHIVE_RECOMMENDED` | `ckb_data/BEHAVIOUR_FEATURES.md`, `CKB_NATIVE_SCHEMA.md`, `Data Aquisition.md`, `research_validation/` | Useful development-stage documentation superseded by the final docs. Retain as provenance. |
| `REMOVE_RECOMMENDED` | generated `__pycache__/`, `.pyc`, and `graphify-out/` audit scratch files | Build/audit residue only. No removal was performed because this phase forbids automatic deletion. |
| `UPDATE_REQUIRED` | `README.md` | It presents the proxy human/bot service as the current project. Replace with the final CKB-native research entry point. |
| `UPDATE_REQUIRED` | `classifier-service/README.md`, `registry-service/README.md` | Add prominent legacy notices in a future separately approved cleanup; do not change service behavior now. |
| `UPDATE_REQUIRED` | root navigation and reproducibility commands | Add final docs, artifact indexes, offline verifier, and final research report. |

## Documentation inconsistencies

- The previous root README described bot/human verdicts, trained classification, and heuristic labels as the current product. That framing is incompatible with the final research result.
- `REPORT.md` correctly contains later caveats, but remains a historical proxy-model report and prominently displays supervised metrics against proxy labels.
- Historical scripts and service names still contain `human`, `bot`, `classifier`, `miner`, `exchange`, and `is_special`. Their presence is not evidence that those concepts entered Dataset V1, Feature V2, PCA, or Phase 2.
- Current research directories preserve failed observations, sparse support, rejected PCA experiments, unstable HDBSCAN runs, GMM disagreement, and an uninterpreted group. These are active evidence, not cleanup targets.

## Minimal-change decision

The final package adds navigation and documentation around the existing layout instead of moving large content-addressed artifacts. Physical archival is recommended only after human review because moves would create unnecessary hash/path churn and could obscure provenance.
