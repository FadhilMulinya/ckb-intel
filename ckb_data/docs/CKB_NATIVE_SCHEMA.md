# CKB-native evidence schema v1

This schema implements Phase 1 and Phase 2 of the behaviour-intelligence
redesign. It is additive: raw Explorer caches and the old `edges` table remain
on disk. `edges` is marked `LEGACY_DISABLED_NOT_SOURCE_OF_TRUTH` in
`schema_meta`; ingestion no longer writes it.

## Source of truth

```text
transactions
  ├── transaction_inputs ── previous_tx_hash + previous_output_index
  └── cells              ── creating_tx_hash + output_index
        ├── lock_scripts
        └── type_scripts
```

`transactions` stores block location (timestamps normalized to Unix epoch
seconds), transaction-level capacity totals, the
fee derived from resolved Cells, and conservation status. Every transaction is
explicitly marked `pairwise_value_attribution = NOT_ESTABLISHED`.

`cells` stores every created output independently, including capacity, lock
script, optional type script, output data, output index, and the unmodified
Explorer Cell JSON.

`transaction_inputs` stores each previous outpoint plus the resolved capacity,
lock/type scripts, data, an explicit resolution status, and `resolution_source`.
Missing previous
outputs remain `incomplete`; they are never converted to zero-value Cells.

`wallet_transaction_participation` records only lock-script control:
`target_controls_input` and `target_controls_output`. It makes no broader owner
or operator claim.

## Observation contract

`wallet_observations` enforces an exact 30-day interval with the database check:

```sql
window_end_timestamp - window_start_timestamp = 2592000
```

The contract version is `wallet-observation-30d-v1`. Coverage ratios are nullable:
unknown coverage is `NULL`, not zero. Listing, detail and input resolution also
carry status strings from:

```text
missing | failed_to_fetch | not_applicable | incomplete | complete
```

Observation block bounds are never taken from first/last observed transactions.
They are resolved independently from canonical block timestamps through local CKB
RPC, with Explorer block lookup as fallback. They remain null with
`boundary_resolution_status = unresolved` when neither source is available.

## Cached-data migration

Run locally against an existing database:

```bash
python3 ckb_data/migrate_ckb_native.py \
  --db ckb_data/ckb_data_v2/ckb_explorer.sqlite
```

This reads `raw_transactions.raw_json` and populates the normalized tables. It
does not make network requests and does not delete or rewrite raw responses.

Explorer transaction detail requested with `display_cells=true` can provide
resolved display inputs/outputs when present. If a cached input lacks its
previous Cell content, the parser retains the outpoint and marks it incomplete.
A future repair job may resolve it from another cached transaction or CKB RPC;
the current parser does not guess.

## Capacity conservation

When every input has a resolved capacity and every output capacity is present:

```text
fee = sum(input Cell capacities) - sum(output Cell capacities)
```

Negative fees or disagreement with a reported Explorer fee produce `failed`.
Cellbase transactions are `not_applicable`. Incomplete resolution produces
`incomplete`.

## Deliberately unsupported projections

- sender-to-recipient capacity attribution;
- automatic change identification;
- counterparty identity;
- typed-asset amount decoding;
- pairwise routes and cycles.

These require explicit, versioned derivation methods built on the normalized
transaction/Cell hypergraph.
