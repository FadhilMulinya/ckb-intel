# Offline reproduction

The grant-review path uses frozen local evidence and must not call Explorer.

Download `ckb-behaviour-dataset-v1.sqlite` from `<DATASET_RELEASE_URL>`, place it at `ckb_data/ckb_data_v2/ckb_explorer.sqlite`, and verify SHA-256 `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`. The URL is intentionally a placeholder until the release artifact is published.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-research.txt
./scripts/verify_final_research.sh .venv/bin/python
```

The wrapper verifies the manifest and database hashes, SQLite `quick_check`, 1,172-row aligned artifacts, Phase 2 source integrity, and all offline tests.

`requirements-research.txt` is the flexible supported dependency declaration. `requirements-research.lock.txt` records the exact CPython 3.12.13 artifact-generation environment; an independent clean-room audit also passed using Python 3.14.

To regenerate derived outputs from the frozen database/cache only:

```bash
PYTHONPATH=ckb_data .venv/bin/python ckb_data/feature_engineering_v2.py
PYTHONPATH=ckb_data .venv/bin/python ckb_data/validate_features_v2.py
PYTHONPATH=ckb_data .venv/bin/python ckb_data/exploratory_pca.py
PYTHONPATH=ckb_data .venv/bin/python ckb_data/exploratory_structure.py
./scripts/verify_final_research.sh .venv/bin/python
```

These commands overwrite derived phase directories deterministically where promised, so reviewers who only need verification should use the wrapper. `dataset_completion.py` and all acquisition clients are excluded from the default path. Live collection is historical/optional infrastructure and is intentionally not documented as a final-verification step.
