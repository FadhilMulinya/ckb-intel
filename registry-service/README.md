# CKB Wallet Behaviour Registry

This Node/Fastify service stores and queries `wallet-behaviour-v2` profiles
returned by `classifier-service`. It does not perform feature engineering,
identity classification, ownership attribution, or cluster naming.

The service is mounted under `/api/v1`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Registry health and version |
| POST | `/api/v1/wallets/analyze` | Calls classifier-service and persists a behavior profile |
| GET | `/api/v1/wallets` | Paginated registered profiles |
| GET | `/api/v1/wallets/:address` | Latest stored profile |
| GET | `/api/v1/wallets/:address/behaviors` | Descriptive behavior results |
| GET | `/api/v1/wallets/:address/features` | Features and support states |

`POST /api/v1/wallets/analyze` accepts `{ "address": "ckb1...", "mode": "frozen" }`.
The registry validates the returned `wallet-behaviour-v2` version, mainnet
network, and evidence-bearing response before upserting it into MongoDB.

Address requests must be lowercase mainnet `ckb1...` addresses with a valid
CKB Bech32/Bech32m checksum. Invalid addresses return `400 INVALID_ADDRESS`.
Classifier domain errors are preserved: `NOT_IN_FROZEN_DATASET`,
`V2_LIVE_ANALYSIS_NOT_YET_SUPPORTED`, and `COLLECTION_FAILED` return `422`.
Timeouts and connection failures return `503 CLASSIFIER_SERVICE_UNAVAILABLE`;
malformed classifier profiles return `422 INVALID_ANALYSIS_RESPONSE`.

Live analysis remains explicitly unsupported when classifier-service returns
`V2_LIVE_ANALYSIS_NOT_YET_SUPPORTED`.

The former V1 label, probability, ingestion, and model-evaluation semantics
were removed. The historical routes are preserved in Git history only.

## Local services

Run MongoDB, classifier-service on port 8000, and this service on port 3000.
Set `MONGODB_URI` (default `mongodb://localhost:27017/behaviour-intelligence`)
and `CLASSIFIER_SERVICE_URL` (default `http://127.0.0.1:8000`). A combined
development stack is available from the repository root with `docker compose up`.
