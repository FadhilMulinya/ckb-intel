# CKB behavioural features and transparent rules v1

## Configuration and data sources

The clients in `ckb_clients.py` read:

```text
CKB_RPC_URL      default http://127.0.0.1:8114
CKB_INDEXER_URL  default CKB_RPC_URL
EXPLORER_API_URL default https://mainnet-api.explorer.nervos.org/api/v1
```

Boundary resolution binary-searches CKB's non-decreasing consensus timestamp
metric: the median timestamp of the preceding 37 canonical blocks (RFC 0017).
The start is the first block whose median time is greater than or equal to the
window start; the end is the last whose median time is less than or equal to
the window end. Local CKB RPC is tried first. Explorer `/blocks/{height}` is
the fallback. First/last observed transaction blocks are never substituted.
One result is cached per shared observation window.

Previous outputs resolve in this order: normalized `cells`, cached raw
transaction details, targeted local `get_transaction`, targeted Explorer
transaction detail, unresolved. No address range or chain-wide scan occurs.

## Feature schema

Version: `ckb-behaviour-features-v1`.

Temporal features use positive interarrival intervals. The dominant period is
the median interval. Periodicity strength is
`exp(-median_absolute_interval_deviation / dominant_period)`. Phase stability
is the circular resultant length of event phases modulo that period. The
method is transparent and suitable for irregularly observed events without
interpolation; it intentionally detects one dominant cadence, not a spectrum.
Periodicity requires at least eight transactions. Unmeasurable values are
`null`, never numeric zero.

Topology features describe Cell and lock structure. Fan-out means multiple
output locks in a transaction in which the target controls an input; it does
not mean the target economically paid every output. Fan-in means multiple
input locks and a target-controlled output; it does not establish that every
input owner paid the target.

Template hashes include Cell counts, target participation, canonical script
families/hashes, data lengths, and normalized capacity shapes. They exclude
transaction hash, block number, timestamp, witnesses, and signatures.

## Script registry

Version: `ckb-script-registry-v1`. Exact code-hash + hash-type matches recognize
SECP256K1_BLAKE160, SECP256K1_MULTISIG, and NERVOS_DAO. Constants come from
Nervos RFC 0024 (genesis script list). Unknown scripts remain `UNKNOWN`; their
canonical script hashes are retained in fingerprints.

## Rule configuration

Version: `ckb-rule-thresholds-v1`; implementation `ckb-transparent-rules-v1`.

| Pattern | Exact requirements for full score |
|---|---|
| PERIODIC_EXECUTION | ≥8 transactions, periodicity strength ≥0.80, phase stability ≥0.75, interarrival CV ≤0.35 |
| BATCH_DISTRIBUTION | ≥3 transactions, fan-out ratio ≥0.50, mean external output locks ≥2.0, template repeat ratio ≥0.50 |
| FAN_IN_COLLECTION | ≥3 transactions, fan-in ratio ≥0.50, mean external input locks ≥2.0, topology repeat ratio ≥0.50 |

Scores are the fraction of the three documented checks that pass. Full checks
with complete supporting data yield `SUPPORTED`; incomplete coverage yields
`PARTIAL`. Too few transactions yields `INSUFFICIENT_EVIDENCE` and a null score.

These rules report observable structure only. They do not infer operators,
economic counterparties, automated ownership, or pairwise value transfer.
