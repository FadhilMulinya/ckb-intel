# CKB Wallet Data Acquisition Pipeline

This document describes how the wallet dataset used for behavioral
classification (human-operated vs. automated) was acquired: from choosing
which addresses to look at, through pulling their transaction history from
CKB Explorer, to verifying the collection actually finished cleanly.

**Current status:** acquisition complete. 890 candidate addresses were
discovered; 887 returned a usable provenance record; of those, 764 have
transaction activity in the collection window (the population for
behavioral clustering) and 123 are genuinely unused/dormant in that
window — real, valid data about those wallets, kept as their own labeled
category rather than discarded (see *Stage 3* below).

---

## Pipeline overview

```
ckb_addresses.py                collect_target_wallets.py         analyze_collection_status.py
(discover candidate  ) -----> (pull time-windowed history,  ) --> (verify + categorize what     ) --> classify_wallet_status.py
(addresses           )        (resumable, idempotent        )     (was actually collected       )     (active / unused / malformed / not-collected)
        |                              |                                    |
        v                              v                                    v
   addresses.txt              ckb_data_v2/ckb_explorer.sqlite      wallet_collection_status.csv
                               ckb_data_v2/provenance/*.json       wallets_active.txt (input to
                                                                    clustering) + wallets_unused.txt
                                                                    (kept, labeled, not discarded)
```

Everything below refers to scripts that live together in one working
directory and import each other directly (`ckb_explorer_pull.py` is the
shared low-level HTTP/DB layer every other script builds on).

---

## Stage 1 — Discovering candidate addresses (`ckb_addresses.py`)

**Goal:** build a list of addresses that represents a genuinely diverse
slice of on-chain activity, not just "whoever happens to be near one
starting point."

**Why this needed its own design thought:** the natural way to find
addresses is to start from one known address and follow its transaction
counterparties outward (a BFS crawl). That was tried first, and it failed
in an instructive way — seeding from a single mining address produced a
sample dominated by other miners, mining-pool payout wallets, and the
large exchanges miners settle with. The clustering built on top of that
data couldn't separate "human vs. bot" because the sample itself was one
narrow neighborhood, not a cross-section of the network.

**What it does instead:** samples **scattered block numbers** across a
wide historical range (`--block-lookback`, default 2,000,000 blocks back)
rather than one contiguous run of recent blocks. Blocks even 100 apart are
still from the same few-minute window with the same active users and
network conditions — scattering across a much wider span avoids that
correlation. For each sampled block, every transaction's inputs and
outputs are scanned and any new address is added to the output list.

**Practical details:**
- Writes each newly discovered address to the output file **immediately**,
  flushed to disk the instant it's found — not batched until the end. A
  1000-address discovery run scans many blocks; without this, a crash or
  interrupt partway through would lose everything.
- Resumable: if the output file already has addresses in it, they're
  loaded first and the run tops up toward `--target` instead of
  restarting or duplicating.

```
python3 ckb_addresses.py --target 1000 --output addresses.txt
```

This produced the 890-address list (`addresses.txt`) used for the rest of
this pipeline. **This is also the one step where the human judgment
matters most** — the scattered-block sampling avoids neighborhood bias,
but if you have independent ground truth (a few addresses you know for
certain are bots, or personal wallets), mixing those in by hand is worth
more than any number of additional randomly-discovered addresses.

---

## Stage 2 — Pulling wallet history (`collect_target_wallets.py`)

This is the core of the pipeline, and the part with the most deliberate
design decisions. The script file is `collect_target_wallets_v3.py` on
disk (the version number reflects how many times the collection strategy
itself was revised — see *Design decisions* below).

### Basic usage

```
python3 collect_target_wallets.py --data-dir ./ckb_data_v2 \
    --addresses addresses.txt \
    --lookback-days 730 --max-tx-listed 0 --max-tx-details 0 \
    --as-of 2026-08-23
```

- `--data-dir` — everything lives under one folder:
  `{data-dir}/ckb_explorer.sqlite` (the database) and
  `{data-dir}/provenance/<address>.json` (one record per wallet — see
  below).
- `--lookback-days` — how far back from `--as-of` to pull. **Every wallet
  gets the same window**, not the same transaction count (see below).
- `--as-of` — a **fixed** reference date. This must stay identical across
  every run in a collection effort, including resumed/interrupted ones —
  otherwise the window silently shifts by however many days have passed,
  and nothing will match on resume.
- `--max-tx-listed` / `--max-tx-details` — `0` means **unlimited** for
  either. A positive number is a safety cap.
- `--fetch-order` — `sequential` (default) or `even` (see below).

Sanity-check one address before committing to the full list:

```
python3 collect_target_wallets.py --data-dir ./ckb_data_v2 --test-address ckb1q...
```

### Design decisions and why

**A fixed time window, not a fixed transaction count.** Early versions
capped collection at "the most recent 300 transactions." That gives every
wallet a *different* observation period: a wallet transacting every 60
seconds hits 300 transactions in half a day; a quiet wallet's 300 might
span 3 years. Every behavioral feature downstream (timing variance, burst
structure, monthly cycles) is sensitive to how much history it's computed
over — comparing a bot's half-day window against a human's 3-year window
measures "different observation windows," not "different behavior." A
730-day (~2 year) window was chosen as a default: long enough to cover
~24 monthly cycles, short enough that a wallet's operator/purpose hasn't
plausibly changed hands partway through, and meaningfully cheaper in API
calls than going back further.

**Listing and detail fetching are capped separately, because they cost
different amounts.** Listing a wallet's transactions is cheap (50 per
API call, no per-transaction cost). Fetching full detail for one
transaction (needed for graph and capacity features) is one API call
each — the expensive step. `--max-tx-listed 0` (unlimited listing) is
cheap enough to always leave on; `--max-tx-details` is the real
rate-limit lever.

**`0` means unlimited for both caps, and this matters for fairness, not
just completeness.** A fixed cap — even a generous one — still means a
wallet under the cap gets 100% coverage while a wallet over it doesn't,
for no principled reason tied to behavior. Unlimited puts every wallet on
equal footing: full history, or (if genuinely still capped by network
reality) full history so far, and that fact is recorded explicitly rather
than hidden.

**Sequential (newest → oldest), resumable fetching — not sampling — for
transaction detail.** Once the decision was made to aim for each
wallet's true total rather than a fixed sample, the fetch order needed to
support resuming a partially-completed wallet exactly where it left off,
without re-fetching or skipping anything. `--fetch-order sequential`
walks strictly from the newest block backward; a second run with a
higher cap (or the same cap, resumed after an interruption) picks up
exactly at the boundary the first run stopped at. `--fetch-order even`
exists as an alternative that spreads detail-fetches across the *whole*
window at every intermediate stage instead — useful if you want partial
coverage to still be representative of the full window rather than just
the most recent slice, at the cost of not being a strict "complete
history so far."

**Never re-fetch what's already cached.** A transaction's content is
immutable and content-addressed by its hash — it cannot change once
mined. `raw_transactions` is therefore treated as a pure, permanent
cache: before fetching any transaction's detail, the script checks
whether it's already stored, and skips the network call if so. Raising
`--max-tx-details` on a wallet that already has partial detail only
fetches the *new* transactions needed to reach the higher cap — verified
directly during development by counting real fetch calls across a
capped-then-raised run (100 new calls to go from 50 → 150, not 150).

**Genuinely idempotent, window-aware resumability.** Interrupting a run
and re-running the identical command should do nothing to
already-complete wallets and should not redo completed work on
partially-complete ones. Each wallet's provenance record is checked
against the *current* window and caps before deciding whether to skip,
do an incremental top-up, or do a full re-pull:
- Same window, nothing was truncated last time → **skip**, no network
  calls at all.
- Same window, something was truncated and the relevant cap increased →
  **incremental top-up**, reusing all previously-fetched data.
- Different window (a real `--lookback-days` or `--as-of` change) →
  **full re-pull** for that address only (its own rows are cleared first,
  no other wallet is touched).

**Real per-wallet lock hash, computed correctly.** CKB Explorer's address
endpoint returns the raw `lock_script` (code_hash / hash_type / args) but
not the resulting hash. The real hash is computed here via
molecule-serializing the script and hashing with
`blake2b(digest_size=32, person=b"ckb-default-hash")` — the same
algorithm CKB itself uses.

**Edges are keyed by address, not by lock hash — a genuine, documented
quirk of the underlying data.** The Explorer API's transaction detail
(`display_inputs`/`display_outputs`) carries only flat fields
(`address_hash`, `capacity`) with no nested lock-script data on
individual cells. `ckb_explorer_pull.py`'s edge-derivation logic
(`resolve_transaction_to_edges`) therefore falls back to using
`address_hash` as the identifier — meaning the `edges` table's
`from_lock_hash`/`to_lock_hash` columns are, in practice, addresses, not
real script hashes, despite the column names. This was confirmed
empirically (100% of a large sample of `edges` rows start with `ckb1`,
the address prefix, not `0x`, the hash prefix) and every downstream
feature-engineering step is written to match this reality rather than
the column names.

**Long/unusual addresses are hashed for their provenance filename.** A
handful of addresses discovered during Stage 1 turned out to be 300-400+
characters long — far beyond a normal CKB address (46-155 characters) —
almost certainly a parsing artifact from an unusual cell type rather than
a real spendable wallet. Windows has a roughly 260-character total path
limit, and `provenance/<390-character-address>.json` blew past it,
causing silent `FileNotFoundError`s on three addresses during the full
run. Fixed by hashing the filename (not the content — the full address is
still stored inside the JSON) whenever it exceeds 150 characters.

---

## Provenance: the paper trail per wallet

Every wallet gets `ckb_data_v2/provenance/<address>.json`, written the
moment that one wallet's pull finishes — not batched with the rest of the
list. This is both a completion marker (used for resumability) and an
audit record:

```json
{
  "address": "ckb1q...",
  "status": "complete",
  "collected_at_utc": "2026-08-24T03:04:56Z",
  "window_start_epoch": 1724371200,
  "window_end_epoch": 1787443200,
  "window_start_utc": "2024-08-23T00:00:00Z",
  "window_end_utc": "2026-08-23T00:00:00Z",
  "lookback_days": 730,
  "max_tx_listed": 0,
  "max_tx_details": 0,
  "deepest_block": {"block_number": 13840788, "block_timestamp_utc": "...", "tx_hash": "0x..."},
  "shallowest_block": {"block_number": 19054246, "block_timestamp_utc": "...", "tx_hash": "0x..."},
  "n_tx_in_window": 64,
  "n_tx_detail_fetched": 64,
  "n_tx_detail_remaining": 0,
  "n_tx_detail_remaining_is_exact": true,
  "listing_truncated": false,
  "detail_sampled": false,
  "fetch_order": "sequential",
  "n_dao_events": 0
}
```

`deepest_block`/`shallowest_block` give the exact oldest/newest
transaction actually observed for that wallet — the real evidence of
where its data came from, independent of what the *requested* window was.

---

## Stage 3 — Verifying what was actually collected

Several small scripts exist for checking collection health at different
levels, because "did this finish?" turned out to have more than one
honest answer (finished vs. finished-but-capped vs. never-really-started).

| Script | Answers |
|---|---|
| `check_collection_status.py` | Does the database actually contain what the provenance files claim? Cross-checks the two and flags any mismatch — a real consistency check, not a rubber stamp. |
| `check_collection_caps.py` | At a population level, are `--max-tx-listed`/`--max-tx-details` actually binding for this dataset, or would raising them do nothing? Also flags dormant wallets (no activity in the back part of the window). |
| `analyze_collection_status.py` | The master report. Categorizes every wallet as fully collected / known-total-with-remainder / unknown-true-total (listing capped) / zero data, writes `wallet_collection_status.csv`, and writes ready-to-use address lists for topping up each category specifically. |
| `classify_wallet_status.py` | Final population classification, into four genuinely distinct groups: `active` (has transaction activity — the clustering population), `unused` (successfully collected, zero activity in the window — **valid data, kept and labeled**, not discarded, since dormancy is a real fact about a wallet, not a collection defect), `malformed` (implausibly long address — the one genuine exclusion category), and `not_collected` (no provenance yet — retry, don't exclude). |

```
python3 analyze_collection_status.py --data-dir ./ckb_data_v2
python3 classify_wallet_status.py --data-dir ./ckb_data_v2 --addresses addresses.txt
```

---

## Final state of this dataset

| | Count |
|---|---|
| Candidate addresses discovered (Stage 1) | 890 |
| Addresses with a usable provenance record | 887 |
| — active (has transaction activity in the window) | 764 |
| — known total, partial detail remaining | 0 |
| — listing truncated (true total unknown) | 0 |
| — unused (successfully collected, zero activity — valid data) | 123 |
| Addresses that failed outright (Windows path-length bug, since fixed) | 3 |

The 0/0 in the two "still needs work" rows means the collection genuinely
converged: every active wallet now has its **complete** transaction
history for the window, not a sample of it, and that was reached without
a shared ceiling — each wallet was pulled to its own actual total. The
123 unused wallets are real data (they were successfully queried and
confirmed to have no transactions in this 730-day window) — this is a
fact about those wallets, not a collection failure, and they should stay
in the dataset as their own labeled category (e.g. a third class
alongside human/bot) rather than being discarded. They're set aside from
the *clustering* population specifically because there's no activity to
compute behavioral features from, not because the data about them is
invalid.

**Next step:** feed `wallets_active.txt` (764 wallets) into the
preprocessing stage (`preprocess_ckb.py`) to build the feature matrix
used for clustering. Keep `wallets_unused.txt` alongside it for the final
report/labeling rather than deleting it.

---

## Database schema reference

For anyone querying `ckb_explorer.sqlite` directly:

| Table | Key columns | Notes |
|---|---|---|
| `queue` | `address` (PK), `status`, `hop` | Tracks crawl status per address. |
| `raw_addresses` | `address` (PK), `lock_hash`, `raw_json`, `fetched_at` | Cached address-detail API response; `lock_hash` is the real molecule/blake2b hash. |
| `address_tx_seen` | `address`, `tx_hash`, `block_timestamp` (composite PK) | Every transaction observed for a wallet within its collected window. |
| `raw_transactions` | `tx_hash` (PK), `raw_json`, `fetched_at` | Full transaction detail, cached permanently (content-addressed, immutable). |
| `edges` | `from_lock_hash`, `to_lock_hash`, `value_shannon`, `tx_hash` (composite PK) | **Actually address-keyed**, not hash-keyed — see Design decisions above. |
| `wallets` | `lock_hash` (PK), `address`, `lock_code_hash`, `lock_hash_type` | One row per unique lock script observed. |
| `dao_events` | `address`, `event_type`, `tx_hash` | Nervos DAO deposit/withdrawal events, best-effort (this endpoint 404s for most wallets, which just means no DAO activity — not a fetch failure). |

