# CKB Wallet Behaviour Intelligence Service

This directory is the service layer for the current CKB-native V2 behaviour
pipeline. It exposes observable features, support/evidence states, and
descriptive behaviour rules. It does not classify human/bot identity, infer
ownership, or assign a definitive wallet type.

## Runtime flow

```text
CKB address → frozen observation OR live Explorer collection
           → common V2 observation → Feature V2 → V2 behaviour rules
           → structured wallet behaviour profile
```

`classifier-service/` is the authoritative Python implementation of CKB Wallet
Behaviour Intelligence. `v2_service.py` imports the authoritative
`wallet_intelligence.features_v2.pipeline.load_observation_v2`
and `assess_observation_v2`; feature formulas remain in the authoritative V2
modules and are not duplicated here.

## Modes

Frozen/offline mode is operational for addresses represented in
`ckb_data/ckb_data_v2/ckb_explorer.sqlite`. It performs no network requests.

Live mode collects a deterministic UTC rolling 30-day window from the CKB
Explorer mainnet API, resolves available previous outputs, and feeds the same
V2 observation/feature/rule pipeline. Incomplete Explorer evidence is exposed
through support states and limitations; the frozen SQLite is never modified.

## API and CLI

Run the API from the repository root:

```bash
cd classifier-service && uvicorn app:app --host 0.0.0.0 --port 8000
```

The `POST /analyze` request is:

```json
{"address": "ckb1...", "mode": "frozen"}
```

Use `"mode": "live"` for an arbitrary valid mainnet address.

The response is versioned as `wallet-behaviour-v2` and contains observation
metadata, evidence counts, one support state per V2 family, all V2 feature
results, rule results, and limitations. Invalid addresses return
`INVALID_ADDRESS`; valid addresses absent from the frozen database return
`NOT_IN_FROZEN_DATASET`; failed collection states return `COLLECTION_FAILED`.

```bash
python classifier-service/inference_cli.py ckb1... --json
```

## Scientific boundaries

HDBSCAN, PCA, GMM, and reference-cohort comparisons remain research artifacts
under `ckb_data/`. They are not converted into wallet identities or definitive
classifications by this service. Behaviour names such as
`CELL_CONSOLIDATION`, `FAN_IN_COLLECTION`, and `PERIODIC_EXECUTION` are
descriptive patterns whose support depends on the evidence available for the
observation.

The superseded V1 proxy-label implementation was removed from the repository;
Git history is the archive and is not imported by the active runtime.
