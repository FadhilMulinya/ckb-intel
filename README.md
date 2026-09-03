# CKB Wallet Behaviour Intelligence

CKB Wallet Behaviour Intelligence is an exploratory CKB mainnet research project that reconstructs transactions and Cells and measures temporal, periodic, topology, lifecycle, lineage, capacity, script, and transaction-template structure. It is **not a verified human/bot classifier**: outputs describe observable on-chain behaviour, while ownership and identity attribution remain outside the demonstrated evidence.

## Why the methodology changed

The historical project used lifetime transaction-count thresholds to create `human_like` and `bot_like` proxy labels. Its reported 95.24% accuracy measured agreement with those heuristics, not verified identities. That baseline is retained for transparency but abandoned as the final methodology. The current work uses label-free, CKB-native evidence and reports negative and incomplete results explicitly.

## Frozen dataset

| Item | Value |
|---|---|
| Dataset | `ckb-behaviour-dataset-v1` |
| Population | 1,172 frozen wallets; 939 complete, 6 partial, 224 retry-exhausted, 3 invalid |
| Observation | 2026-08-01 00:00 UTC through 2026-08-31 00:00 UTC |
| Transactions | 51,816 |
| Applicable inputs | 56,407 / 56,407 resolved (100%); Cellbase inputs are `NOT_APPLICABLE` |
| Manifest SHA-256 | `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe` |
| Database SHA-256 | `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322` |

This is a reproducible observational cohort assembled from overlapping historical local sources, not a random or statistically representative sample of all CKB wallets. Of 1,172 wallets, 425 retain provenance-only legacy proxy metadata (222 `bot_like`, 203 `human_like`); 747 have no proxy label. Those fields were excluded from Feature V2 and all exploratory ML.

## Architecture

```text
CKB Mainnet Evidence
        ↓
Normalized Transactions / Cells
        ↓
Canonical Lock + Type Scripts
        ↓
Fixed Wallet Observations
        ↓
Feature Engineering V2
        ↓
Feature Validation
        ↓
PCA Diagnostics
        ↓
Exploratory Structure Discovery
        ↓
Evidence Review
```

Feature V2 covers temporal structure, periodicity, Cell lifecycle, topology, transaction templates, scripts, capacity, lineage, and typed-asset groundwork. Missing values mean unsupported or unobserved evidence—not zero behaviour.

## Validation and exploratory results

All 121 numeric predictors were audited: 17 `USABLE`, 99 `SPARSE`, 5 `CONSTANT`, and zero impossible values. The candidate sets contain 104 broad, 95 core, 59 low-redundancy, and 10 High-Confidence predictors. The High-Confidence reference has 513 complete-case wallets.

For High-Confidence PCA, PC1 explains 39.24%, PC1–2 58.03%, PC1–3 72.37%, and PC1–5 86.74%. Median PC1–PC5 bootstrap loading cosine similarity is 0.9839. Maximum activity association is approximately 0.70; none crosses the predeclared 0.80 HIGH threshold.

HDBSCAN in full scaled High-Confidence space was unstable; PCA3, PCA4, and PCA6 were robust, but produced 2, 3, and 2 groups. PCA4 evidence review cautiously supported `LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE` and `SCRIPT_TYPE_DIVERSE_STRUCTURE`; a third group remains `UNINTERPRETED`. All three had low post-hoc activity dependence. GMM did not strongly confirm HDBSCAN. These are exploratory structural descriptions, not a global taxonomy.

## Documentation

- [Methodology](docs/methodology.md)
- [Dataset](docs/dataset.md)
- [Feature Engineering V2](docs/feature-engineering-v2.md)
- [Validation](docs/validation.md)
- [Exploratory ML](docs/exploratory-ml.md)
- [Limitations](docs/limitations.md)
- [Offline reproduction](docs/reproduction.md)
- [Repository audit](docs/repository-audit.md)
- [Artifact index](artifacts/README.md)
- [Final research report](reports/final-research-report.md)

## Verify offline

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-research.txt
./scripts/verify_final_research.sh .venv/bin/python
```

`requirements-research.lock.txt` records the exact artifact-generation versions; the flexible file is the supported installer. The frozen database is distributed separately in the [Dataset V1 release](https://github.com/FadhilMulinya/ckb-intel/releases/tag/ckb-behaviour-dataset-v1) and must be downloaded as `ckb-behaviour-dataset-v1.sqlite` and placed at `ckb_data/ckb_data_v2/ckb_explorer.sqlite`.

The verifier does not call Explorer. It validates hashes, contracts, row alignment, SQLite integrity, and runs the complete offline suite. The currently verified suite contains **80 passing tests**.

## Historical software

`classifier-service/`, `registry-service/`, and `REPORT.md` are retained as the **LEGACY / ABANDONED BASELINE**. They must not be used to interpret the final research outputs. See [limitations](docs/limitations.md).
