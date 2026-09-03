# Manual Verification Field Guide (Phase 5)

Use this alongside `ground_truth_candidates_template.csv` (produced by `expand_verification_template.py`). One row per address. Fill in the `checked_*` fields from what you actually observe on the explorer, then set the verdict fields last. Leave a field blank rather than guessing if the explorer doesn't show it clearly for that address — a blank is honest; a guessed value isn't.

## Fields carried over from the pipeline (don't edit — for comparison only)

| Column | What it is |
|---|---|
| `source_signal` | Why this address was selected as a candidate (e.g. which archetype score, or outlier rank) |
| `top_archetype`, `top_score`, `is_scripted` | Phase 3's rule-based scores |
| `cluster_label` | Phase 4's unsupervised cluster |
| `touches_cellbase_directly` | Phase 3's miner lower-bound signal |
| `wallet_status` | active / unused (from collection) |

## `checked_*` fields — fill from the explorer

| Column | What to enter | Where to look |
|---|---|---|
| `checked_tx_count` | Total transaction count shown on the address page | Address overview |
| `checked_first_tx_date` | Date of the earliest transaction | Address overview / bottom of tx list |
| `checked_last_tx_date` | Date of the most recent transaction | Address overview / top of tx list |
| `checked_lock_family` | `secp256k1_sighash`, `multisig`, `omnilock`, `other` — what you actually see, not what the pipeline predicted | Lock script tab |
| `checked_has_type_script` | `Y` + asset name, or `N` | Balance / cell detail — any UDT/token badge |
| `checked_timestamp_regularity` | `Regular`, `Irregular`, or `Unclear` | Compare gaps between consecutive transactions in the tx list |
| `checked_tx_shape_pattern` | Free but consistent phrasing, e.g. `always 1-in-1-out`, `N-to-1`, `1-to-N`, `mixed` | Open 3-5 individual transactions, look at input/output counts |
| `checked_since_repeated` | `Y`, `N`, or `NA` (no since field / not visible) | Transaction detail → input cell → `since` field |
| `checked_counterparty_pattern` | e.g. `many small deposits swept`, `one repeated counterparty`, `many distinct ordinary counterparties`, `single exchange/pool` | Scan the "From"/"To" addresses across several transactions |
| `checked_block_miner_match` | `Y`, `N`, or `NA` (didn't check) | Only for miner candidates — block list → open a block → "Miner" field |
| `checked_external_reference` | Name of exchange/pool if identified via a web search of the address, else blank | Web search `"<address>" exchange` or similar |
| `confidence` | `High`, `Medium`, `Low` | Your own judgment call on the verdict below |

## Verdict fields

| Column | Valid values |
|---|---|
| `verified_label` | `Human`, `Bot`, `Miner`, `Exchange`, `Inactive`, `Unclear` |
| `verified_notes` | Anything not captured above — free text |
| `verified_by` | Your name/initials |
| `verified_date` | Date you did the check |

Use `Unclear` rather than forcing a guess — an honest `Unclear` is more useful ground truth than a confident-looking wrong label, and Phase 6 can simply exclude `Unclear` rows from training/validation.

## Worked examples

**Bot candidate, confirmed:**
```
checked_tx_count: 214
checked_timestamp_regularity: Regular
checked_tx_shape_pattern: always 1-in-1-out
checked_since_repeated: Y
checked_counterparty_pattern: one repeated counterparty
confidence: High
verified_label: Bot
verified_notes: fires roughly every 3600s, same since value across 40+ sampled tx
```

**Bot candidate, disconfirmed (this is exactly why stratified sampling matters):**
```
checked_tx_count: 18
checked_timestamp_regularity: Irregular
checked_tx_shape_pattern: mixed
checked_since_repeated: N
confidence: Medium
verified_label: Human
verified_notes: PERIODIC_EXECUTION score was 0.71 but real activity looks like a person paying rent-like recurring transfers to 2-3 named counterparties, not a script
```

**Miner candidate:**
```
checked_block_miner_match: Y
checked_counterparty_pattern: single exchange/pool
checked_external_reference: F2Pool
confidence: High
verified_label: Miner
verified_notes: matched as block Miner field on 6 separate blocks
```
