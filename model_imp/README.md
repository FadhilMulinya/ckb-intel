# CKB Wallet Behaviour Intelligence — unsupervised end-to-end pipeline

Groups **CKB addresses** (lock scripts, not EVM-style accounts) into behaviour
**clusters** discovered directly from the data — no assumed labels, no
`bot`/`human`/`miner` categories baked in up front — using only data pulled
live from the public **CKB Explorer API** (`mainnet-api.explorer.nervos.org`).
Each cluster gets an auto-generated, human-readable description of what its
members actually do on-chain, and any address can then be assigned to its
nearest cluster for interpretation.

This follows the CKB-native research in `Report.docx` (Cells/lock-scripts as
the entity, Cell topology/lifecycle/`since` timelocks as evidence) and its own
recommended methodology (Section 28):

```
Phase A: transparent, auditable feature rules   -> labeling.py
Phase B: unsupervised clustering for discovery  -> cluster_model.py   <-- core of this pipeline
Phase C: interpret each cluster                 -> cluster_model.py (automated + auditable)
Phase D: (optional, later) supervised model once a human has reviewed
         and possibly corrected the Phase C cluster names
```

There is **no ground-truth "bot" label anywhere in CKB Explorer** (or anywhere
else), so this pipeline never claims one. It clusters wallets by behaviour
first, then *describes* each cluster from its own statistics, and only uses
the transparent heuristic rules as a naming aid (majority vote within a
cluster, reported with a `purity` score) — not as a supervised target.

## Pipeline stages

```
acquisition.py    -> pulls raw Explorer JSON per wallet, fixed 30-day window
cell_resolver.py  -> normalizes display_inputs/display_outputs into Cell records
features.py       -> ~60 CKB-native behavioural features
labeling.py        -> transparent, evidence-gated heuristic rules (used only
                       to help NAME clusters, never as a training target)
dataset.py         -> orchestrates the above into data/processed/wallet_dataset.csv
cluster_model.py   -> standardizes features, picks k via silhouette score,
                       fits KMeans, and auto-generates a description + suggested
                       archetype name + purity score for every cluster
infer.py            -> address -> pull -> features -> nearest cluster + description
```

## Quick start

```bash
pip install -r requirements.txt

# 1) Build a dataset (crawls recent blocks for seed addresses, stratifies by
#    activity level, pulls each wallet's 30-day transaction window, computes
#    features). Takes a while - it's a public API, throttled client-side.
python dataset.py --n-blocks 400 --per-bucket 40

# 2) Discover clusters (k chosen automatically via silhouette score, 3-10 range)
python cluster_model.py --k-min 3 --k-max 10

# 3) Assign any address to its nearest cluster, end to end
python infer.py ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqvz8...

# Anytime (even mid-collection, in another terminal): check on progress
python stats.py
```

`infer.py` prints something like:

```json
{
  "address": "ckb1q...",
  "evidence_state": "OK",
  "transactions_observed": 214,
  "observation_window_days": 30,
  "heuristic_hint": "BATCH_DISTRIBUTOR",
  "heuristic_confidence": 0.91,
  "heuristic_reason_codes": ["REPEATED_FANOUT", "FANOUT_TX_RATIO_0.62", "RECIPIENT_STRUCTURE_RECURRENCE"],
  "cluster": {
    "cluster_id": 4,
    "suggested_archetype": "BATCH_DISTRIBUTOR",
    "cluster_purity": 0.83,
    "description": "Typically frequently pays out to many recipients at once; has a large number of distinct payees; ...",
    "distance_to_cluster_center": 1.42,
    "assignment_margin": 0.87,
    "cluster_size_in_training_sample": 34
  }
}
```

`cluster_purity` tells you how internally consistent that cluster's members
are (1.0 = every member agreed with the transparent heuristic rules; lower
means it's a real, distinct group by the data but a mixed bag by rule-of-thumb
labels — worth a human look, exactly as the doc recommends). `assignment_margin`
tells you how confidently *this* wallet lands in its cluster vs. the
next-closest one — a small margin means the wallet sits near a cluster
boundary.

## Why cluster instead of training a classifier on heuristic labels?

An earlier version of this pipeline trained a supervised RandomForest on
heuristic-rule labels. That has a real problem: the model just learns to
reproduce the rules it was trained on, which teaches you nothing new. Pure
unsupervised clustering instead lets the **data** tell you what groups
actually exist — you might find five clean clusters, or you might find that
"bot-like" wallets actually split into two very different sub-populations
the rules didn't distinguish (e.g. payroll bots vs. arbitrage bots). Run
`cluster_model.py` and read the `description` + `top_distinguishing_features`
for every cluster before trusting any name — that's Phase C, and it's meant
to involve you.

If you later hand-review and relabel some clusters and want a fast classifier
for new wallets instead of always re-running KMeans, that's Phase D — train a
supervised model on your reviewed labels using the same `features.py` vectors.
Nothing else in the pipeline changes.

## Feature families (features.py)

| Family | Examples | Doc section |
|---|---|---|
| Observation/evidence | `transactions_observed`, `evidence_state` (excluded from clustering features — Section 26 leakage guard) | §25, §26, §31 |
| Temporal | `interarrival_cv`, `burstiness`, `periodicity_strength`, `dominant_period_hours` | §11 |
| Cell topology | `fanout_tx_ratio`, `fanin_tx_ratio`, `topology_entropy`, `single_to_single_ratio` | §12 |
| Capacity | `capacity_in_total`, `net_capacity_delta`, `capacity_fragmentation/consolidation` | §6 |
| Cell lifecycle | `cell_lifetime_mean_s`, `short_lived_cell_ratio`, `same_block_spend_ratio` | §7 |
| `since` / timelock | `uses_since_ratio`, `repeated_since_value_ratio` | §10 |
| Type script | `dao_capacity_share`, `udt_capacity_share` (from Explorer's `cell_type`) | §17-19 |
| Counterparty/network | `fanin_source_entropy`, `round_trip_partner_ratio` | §13-15 |
| Miner evidence | `cellbase_reward_ratio`, `is_known_miner_address` (direct, not inferred) | — |

`cell_lifetime_*` is computed **without extra API calls**: Explorer's
`display_inputs` already includes `generated_tx_hash`/`cell_index` (the
creating OutPoint), so lifetime is resolved whenever the creating transaction
is inside the same wallet's observed window. Cells created outside the window
are correctly left unresolved rather than assumed to be instant-spends.

## Evidence gating (why some wallets never get clustered)

Wallets with zero transactions in the 30-day window are `INACTIVE`. Wallets
with fewer than `config.MIN_TX_FOR_EVIDENCE` (default 5) are
`INSUFFICIENT_EVIDENCE`. Neither is fed into the clustering step — clustering
near-empty feature vectors just produces a meaningless "low activity" cluster
that swallows signal from every real behavioural group (Section 25).

## Upgrading from an older copy of this pipeline

If you collected data with an earlier version of `acquisition.py` (before
`status="capped"` existed as distinct from `status="complete"`), some cached
wallets in `data/raw/` may say `status: "complete"` even though they actually
hit a safety cap without proving full window coverage — `stats.py` will show
this as a contradiction (`capped: 0` in the status counts, but some wallets
flagged `[CAPPED]` in the "largest wallets" list). This self-heals the next
time each wallet is touched by `dataset.py`/`infer.py`, or fix it immediately
for everything on disk in one pass:

```bash
python repair_cache.py --dry-run   # see what would change first
python repair_cache.py             # apply it
```

## Full-window guarantee (why "capped" exists as its own status)

Because the window is short (30 days), the whole point is that every wallet's
data should be the **complete** month, not a truncated slice — a partial month
would quietly bias every temporal/topology feature (fewer transactions looks
like a bot's "template repetition" or a normal human's "low activity" for the
wrong reason). Two safety valves exist purely to stop a runaway loop
(`config.MAX_TX_PER_WALLET`, default 50,000; `config.MAX_PAGES_PER_WALLET`,
default 3,000) — but hitting either one produces a **third, distinct status**:

| status | meaning | included in training CSV? |
|---|---|---|
| `complete` | Proved full window coverage: either hit a transaction older than the window, or exhausted the wallet's entire history first. | Yes |
| `partial` | Network/time-budget interruption mid-pull. Resumable - re-running continues from the last checkpointed page. | No (until it becomes `complete`) |
| `capped` | Safety valve fired **while still inside the window** - the wallet's true in-window activity may exceed the cap. **Never treated as a complete month.** | No, ever - unless you raise the caps and re-run |

`capped` is never silently relabeled `complete` — that distinction is the fix
for the exact failure mode this section is about. If you see wallets logged as
`capped`, raise the limits and re-run (it resumes from the checkpointed page,
it does not restart):

```bash
python dataset.py --max-tx-per-wallet 200000 --max-pages-per-wallet 10000
python infer.py <address> --max-tx-per-wallet 200000 --max-pages-per-wallet 10000
```

## Checking on collection progress: `stats.py`

Reads only from disk (`data/raw/*.json`, the sample manifest, the processed
CSV, cluster profiles if built) - no network calls, safe to run anytime,
including in a second terminal while `dataset.py` is still pulling.

```bash
python stats.py                        # full report: status counts, tx volume
                                        # distribution, capped/errored wallets,
                                        # manifest coverage, label/cluster summary
python stats.py --top 20               # list the 20 largest wallets by tx count
                                        # (useful for deciding whether to raise
                                        # --max-tx-per-wallet)
python stats.py --address ckb1q...     # deep-dive: one wallet's raw pull record
                                        # (status, next_page cursor, time range, errors)
python stats.py --save-json stats.json --save-markdown stats.md
```

## Resumability (safe to Ctrl-C, safe to lose network mid-run)

The CKB Explorer public API is not always fast or reliable — long pulls will hit
read timeouts and dropped connections. The pipeline is built to survive that:

- **Per-page checkpointing.** `acquisition.pull_wallet_raw` saves progress to
  `data/raw/<address>.json` every `config.CHECKPOINT_EVERY_N_PAGES` pages (2 by
  default), and immediately on any page failure. A wallet that fails on page 30
  keeps pages 1–29 — re-running resumes from page 30, it never restarts at page 1.
- **Per-wallet time budget.** `config.MAX_SECONDS_PER_WALLET` (default 90s) caps
  how long a single call spends on one wallet before checkpointing and moving to
  the next. A pathological high-traffic wallet (e.g. an exchange hot wallet) can't
  stall the whole batch — it's marked `status: "partial"` and picked up on a later
  run or a later `pull_wallet_batch` pass.
- **Sample manifest.** `dataset.py`'s first run saves the discovered/stratified
  address sample to `data/processed/sample_manifest.json`. Every subsequent run
  of `python dataset.py` reuses that manifest instead of re-crawling blocks and
  re-sampling — pass `--force-reseed` if you actually want a fresh sample.
- **Wallets that never finish are excluded from the CSV, not silently guessed at.**
  `dataset.py` only writes rows for wallets that reached `status: "complete"` this
  run. It logs how many are still partial; just re-run the same command (no flags
  needed) until that count hits zero.
- **`infer.py` retries automatically.** A single-address lookup calls
  `pull_wallet_raw` up to 6 times in a row (each capped at `--max-seconds-per-wallet`,
  90s default) before giving up and returning a best-effort partial answer flagged
  with `note_pull_incomplete`.

Practically:

```bash
python dataset.py --n-blocks 400 --per-bucket 40
# ... network hiccups, Ctrl-C, whatever - just run it again ...
python dataset.py                      # same args not even required; resumes via the manifest
python dataset.py                      # keep re-running until "0 wallets still partial"
```

Tested without any network access via `tests/resumability_test.py`, which
covers two scenarios: (1) a page fetch failing partway through a wallet -
asserts the transactions collected before the failure are never lost, a
resumed call only fetches the remaining pages, and a call on an
already-`complete` wallet makes zero API calls; and (2) a wallet whose
in-window activity exceeds the safety cap - asserts it comes back `capped`
(never `complete`), and that raising the cap and re-running resumes from the
checkpoint instead of restarting.



This sandbox has no network access to `explorer.nervos.org`, so
`explorer_client.py`/`cell_resolver.py` are built from Explorer's published
apifox schema but haven't been round-tripped against a live response here.
Before a big collection run, sanity check:

1. `explorer_client._unwrap` assumes the standard JSON:API envelope
   (`{"data": {"attributes": {...}}}`). Run
   `python -c "import explorer_client as ec; print(ec.get_block(1))"` first.
2. `cell_resolver.decode_since` expects `since` as a raw int/hex; if your
   Explorer version returns a pre-parsed object with different key names,
   adjust the `isinstance(since_field, dict)` branch.

`tests/synthetic_smoke_test.py` fabricates Explorer-shaped JSON for six
archetypes (miner, periodic bot, batch distributor, fan-in collector, normal
human, inactive) and runs the **entire** pipeline — features → clustering →
description generation → new-address inference — against it with no network
calls. On the last run it recovered all five active archetypes as five
distinct clusters (silhouette score 0.996) and correctly assigned five
held-out check wallets to their matching clusters. Run it any time with
`python tests/synthetic_smoke_test.py`.

## Validating against the live API

This sandbox has no network access to `explorer.nervos.org`, so
`explorer_client.py`/`cell_resolver.py` are built from Explorer's published
apifox schema. Two things worth a 30-second sanity check on your machine
before a big collection run:

1. `explorer_client._unwrap` assumes the standard JSON:API envelope
   (`{"data": {"attributes": {...}}}`). Run
   `python -c "import explorer_client as ec; print(ec.get_block(1))"` first.
2. `cell_resolver.decode_since` expects `since` as a raw int/hex; if your
   Explorer version returns a pre-parsed object with different key names,
   adjust the `isinstance(since_field, dict)` branch.

## Known limitations / honest caveats

- **Wallet = address, not lock_hash.** The doc recommends canonicalizing to
  `lock_hash` so multiple address encodings of the same lock collapse to one
  entity. Swap in `address_info["lock_hash"]` as the join key if you need
  this.
- **Round-trip/cycle detection is 1-hop only.** Full `A → B → A` cycle
  detection (§15) needs a multi-wallet transaction graph; this pipeline
  approximates it with `round_trip_partner_ratio`.
- **CKB Explorer, not a node+indexer.** The doc's strong recommendation
  (§3) is a CKB full node with its built-in indexer for production-scale,
  rate-limit-free collection. Swapping `explorer_client.py` for indexer RPC
  calls (`get_transactions` by lock script) is the natural next step; the
  rest of the pipeline (resolver → features → clustering) doesn't need to
  change.
- **k is chosen automatically by silhouette score** over a search range —
  reasonable as a default, but always read the per-cluster descriptions
  before trusting the count. If two clusters look behaviourally identical,
  re-run with a narrower `--k-max`; if one cluster's description reads like
  two different things mashed together, widen it.
- **This is Phase B/C, not a validated ground-truth classifier.** Treat
  `suggested_archetype` as a strong, evidence-backed hypothesis about what a
  cluster of wallets is doing — worth investigating further, not a legal or
  security finding.
