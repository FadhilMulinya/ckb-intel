# registry-service

## What this service does

`registry-service` is a Node/Fastify/MongoDB service with one job: resolve CKB wallet addresses to their on-chain identity, and store the classification label a separate model writes back for each address. That's it.

- **Wallet identity** - given an address, resolves its lock script / lock script hash via [CCC](https://github.com/ckb-devrel/ccc), and computes a tx-count/first-seen/last-seen summary from the CKB Explorer API.
- **Classification storage** - accepts a label (`bot` / `human` / `uncertain` / `unknown`) + confidence score for an address and stores it, queryable and filterable.
- **No transaction data stored.** Ingestion pages through a wallet's transaction history only to compute the summary counters above - nothing per-transaction is written to MongoDB. The `wallets` collection is the only collection this service has.
- **Published model metrics** - reads and re-serves a separate model's evaluation results (accuracy, precision, recall, etc.) as JSON, live off disk.
- **Fail-fast startup** - refuses to start if the CKB RPC node or Explorer API isn't reachable.
- **Self-documenting** - every endpoint is described at `GET /api/v1/docs` , backed by `GET /api/v1/openapi.json`).

This service does not run any classification model, does not fetch transaction data for feature engineering, and does not decide what label a wallet gets - it only stores whatever label it's told, by whichever writes it.

> **Where the label comes from:** a separate Python service (`classifier-service/`, one directory up) fetches a wallet's transaction history, extracts behavioral features, and runs a trained classifier - completely independently of this service. After scoring a wallet, it optionally writes the result here via `PATCH /api/v1/wallets/:address/label`. See the top-level [`README.md`](../README.md) for how the two fit together, and [`../scripts/dev.sh`](../scripts/dev.sh) to run both at once.

## Installation

Requires **Node.js ≥ 18** and a reachable **MongoDB** instance (local `mongod`, Docker, or Atlas).

```bash
# GitHub repo is still named ckb-intel -- only the local directory here has
# been renamed to registry-service to match what this service actually is.
git clone git@github.com:FadhilMulinya/ckb-intel.git registry-service
cd registry-service
npm install
cp .env.example .env
# edit .env: set MONGODB_URI at minimum -- this service is mainnet-only,
# there's no network switch
```

## Quickstart

```bash
npm start          # or: npm run dev (watch mode)
```

On startup the app runs a pre-flight check against every external dependency and refuses to start if any is unreachable:

```
[preflight] checking external dependencies...
[preflight] ✅ ckb-rpc (CCC): mainnet tip block 15043210
[preflight] ✅ explorer-api: reachable at https://mainnet-api.explorer.nervos.org/api/v1
```

Resolve a wallet's identity:

```bash
curl -X POST http://localhost:3000/api/v1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"addresses": ["ckb1qzda0cr08m85hc8jlnfp3zer7xule..."]}'

curl http://localhost:3000/api/v1/wallets/ckb1qzda...
```

Re-running ingestion for the same address is safe - everything is upserted, so it simply refreshes tx-count/first-seen/last-seen.

Write back (or query) a classification label. `label` mirrors the classifier's own verdict values exactly - `bot` | `human` | `uncertain` | `unknown` - no other values are accepted:

```bash
curl -X PATCH http://localhost:3000/api/v1/wallets/ckb1qzda.../label \
  -H 'Content-Type: application/json' \
  -d '{"label": "bot", "botProbability": 0.94}'

curl "http://localhost:3000/api/v1/wallets?label=bot"
```

`PATCH .../label` upserts - it works even for an address this service has never ingested, so a label can never be silently dropped just because ingestion hasn't run yet.

Pull the model's published evaluation metrics:

```bash
curl http://localhost:3000/api/v1/model/evaluation
```

## API Docs

Full documented and  interactive reference (Scalar, backed by `GET /api/v1/openapi.json`):

```
http://localhost:3000/api/v1/docs
```

## API Reference

| Method | Route | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness check |
| GET | `/api/v1/chain/status` | Current tip block (RPC connectivity), mainnet only; cached 5s so repeated calls don't each pay a live RPC round trip |
| GET | `/api/v1/wallets?page=&pageSize=&label=` | List wallets, optionally filtered by label |
| GET | `/api/v1/wallets/:address` | One wallet's summary + classification document |
| PATCH | `/api/v1/wallets/:address/label` | Body `{ "label": "bot"\|"human"\|"uncertain"\|"unknown", "botProbability"?: number }` - write back a classification (auto-creates the wallet if needed) |
| POST | `/api/v1/ingest` | Body `{ "addresses": ["ckb1..."] }` - resolve wallet identity |
| GET | `/api/v1/model/evaluation` | Accuracy, precision, recall, F1, confusion matrix, dataset stats, label distribution, `lastUpdatedAt` |
| GET | `/api/v1/docs` | Interactive API reference (Scalar) |


## Architecture

The codebase follows a strict layered separation so contributors always know where a change belongs:

| Question | Answer | Folder |
|---|---|---|
| Does this involve HTTP? | **Controller** - I/O only | `src/controllers/` |
| Is this decision-making or logic? | **Service** | `src/services/` |
| Is this talking to the database? | **Repository** | `src/repositories/` |
| Is this talking to the outside world (RPC, Explorer API)? | **Client** | `src/clients/` |

```
src/
  index.ts          # entrypoint - delegates to server.ts, nothing else
  server.ts         # Fastify app construction, route mounting, lifecycle
  routes/v1/        # versioned route registration → controllers (+ docs, see below)
  controllers/      # I/O: parse request → call service → shape reply
  services/         # logic: ingestion orchestration, queries, evaluation read
  repositories/     # data: the only files allowed to touch Mongoose models
  clients/          # external: CKB RPC (CCC) + CKB Explorer API
  db/               # Mongo connection + Mongoose schema (Wallet only)
  config/           # env-driven configuration
  types/            # shared normalized transaction/cell-ref shapes
  utils/            # human-readable date formatting
  openapi.ts        # hand-authored OpenAPI document for /api/v1
  docs.ts           # serves /api/v1/openapi.json + /api/v1/docs (Scalar)
```

Design rules:

- **No inheritance.** Layers are plain modules composed together, never extended.
- **One direction only:** controllers → services → repositories/clients. A controller never imports a model; a repository never makes an HTTP decision. One documented exception: `services/evaluation.service.ts` reads a file off disk directly (a separate service's output artifact, not something any repository here owns).
- **Versioned API.** Everything - including the docs endpoints - is mounted under `/api/v1`. Breaking changes go in a new `routes/v2` folder with its own prefix.

### Ingestion data flow

```
address string
     │
     ▼
CKB client  ──► resolves address → lock script → lock script hash
     │             (src/clients/ckb.client.ts)
     ▼
Explorer client ──► pages through tx history for the address
     │                 (src/clients/explorer.client.ts)
     ▼
normalization.service ──► maps raw Explorer shape → internal schema
     │                       (src/types/index.ts)
     ▼
ingestion.service ──► folds each transaction into running counters
     │                  (tx-count, first-seen, last-seen) - nothing
     │                  per-transaction is kept after this
     ▼
wallet.repository ──► upserts the Wallet document in MongoDB
```

`getCkbClient()` uses [`@ckb-ccc/core`](https://github.com/ckb-devrel/ccc)'s default public mainnet RPC endpoint - mainnet only, no testnet code path exists in this service. There's currently no config override for the RPC URL itself.

### Training time window

Ingestion does **not** pull full wallet histories - bots and exchange hot wallets can have millions of transactions. Only transactions inside the training window (default **2025-06-01 → 2026-06-30**, configurable via `INGEST_WINDOW_START` / `INGEST_WINDOW_END`) count toward `txCount`/`firstSeenMs`/`lastSeenMs`.

The Explorer API has no server-side time filter, so the pipeline pages **newest-first**, skips transactions after the window, folds the ones inside it into the running counters, and stops paging at the first transaction older than the window. Work per wallet is bounded by the window, not by the wallet's lifetime. All window logic lives in `src/services/time-window.service.ts`.

## Data Model

**`wallets`** - the only collection. One document per address: lock script hash, network, first/last seen timestamps, transaction count, ingestion status, and the classification label + confidence + `classifiedAt` written back by the model.

**Model evaluation** - not stored in Mongo at all. `GET /api/v1/model/evaluation` (`src/services/evaluation.service.ts`) reads a shared `eval_results.json` artifact directly off disk on every request, so it always reflects whatever the model's most recent training run produced.

## Examples

[`examples/api-client.ts`](examples/api-client.ts) is a complete, dependency-free consumer of the API (plain `fetch`, works in Node 18+ or a browser). It walks the full flow: health check → chain status → ingest → wallet summary → label write-back → filtered wallet list.

```bash
npm start                                   # terminal 1: run the API
npx tsx examples/api-client.ts ckb1qzda...  # terminal 2: run the example
```

## Testing

```bash
npm run build      # full TypeScript compile check
npm test           # offline unit tests (normalization + time-window logic)
```

Manual end-to-end check:

```bash
npm start                                         # pre-flight must pass
curl http://localhost:3000/api/v1/health          # liveness
curl http://localhost:3000/api/v1/chain/status    # network + tip block
npx tsx examples/api-client.ts <ckb-address>      # full flow
```

For an automated end-to-end suite covering this service, `classifier-service`, and the write-back between them, see [`../tests/e2e_test.py`](../tests/e2e_test.py) and run it with `../scripts/e2e.sh` from the repo root.

To see the fail-fast behaviour, point `EXPLORER_API_URL_MAINNET` (or `_TESTNET`) at an unreachable host in `.env` and run `npm start` - the process exits with `preflight failed` instead of serving.

## Contributing

Find the layer your change belongs to (see [Architecture](#architecture)) and keep it there; PRs that put database queries in controllers or HTTP concerns in services will be asked to move them. New endpoints: add a controller function, wire it in `src/routes/v1/index.ts`, and add it to `src/openapi.ts` so it shows up in `/api/v1/docs`.

Good first contributions:

- Refining cell-kind classification - the current normalizer treats everything as `cellKind: "plain"` except cellbase inputs (SUDT/xUDT/DAO/NFT detection is open).

### Notes for contributors

- `capacityShannon` is kept as a string everywhere (CKB capacities can exceed JS's safe integer range) - use a bigint-safe library when computing on it.
- `MAX_TX_PER_WALLET` in `.env` is a safety cap (default 2000) so a single very active wallet (e.g. an exchange hot wallet) can't blow up an ingestion run.

## License

[ISC](https://opensource.org/licenses/ISC)
