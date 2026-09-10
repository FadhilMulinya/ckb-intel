# CKB Wallet Behaviour Intelligence — Current Status

## A. What The Project Is Today

Users submit a CKB mainnet address with `frozen` or `live` mode. The classifier loads frozen data or collects live data from CKB Explorer, normalizes CKB Cells and transactions, resolves previous outputs, and runs Feature V2. The registry validates and stores the result in MongoDB. The output describes observable wallet behavior. It does not identify humans, bots, owners, exchanges, or malicious wallets.

## B. Current Architecture

```text
Client → registry-service :3000 → classifier-service :8000
       → CKB Explorer or frozen SQLite → Feature V2 → MongoDB → response
```

## C. Current API

Registry:

```text
GET  /api/v1/health
POST /api/v1/wallets/analyze
GET  /api/v1/wallets
GET  /api/v1/wallets/{address}
GET  /api/v1/wallets/{address}/features
GET  /api/v1/wallets/{address}/behaviors
GET  /api/v1/docs
GET  /api/v1/openapi.json
```

Classifier:

```text
GET  /health
POST /analyze
GET  /docs-overview
GET  /docs
GET  /openapi.json
GET  /redoc
```

## D. Live Arbitrary-Wallet Capability

**PARTIALLY PROVEN.** This address was absent from frozen SQLite and completed live analysis locally:

```text
ckb1qyqvkel34xpgrdtja8fddy93fgkp6lduy90q2u385q
```

It had zero transactions in the current window. A separate six-transaction live analysis also succeeded for a known frozen-cohort wallet. High-volume wallet performance is not proven.

## E. Response

Successful responses contain:

```json
{
  "version": "wallet-behaviour-v2",
  "address": "ckb1...",
  "network": "mainnet",
  "observation": {},
  "evidence": {},
  "feature_support": {},
  "features": {},
  "behaviors": [],
  "limitations": []
}
```

## F. Feature Families

The API exposes all nine families:

```text
temporal, periodicity, topology, lifecycle, templates,
scripts, typed_assets, capacity, lineage
```

Support depends on available evidence; unsupported measurements remain explicit.

## G. Behavior Rules

The twelve descriptive rules are:

```text
PERIODIC_EXECUTION, BATCH_DISTRIBUTION, FAN_IN_COLLECTION,
BURST_EXECUTION, CELL_FRAGMENTATION, CELL_CONSOLIDATION,
SCRIPT_TEMPLATE_REPETITION, RAPID_CELL_TURNOVER,
PASS_THROUGH_CANDIDATE, STATE_MACHINE_ACTIVITY,
IRREGULAR_ACTIVITY, MIXED
```

Rules can overlap and do not classify wallet identity.

## H. How To Test Locally

Start MongoDB, then run:

```bash
CLASSIFIER_PYTHON=/private/tmp/ckb-forensic-env/bin/python \
  ./scripts/start-services.sh
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3000/api/v1/health
```

Analyze and retrieve a live wallet:

```bash
curl -X POST http://127.0.0.1:3000/api/v1/wallets/analyze \
  -H 'content-type: application/json' \
  -d '{"address":"ckb1qyqvkel34xpgrdtja8fddy93fgkp6lduy90q2u385q","mode":"live"}'

curl http://127.0.0.1:3000/api/v1/wallets/ckb1qyqvkel34xpgrdtja8fddy93fgkp6lduy90q2u385q
```

Interactive docs: `http://127.0.0.1:3000/api/v1/docs`.

## I. Proven Tests

- Classifier tests: **37 passed**.
- Registry build and contract checks: **passed**.
- Research verifier: **53 passed, 1 skipped, 0 failed**.
- Final marker: `FINAL_RESEARCH_OFFLINE_VERIFICATION_OK`.
- Local live HTTP and Mongo retrieval: **manually proven**.
- Docker runtime: **not proven**; Docker daemon was unavailable.

## J. Frozen Dataset

```text
Population: 1,172 wallets
Observations: 1,169
Window: 2026-08-01T00:00:00Z to 2026-09-01T00:00:00Z
Manifest: ckb_data/dataset_completion/population_manifest_v1.jsonl
Manifest SHA-256: 705608bf0603e4ff803896d62305b5084dafbd408256fe007d82a6c3d8ff313e
SQLite SHA-256: e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322
```

## K. Current Limitations

- No public hosted API or demo.
- Docker deployment has not been run.
- High-volume Explorer collection can time out.
- No automated full live HTTP/Mongo integration suite.
- No public authentication or rate limiting.
- Behavior rules are transparent heuristics.
- Frozen research population is not representative of all CKB wallets.

## L. Safe Public Claims

The project provides local CKB-native wallet behavior analysis, using real Explorer data in live mode, with nine feature families and twelve descriptive rules. Frozen artifacts and the offline verifier are available.

## M. Claims To Avoid

Do not call it a bot detector, claim identity classification, claim 95.24% V2 accuracy, claim universal wallet coverage, claim production readiness, or claim that the population represents all CKB wallets.

## N. Can Nervos Test It?

**YES, WITH QUALIFICATIONS.** Nervos can clone the repository, run MongoDB and the two services, use Scalar docs, submit the address above, inspect the result, retrieve it, and run the research verifier. There is no public endpoint yet.

## O. Next Steps

1. Deploy a public test instance.
2. Add automated live integration tests.
3. Improve high-volume collection and add rate limiting.

## P. Short Final Status

Local V2 wallet behavior analysis works end to end. An unseen valid CKB address completed live Explorer analysis and Mongo retrieval. Nine feature families and twelve descriptive rules are returned. The system makes no human/bot or ownership claims. Frozen research verification passes. The API is locally testable through Scalar docs. Public deployment and high-volume guarantees remain unavailable.
