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
| Wallet-transaction participation rows | 51,816 |
| Distinct participating transactions | 47,145 |
| Applicable input rows | 56,407 / 56,407 resolved (100% resolution status); Cellbase inputs are `NOT_APPLICABLE` |
| Authoritative manifest | `ckb_data/dataset_completion/population_manifest_v1.jsonl` |
| Manifest SHA-256 | `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe` |
| Database SHA-256 | `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322` |

This is a reproducible observational cohort assembled from overlapping historical local sources, not a random or statistically representative sample of all CKB wallets. The authoritative population manifest is `ckb_data/dataset_completion/population_manifest_v1.jsonl`; other manifest-like files are validation or historical artifacts. Of 1,172 wallets, 425 retain provenance-only legacy proxy metadata (222 `bot_like`, 203 `human_like`); 747 have no proxy label. Those fields were excluded from Feature V2 and all exploratory ML.

## Architecture

`classifier_service/` is the authoritative Python implementation boundary for
wallet observation loading, Feature V2 extraction, support states, and
descriptive behaviour rules, collection clients, normalization, and
previous-output resolution. `ckb_data/` contains frozen observations,
manifests, datasets, and research orchestration that consumes the service
package.

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
- [Validation gates](docs/validation-gates.md)
- [Repository audit](docs/repository-audit.md)
- [Artifact index](artifacts/README.md)
- [Final research report](reports/final-research-report.md)
- [Current project status](reports/project-status-report.md)

## Start the services

The registry requires external MongoDB/Atlas. Set `MONGODB_URI` in your
environment (no local MongoDB), then run both application services from the
repository root:

```bash
./scripts/start-services.sh
```

The script starts classifier-service on `http://127.0.0.1:8000` and
registry-service on `http://127.0.0.1:3000`. Set `CLASSIFIER_PYTHON` if the
classifier dependencies are installed in a virtual environment, for example:

```bash
CLASSIFIER_PYTHON=/private/tmp/ckb-forensic-env/bin/python ./scripts/start-services.sh
```

Check service health at:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:3000/api/v1/health
```

Interactive Scalar API documentation for the registry is available at
`http://127.0.0.1:3000/api/v1/docs`; the generated OpenAPI document is at
`http://127.0.0.1:3000/api/v1/openapi.json`.

To analyze a wallet after startup:

```bash
curl -X POST http://127.0.0.1:3000/api/v1/wallets/analyze \
  -H 'content-type: application/json' \
  -d '{"address":"ckb1...","mode":"live"}'
```

## Production deployment

The target is `https://api.afriai.xyz`. Only registry is published, at
`127.0.0.1:3000`; classifier stays on Docker networking at
`http://classifier-service:8000`. MongoDB is external Atlas, never a local
container. Both services use `restart: unless-stopped`.

1. Clone the repository or pull the reviewed commit onto the VPS.
2. Copy `.env.example` to `.env`, restrict its permissions (`chmod 600 .env`),
   and set `MONGODB_URI` to your external Atlas URI. Allow the VPS egress IP in
   Atlas and use a dedicated database user. Never commit `.env`.
3. Supply the existing Dataset V1 SQLite separately at
   `deployment-data/ckb_explorer.sqlite`, or set `FROZEN_SQLITE_PATH` to its
   absolute server-side path. Verify SHA-256
   `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`
   (862994432 bytes). Make it readable by container UID 10001, for example mode
   `0444`. It mounts read-only at `/app/ckb_data/ckb_data_v2/ckb_explorer.sqlite`.
   Missing mount sources fail startup; do not create or substitute a database.
4. Build and start from the repository root:

   ```bash
   docker compose config --quiet
   docker compose build
   docker compose up -d
   docker compose ps
   ```

5. Verify internal classifier and localhost registry health:

   ```bash
   docker compose exec classifier-service python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read().decode())"
   curl --fail http://127.0.0.1:3000/api/v1/health
   ```

6. Configure your host HTTPS reverse proxy for `api.afriai.xyz` and forward to
   `http://127.0.0.1:3000`. Configure Cloudflare proxied DNS and Full (strict)
   TLS yourself, with a valid origin certificate. Allow origin HTTPS only from
   Cloudflare's published IP ranges; keep administrative access separate.

For nginx, maintain an include with `set_real_ip_from` entries for only the
current official Cloudflare IPv4/IPv6 ranges. Never trust arbitrary senders of
`CF-Connecting-IP`. Inside the HTTPS server block:

```nginx
include /etc/nginx/cloudflare-real-ip.conf;
real_ip_header CF-Connecting-IP;
real_ip_recursive on;
client_max_body_size 16k;
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header CF-Connecting-IP "";
    proxy_set_header Forwarded "";
    proxy_connect_timeout 5s;
    proxy_read_timeout 35s;
    proxy_send_timeout 10s;
    proxy_next_upstream off;
}
```

Overwrite X-Forwarded-For; do not append incoming client headers. Fastify trusts
only `TRUSTED_PROXY_CIDRS`, defaulting in Compose to the host bridge gateway
`172.30.0.1/32`. If its subnet conflicts with an existing network, update
`DOCKER_SUBNET`, `DOCKER_GATEWAY`, and `TRUSTED_PROXY_CIDRS` together. Verify the
peer address on the VPS and test rate isolation from two real client IPs. Never
fix a mismatch by trusting all proxies. Standalone registry trusts none by default.

Environment reads live in `registry-service/src/environments.ts` and
`classifier_service/environments.py`; `.env.example` lists production settings.
CORS uses exact configurable origins, GET/POST/OPTIONS, Content-Type/Accept,
and no credentials. Disallowed origins receive no CORS permission header.
Analysis defaults to 5 requests/IP/60 seconds; the four wallet read routes share
60 requests/IP/60 seconds. Limits return 429 with retry/rate headers. Health,
docs/OpenAPI, and OPTIONS are excluded. Buckets are in memory and reset on restart.
Run one registry process and one classifier worker.

Live analysis permits two simultaneous jobs by default; excess requests receive
503 `ANALYSIS_BUSY` and `Retry-After: 5`. Slots remain occupied until work ends,
even if the registry's 20-second timeout expires. Frozen requests do not acquire
this semaphore. Live collection still uses temporary SQLite and Explorer; there
is no whole-analysis deadline or total transaction cap, so high-activity wallets
can exceed available time or memory. This is not a high-volume reliability claim.
Explorer calls use configurable timeouts/retries; retry sleeps are capped at
8 seconds plus jitter. Mongo connection/selection timeouts are 5 seconds, socket
timeout 10 seconds, and pool size 5.

Health checks report liveness, not database/Explorer readiness. Registry requires
Atlas at startup, but transient Atlas failures do not change its health response.
Verify the frozen hash separately. Docker build/startup, TLS, Atlas connectivity,
proxy attribution, and representative live/frozen requests must be checked on
the VPS. Configuration alone does not mean the public API is deployed.

## Verify offline

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-research.txt -r classifier_service/requirements-dev.txt
./scripts/verify_final_research.sh .venv/bin/python
```

`requirements-research.lock.txt` records the exact artifact-generation versions; the flexible file is the supported installer. The frozen database is distributed separately in the [Dataset V1 release](https://github.com/FadhilMulinya/ckb-intel/releases/tag/ckb-behaviour-dataset-v1) and must be downloaded as `ckb-behaviour-dataset-v1.sqlite` and placed at `ckb_data/ckb_data_v2/ckb_explorer.sqlite`.

The verifier does not call Explorer. It validates hashes, contracts, row alignment, SQLite integrity, and runs the complete offline suite under `ckb_data/tests`. The suite currently contains 71 passing tests and 11 intentional skips.

## Historical software

An earlier V1 proxy-label human/bot classifier was retired after review. Its
executable source, model artifacts, and registry service were removed; Git
history preserves the superseded implementation. The active
`classifier_service/` is the V2 wallet behaviour service.
