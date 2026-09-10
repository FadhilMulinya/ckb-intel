# Registry–Classifier Parity

## Status

Application parity is confirmed for the local runtime path. Docker deployment
parity is unverified because the Docker daemon/socket was unavailable in the
verification environment.

## Architecture

```text
Client
  ↓
registry-service :3000 (/api/v1)
  ↓ HTTP
classifier-service :8000 (/analyze)
  ↓
V2WalletService → wallet_intelligence → frozen SQLite / future live evidence
```

The registry owns API handling, CCC address validation, classifier contract
validation, persistence, retrieval, and error translation. The classifier owns
observation loading, feature extraction, support/evidence evaluation, and
descriptive behavior rules.

## Verified runtime flows

- A frozen address was analyzed through real registry-to-classifier HTTP.
- The complete scientific profile was persisted to MongoDB and retrieved.
- All nine feature families and all twelve behavior entries survived the
  round-trip unchanged.
- Invalid addresses returned `400 INVALID_ADDRESS`.
- A valid address absent from the frozen database returned
  `422 NOT_IN_FROZEN_DATASET`.
- Live mode returned `422 V2_LIVE_ANALYSIS_NOT_YET_SUPPORTED`.
- Classifier outage returned `503 CLASSIFIER_SERVICE_UNAVAILABLE`, and normal
  analysis recovered after restart.
- Malformed classifier profiles were rejected.

The system provides descriptive wallet-behaviour intelligence. It does not
classify wallets as human, bot, exchange, malicious, or any other identity.

## Tests

- Registry build, smoke, and contract validation: passed.
- Classifier tests: 34 passed.
- Research verifier: 54 tests, 53 passed, 1 skipped, 0 failures/errors.
- Final marker: `FINAL_RESEARCH_OFFLINE_VERIFICATION_OK`.
- `git diff --check`: passed.

## Docker caveat

`docker compose config` was verified. Image build, full stack startup, Docker
DNS runtime, and Docker end-to-end analysis were not executed because the
Docker daemon/socket was unavailable. This is an environment limitation, not a
demonstrated application defect.

## Scientific artifact integrity

The protected artifacts remained byte-for-byte unchanged. Their baseline and
final SHA-256 values are recorded in the final review report.

## Remaining product gap

Arbitrary live-wallet V2 analysis is still not implemented. That is the next
product phase and is separate from registry/classifier parity.
