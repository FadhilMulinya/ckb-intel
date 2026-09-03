from __future__ import annotations

"""
Automates the OBSERVABLE-FACT half of Phase 5 manual verification (tx count,
lock family, timing regularity, tx shape, since repetition, counterparty
count, block-mined count) so you review/confirm instead of reading every
field off the explorer UI by hand for each wallet. It does NOT auto-decide
verified_label -- that stays a human judgment call, same as everywhere else
in this pipeline. This script fills the checked_* columns; you still fill
verified_label / verified_notes / confidence yourself.

Reuses ckb_explorer_pull.py's fetch/retry/rate-limit machinery (same as the
rest of this pipeline) and cell_resolver.py's since/type-script decoding
directly, rather than reimplementing either.

IMPORTANT -- run --diagnose before a big batch run:
This environment has no network access to the real CKB Explorer API, so the
field-name guesses below (especially BLOCK_MINED_FIELD_CANDIDATES -- the
"Block Mined" count you found on the address overview page) could not be
confirmed against live data ahead of time. Exactly the same situation as
Phase 1's previous-outpoint field names, which turned out right, and its
lock-script field names, which turned out wrong. --diagnose fetches ONE
real address and shows you which candidate field actually matched (or
didn't), so you know whether to trust the batch output before running it
on everything.

Usage:
    # 1. ALWAYS diagnose first against one real address.
    python3 quick_verify_wallets.py --diagnose --address ckb1q...

    # 2. Batch-run against a candidates file (adds checked_* columns).
    python3 quick_verify_wallets.py --candidates ground_truth_candidates_template.csv \
        --out ground_truth_candidates_prefilled.csv --max-tx-sample 20 --workers 4
"""

import argparse
import json
import logging
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import ckb_explorer_pull as crawler
except ImportError:
    print("Could not import ckb_explorer_pull.py -- it must be in the same directory.", file=sys.stderr)
    sys.exit(2)

try:
    import cell_resolver as cr
except ImportError:
    print("Could not import cell_resolver.py -- it must be in the same directory "
          "(reused here for since/type-script decoding, same logic as Phase 1/2).", file=sys.stderr)
    sys.exit(2)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("quick_verify_wallets")

EXPLORER_ADDRESS_URL = "https://explorer.nervos.org/address/{address}"

# Candidate field names for the address-overview "Block Mined" counter you
# found in the UI. Not independently confirmed against the live API in this
# environment -- see module docstring. --diagnose reports which one (if any)
# actually matches your real data.
BLOCK_MINED_FIELD_CANDIDATES = (
    "block_mined_count", "blocks_mined", "mined_blocks_count",
    "mined_block_count", "block_count", "seal_count",
)

TX_COUNT_FIELD_CANDIDATES = ("transactions_count", "tx_count", "ckb_transactions_count")

REGISTRY = cr.load_lock_registry()


def _get_attrs(payload: Optional[dict]) -> dict:
    if not payload:
        return {}
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        return {}
    return data.get("attributes", {}) or {}


def _first_matching(attrs: dict, candidates: tuple[str, ...]) -> tuple[Optional[object], Optional[str]]:
    for key in candidates:
        if key in attrs and attrs[key] is not None:
            return attrs[key], key
    return None, None


def classify_shape(n_in: int, n_out: int) -> str:
    if n_in <= 1 and n_out <= 1:
        return "1_to_1"
    if n_in <= 1 and n_out > 1:
        return "1_to_n"
    if n_in > 1 and n_out <= 1:
        return "n_to_1"
    return "n_to_n"


def _parse_tx_detail(detail: Optional[dict]) -> Optional[tuple]:
    attrs = _get_attrs(detail)
    if not attrs:
        return None
    ts = cr._to_int(attrs.get("block_timestamp"))
    inputs = attrs.get("display_inputs") or []
    outputs = attrs.get("display_outputs") or []
    return ts, inputs, outputs


# ---------------------------------------------------------------------------
# Diagnose -- run this against ONE real address before trusting a batch run
# ---------------------------------------------------------------------------

def diagnose(address: str, max_tx_sample: int) -> None:
    log.info("fetching address detail for %s...", address)
    detail = crawler.fetch_address_detail(address)
    attrs = _get_attrs(detail)
    if not attrs:
        log.error("no address detail returned -- check the address and your network connection.")
        return

    print("\n=== Raw address-detail attributes (top-level keys) ===")
    for key in sorted(attrs.keys()):
        val = attrs[key]
        val_repr = json.dumps(val) if not isinstance(val, (dict, list)) else f"{type(val).__name__} ({len(val)} item(s))"
        print(f"  {key}: {val_repr[:100]}")

    block_mined, matched_key = _first_matching(attrs, BLOCK_MINED_FIELD_CANDIDATES)
    print(f"\n=== Block-mined field check ===")
    if matched_key:
        print(f"  MATCHED: '{matched_key}' = {block_mined}")
        print(f"  Update BLOCK_MINED_FIELD_CANDIDATES to put '{matched_key}' first if it isn't already.")
    else:
        print(f"  NO MATCH among {BLOCK_MINED_FIELD_CANDIDATES}.")
        print(f"  The 'Block Mined' counter you saw in the UI isn't under any of these keys in the "
              f"raw API response for this address -- either it's computed by the frontend from "
              f"something else, or it's under a key not in this candidate list. Compare the full "
              f"key list above against what the UI shows and tell me the real key name if you can "
              f"spot it, or we'll fall back to the block-scanning method for this field.")

    tx_count, tx_count_key = _first_matching(attrs, TX_COUNT_FIELD_CANDIDATES)
    print(f"\n=== Transaction-count field check ===")
    print(f"  {'MATCHED: ' + tx_count_key + ' = ' + str(tx_count) if tx_count_key else 'NO MATCH'}")

    print(f"\n=== Sampling up to {max_tx_sample} recent transaction(s) ===")
    n_fetched = 0
    for tx_item in crawler.fetch_address_transactions(address):
        if n_fetched >= max_tx_sample:
            break
        tx_hash = tx_item.get("attributes", {}).get("transaction_hash") or tx_item.get("id")
        if not tx_hash:
            continue
        detail_tx = crawler.fetch_transaction_detail(tx_hash)
        parsed = _parse_tx_detail(detail_tx)
        if parsed is None:
            continue
        ts, inputs, outputs = parsed
        n_fetched += 1
        if n_fetched <= 3:
            print(f"  tx {n_fetched}: ts={ts}, n_inputs={len(inputs)}, n_outputs={len(outputs)}")
            if inputs:
                since_raw = cr.extract_since_raw(inputs[0])
                print(f"    first input since_raw={since_raw!r}, decoded={cr.decode_since(since_raw)}")

    print(f"\nSampled {n_fetched} transaction(s) successfully. If this number is 0, check that "
          f"fetch_address_transactions/fetch_transaction_detail are returning data for this address "
          f"before trusting the batch run.")
    print("\nThis was diagnosis-only (no output file written). Once the field matches above look "
          "right, run the batch command from the module docstring.")


# ---------------------------------------------------------------------------
# Per-address analysis (the actual automation)
# ---------------------------------------------------------------------------

def analyze_address(address: str, max_tx_sample: int) -> dict:
    result = {
        "address": address,
        "explorer_url": EXPLORER_ADDRESS_URL.format(address=address),
        "checked_tx_count": "", "checked_lock_family": "",
        "checked_block_miner_match": "NA", "checked_has_type_script": "N",
        "checked_timestamp_regularity": "Unclear", "checked_tx_shape_pattern": "",
        "checked_since_repeated": "NA", "checked_counterparty_pattern": "",
        "suggested_verified_label": "", "suggested_confidence": "",
        "_fetch_error": "",
    }
    try:
        detail = crawler.fetch_address_detail(address)
        attrs = _get_attrs(detail)
        if not attrs:
            result["_fetch_error"] = "no address detail returned"
            return result

        tx_count, _ = _first_matching(attrs, TX_COUNT_FIELD_CANDIDATES)
        result["checked_tx_count"] = tx_count if tx_count is not None else ""

        lock_script = attrs.get("lock_script") or {}
        code_hash, hash_type = lock_script.get("code_hash"), lock_script.get("hash_type")
        result["checked_lock_family"] = cr.classify_lock_family(code_hash, hash_type, REGISTRY) if code_hash else "unknown"

        block_mined, _ = _first_matching(attrs, BLOCK_MINED_FIELD_CANDIDATES)
        if block_mined is not None:
            result["checked_block_miner_match"] = "Y" if cr._to_int(block_mined) and cr._to_int(block_mined) > 0 else "N"

        timestamps, shapes, since_values, counterparties = [], [], [], set()
        has_type_script_seen = False
        n_sampled = 0

        for tx_item in crawler.fetch_address_transactions(address):
            if n_sampled >= max_tx_sample:
                break
            tx_hash = tx_item.get("attributes", {}).get("transaction_hash") or tx_item.get("id")
            if not tx_hash:
                continue
            detail_tx = crawler.fetch_transaction_detail(tx_hash)
            parsed = _parse_tx_detail(detail_tx)
            if parsed is None:
                continue
            ts, inputs, outputs = parsed
            n_sampled += 1
            if ts is not None:
                timestamps.append(ts)
            shapes.append(classify_shape(len(inputs), len(outputs)))
            for cell in inputs:
                since_decoded = cr.decode_since(cr.extract_since_raw(cell))
                if since_decoded is not None:
                    since_values.append(since_decoded["raw_value"])
                addr = cell.get("address_hash") or cell.get("address")
                if addr and addr != address:
                    counterparties.add(addr)
            for cell in outputs:
                addr = cell.get("address_hash") or cell.get("address")
                if addr and addr != address:
                    counterparties.add(addr)
                if cr.extract_type(cell)["has_type_script"]:
                    has_type_script_seen = True

        result["checked_has_type_script"] = "Y" if has_type_script_seen else "N"

        if len(timestamps) >= 3:
            gaps = np.diff(sorted(timestamps))
            gap_mean = gaps.mean()
            if gap_mean > 0:
                gap_cv = gaps.std() / gap_mean
                result["checked_timestamp_regularity"] = "Regular" if gap_cv < 0.3 else "Irregular"

        if shapes:
            dominant, count = Counter(shapes).most_common(1)[0]
            frac = count / len(shapes)
            result["checked_tx_shape_pattern"] = dominant if frac > 0.6 else "mixed"

        if since_values:
            top_count = Counter(since_values).most_common(1)[0][1]
            result["checked_since_repeated"] = "Y" if top_count / len(since_values) > 0.5 else "N"
        elif n_sampled > 0:
            result["checked_since_repeated"] = "N"

        result["checked_counterparty_pattern"] = (
            f"{len(counterparties)} distinct counterparty(ies) across {n_sampled} sampled tx"
        )

        # A SUGGESTION only -- simple, transparent rules, never a substitute
        # for your own judgment. Deliberately conservative: defaults to
        # Unclear rather than guessing when signals are mixed or thin.
        if result["checked_block_miner_match"] == "Y":
            result["suggested_verified_label"] = "Miner"
            result["suggested_confidence"] = "Medium"
        elif n_sampled == 0:
            result["suggested_verified_label"] = "Unclear"
            result["suggested_confidence"] = "Low"
        elif (result["checked_timestamp_regularity"] == "Regular"
              and result["checked_tx_shape_pattern"] != "mixed"
              and result["checked_since_repeated"] == "Y"):
            result["suggested_verified_label"] = "Bot"
            result["suggested_confidence"] = "Medium"
        elif result["checked_timestamp_regularity"] == "Irregular":
            result["suggested_verified_label"] = "Human"
            result["suggested_confidence"] = "Low"
        else:
            result["suggested_verified_label"] = "Unclear"
            result["suggested_confidence"] = "Low"

    except Exception as e:  # noqa: BLE001 -- one bad address must not kill the whole batch
        result["_fetch_error"] = f"{type(e).__name__}: {e}"

    return result


def run_batch(addresses: list[str], max_tx_sample: int, workers: int) -> pd.DataFrame:
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(analyze_address, addr, max_tx_sample): addr for addr in addresses}
        n_done = 0
        for future in as_completed(futures):
            rows.append(future.result())
            n_done += 1
            if n_done % 10 == 0:
                log.info("  %d/%d address(es) processed...", n_done, len(addresses))
    df = pd.DataFrame(rows).set_index("address").reindex(addresses)
    n_errors = int((df["_fetch_error"] != "").sum())
    if n_errors:
        log.warning("%d/%d address(es) had a fetch error -- see _fetch_error column. These rows "
                     "still need fully manual verification.", n_errors, len(addresses))
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diagnose", action="store_true", help="Diagnose field names against one real address.")
    ap.add_argument("--address", type=str, default=None, help="Address to use with --diagnose.")
    ap.add_argument("--candidates", type=Path, default=None,
                     help="CSV with an 'address' column (e.g. ground_truth_candidates_template.csv). "
                          "Existing checked_*/verified_* columns are preserved; only blank checked_* "
                          "cells get auto-filled, so anything you've already verified by hand is untouched.")
    ap.add_argument("--out", type=Path, default=None, help="Output CSV path (required with --candidates).")
    ap.add_argument("--max-tx-sample", type=int, default=20,
                     help="Transactions sampled per address. Higher = more accurate regularity/shape "
                          "reads, more API calls. Default: 20.")
    ap.add_argument("--workers", type=int, default=4, help="Concurrent addresses processed at once.")
    args = ap.parse_args()

    if args.diagnose:
        if not args.address:
            raise SystemExit("--diagnose requires --address <ckb1q...>")
        diagnose(args.address, args.max_tx_sample)
        return

    if not args.candidates or not args.out:
        raise SystemExit("Provide --candidates and --out for a batch run, or --diagnose --address for diagnosis.")
    if not args.candidates.exists():
        raise SystemExit(f"no such file: {args.candidates}")

    existing = pd.read_csv(args.candidates, dtype=str, keep_default_na=False)
    if "address" not in existing.columns:
        raise SystemExit("--candidates file must have an 'address' column.")

    addresses = existing["address"].tolist()
    log.info("running quick verification against %d address(es) (max %d tx sampled each, %d worker(s))...",
              len(addresses), args.max_tx_sample, args.workers)
    computed = run_batch(addresses, args.max_tx_sample, args.workers)

    checked_cols = [c for c in computed.columns if c.startswith("checked_") or c.startswith("suggested_")]
    existing = existing.set_index("address")
    for col in checked_cols:
        if col not in existing.columns:
            existing[col] = ""
        # Only fill blanks -- never overwrite anything already verified by hand.
        blank_mask = existing[col].isin(["", "nan"]) | existing[col].isna()
        existing.loc[blank_mask, col] = computed.loc[existing.index[blank_mask], col].reindex(existing.index[blank_mask])

    if "_fetch_error" in computed.columns:
        existing["_fetch_error"] = computed["_fetch_error"].reindex(existing.index)

    existing = existing.reset_index()
    existing.to_csv(args.out, index=False)
    log.info("wrote %s (%d row(s))", args.out, len(existing))

    n_errors = int((existing.get("_fetch_error", pd.Series(dtype=str)) != "").sum())
    print(f"\n{len(existing)} address(es) processed, {n_errors} fetch error(s).")
    print("checked_* columns are auto-filled SUGGESTIONS from live data -- review them the same way "
          "you'd review your own manual read, especially checked_block_miner_match if --diagnose "
          "didn't find a confirmed field match. suggested_verified_label/suggested_confidence are "
          "starting points only; fill verified_label/verified_notes/confidence yourself before "
          "treating any row as final ground truth.")


if __name__ == "__main__":
    main()
