# Historical-claim audit

Repository-wide searches covered `95.24%`, `human_like`, `bot_like`, `human`, `bot`, `is_special`, transaction-count thresholds, `ground truth`, verified labels, classifier accuracy, `miner`, and `exchange`.

<<<<<<< HEAD
- **Legitimate historical context:** `REPORT.md` explains the heuristic labels and correctly qualifies 95.24% as proxy-label accuracy.
- **Legacy artifacts:** `classifier-service/`, `registry-service/`, `data/real/`, `ckb_data/ckb_features/`, and `ckb_data/wallet_classifier_v3/` contain the abandoned classification workflow.
- **Fixtures:** root/service tests retain identity-like strings to verify historical behavior.
- **Current provenance:** `legacy_proxy_label` in manifests and metadata preserves source lineage; it is excluded from features and discovery.
- **Current-methodology violations:** none found in Dataset V1, Feature V2, validation, PCA, or Phase 2 reports. Their code and tests prohibit label leakage.
- **Documentation correction:** the root README was replaced. Physical archival and legacy service banners remain recommended for a later approved cleanup.

No historical evidence or fixture was deleted.
=======
- **Legitimate historical context:** current research reports explain the heuristic labels and qualify 95.24% as proxy-label accuracy.
- **Legacy implementation:** V1 executable code, model artifacts, data exports, tests, and the registry service were removed. Git history is the archive.
- **Current provenance:** `legacy_proxy_label` in manifests and metadata preserves source lineage; it is excluded from features and discovery.
- **Current-methodology violations:** none found in Dataset V1, Feature V2, validation, PCA, or Phase 2 reports. Their code and tests prohibit label leakage.
- **Documentation correction:** active README and service docs identify V2 as authoritative.

Frozen V2 provenance manifests retain legacy source labels as metadata only; no
active service path consumes them for classification.
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6
