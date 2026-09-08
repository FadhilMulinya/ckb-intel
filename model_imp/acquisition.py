import os
import json
import time
import random
import logging
from collections import defaultdict, Counter
from datetime import datetime, timezone

import config
import explorer_client as ec

logger = logging.getLogger("ckb_wallet_intel.acquisition")


def _bucket_for(count: int):
    for lo, hi in config.ACTIVITY_BUCKETS:
        if lo <= count <= hi:
            return f"{lo}-{hi}"
    return "unknown"


def discover_seed_addresses(n_blocks: int = 400, max_addresses: int = 3000):
    """Crawl recent blocks, collect candidate lock addresses + miner addresses.

    Returns: (candidate_addresses: set[str], miner_addresses: set[str])
    """
    tip = ec.get_tip_block_number()
    candidates = set()
    miners = set()
    blocks_seen = 0

    num = tip
    while blocks_seen < n_blocks and num > 0 and len(candidates) < max_addresses:
        try:
            block = ec.get_block(num)
        except RuntimeError as exc:
            logger.warning("block %s failed: %s", num, exc)
            num -= 1
            continue
        miner_hash = block.get("miner_hash")
        if miner_hash:
            miners.add(miner_hash)
            candidates.add(miner_hash)

        block_hash = block.get("block_hash")
        try:
            txs = list(_iter_block_transactions(block_hash))
        except RuntimeError as exc:
            logger.warning("block_transactions %s failed: %s", num, exc)
            txs = []

        for tx in txs:
            for io in (tx.get("display_inputs") or []):
                if io.get("address_hash"):
                    candidates.add(io["address_hash"])
                if io.get("from_cellbase"):
                    pass
            for io in (tx.get("display_outputs") or []):
                if io.get("address_hash"):
                    candidates.add(io["address_hash"])

        blocks_seen += 1
        num -= 1

    logger.info("Seed discovery: scanned %d blocks, %d candidate addresses, %d miner addresses",
                blocks_seen, len(candidates), len(miners))
    return candidates, miners


def _iter_block_transactions(block_hash, page_size=100):
    page = 1
    while True:
        payload = ec._get(f"/block_transactions/{block_hash}", params={"page": page, "page_size": page_size})
        items, meta = ec._unwrap(payload)
        if not items:
            return
        for it in items:
            yield it
        total = (meta or {}).get("total", 0)
        if page * page_size >= total:
            return
        page += 1


def stratify_by_activity(candidates, per_bucket=None, seed=42):
    """Query each candidate's total tx count (cheap: page_size=1) and bucket it,
    then randomly sample up to `per_bucket` addresses per bucket."""
    per_bucket = per_bucket or config.TARGET_WALLETS_PER_BUCKET
    rng = random.Random(seed)
    candidates = list(candidates)
    rng.shuffle(candidates)

    buckets = defaultdict(list)
    for addr in candidates:
        try:
            payload = ec._get(f"/address_transactions/{addr}", params={"page": 1, "page_size": 1})
            _, meta = ec._unwrap(payload)
            total = (meta or {}).get("total", 0)
        except RuntimeError:
            continue
        b = _bucket_for(total)
        if len(buckets[b]) < per_bucket:
            buckets[b].append((addr, total))
        if all(len(v) >= per_bucket for v in buckets.values()) and len(buckets) == len(config.ACTIVITY_BUCKETS):
            break

    logger.info("Activity buckets: %s", {k: len(v) for k, v in buckets.items()})
    sample = [addr for lst in buckets.values() for addr, _ in lst]
    return sample, buckets


def _within_window(block_timestamp_ms, window_start_ms):
    return int(block_timestamp_ms) >= window_start_ms


def _cache_path(address):
    return os.path.join(config.RAW_DIR, f"{address}.json")


def _reclassify_stale_cache(record):
    """Self-healing for records written by an OLDER version of this pipeline,
    before status="capped" existed as distinct from status="complete".

    The old code set status="complete" whenever it hit MAX_TX_PER_WALLET or
    MAX_PAGES_PER_WALLET, with no way to tell "genuinely finished" apart from
    "safety valve fired mid-window". We CAN tell them apart after the fact:
    if hit_max_cap is True and we never actually saw a transaction older than
    the window (saw_older_than_window is False), the window boundary was never
    proven - that record should be "capped", not "complete". Rewritten to disk
    so this is a one-time fix per wallet, not a per-call check forever.
    """
    if record is None:
        return record
    if record.get("status") == "complete" and record.get("hit_max_cap") and not record.get("saw_older_than_window"):
        logger.warning(
            "%s: reclassifying stale cache from an older pipeline version - it was marked "
            "'complete' but actually hit a safety cap without proving full window coverage. "
            "Correcting to status='capped' (excluded from training data; raise "
            "--max-tx-per-wallet / --max-pages-per-wallet and re-run to get its full month).",
            record.get("address"),
        )
        record["status"] = "capped"
        _save_cache(record)
    return record


def _load_cache(address):
    path = _cache_path(address)
    if os.path.exists(path):
        with open(path) as f:
            record = json.load(f)
        return _reclassify_stale_cache(record)
    return None


def _save_cache(record):
    path = _cache_path(record["address"])
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(record, f)
    os.replace(tmp_path, path)  


def pull_wallet_raw(address: str, window_days: int = None, force: bool = False,
                     max_seconds: int = None):
    """Pull all transactions for `address` in the fixed observation window,
    checkpointing to data/raw/<address>.json after every few pages.

    Resumable: if a previous run left this wallet at status="partial" (network
    failure, time budget exceeded, Ctrl-C, ...), this call picks up from the
    last saved page instead of starting over. Call again with the same
    arguments as many times as needed; each call only does the remaining work.
    """
    window_days = window_days or config.OBSERVATION_WINDOW_DAYS
    max_seconds = max_seconds or config.MAX_SECONDS_PER_WALLET
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - window_days * 24 * 3600 * 1000

    cached = None if force else _load_cache(address)
    if cached and cached.get("status") == "complete":
        return cached

    if cached and cached.get("status") in ("partial", "capped") and not force:
        record = cached
        record["window_end_ms"] = now_ms  # keep the window end fresh across resumed runs
        next_page = record.get("next_page", 1)
        txs_in_window = record.get("transactions", [])
        listing_seen = record.get("listing_seen_before_cutoff", 0)
        logger.info("Resuming %s from page %d (%d tx already collected, previous status=%s)",
                    address, next_page, len(txs_in_window), cached.get("status"))
    else:
        record = {
            "address": address, "window_days": window_days,
            "window_start_ms": window_start_ms, "window_end_ms": now_ms,
            "address_info": None, "transactions": [],
            "listing_seen_before_cutoff": 0, "hit_max_cap": False,
            "saw_older_than_window": False, "status": "partial", "next_page": 1,
            "last_error": None,
        }
        next_page = 1
        txs_in_window = []
        listing_seen = 0

    if record.get("address_info") is None:
        try:
            record["address_info"] = ec.get_address_info(address)
        except RuntimeError as exc:
            logger.warning("address info failed for %s (continuing without it): %s", address, exc)

    start_time = time.time()
    pages_fetched_this_call = 0
    window_complete = False   
    capped = False           
    error = None

    while True:
        if listing_seen >= config.MAX_TX_PER_WALLET:
            capped = True
            logger.warning(
                "%s hit MAX_TX_PER_WALLET (%d) while still inside the %d-day window - "
                "this wallet's true in-window activity may exceed the safety cap. "
                "Raise config.MAX_TX_PER_WALLET and re-run if you need its full month.",
                address, config.MAX_TX_PER_WALLET, window_days,
            )
            break
        if next_page > config.MAX_PAGES_PER_WALLET:
            capped = True
            logger.warning("%s hit MAX_PAGES_PER_WALLET (%d) while still inside the window - "
                            "raise config.MAX_PAGES_PER_WALLET and re-run for full coverage.",
                            address, config.MAX_PAGES_PER_WALLET)
            break
        if time.time() - start_time > max_seconds:
            logger.info("%s hit per-call time budget (%ds); checkpointing and moving on "
                        "(resumable - not truncated, just needs another run)", address, max_seconds)
            break

        try:
            items, total = ec.get_address_transactions_page(address, next_page)
        except RuntimeError as exc:
            error = str(exc)
            logger.warning("Giving up on page %d for %s this run (will resume next run): %s",
                            next_page, address, exc)
            break

        if not items:
            window_complete = True
            break

        stop = False
        for tx in items:
            listing_seen += 1
            ts = tx.get("block_timestamp")
            if ts is None:
                continue
            if _within_window(ts, window_start_ms):
                txs_in_window.append(tx)
            else:
                record["saw_older_than_window"] = True
                stop = True
                break  

        next_page += 1
        pages_fetched_this_call += 1

        if stop:
            window_complete = True  
            break
        if (next_page - 1) * config.PAGE_SIZE >= total:
            window_complete = True
            break

        if pages_fetched_this_call % config.CHECKPOINT_EVERY_N_PAGES == 0:
            record.update({"transactions": txs_in_window, "listing_seen_before_cutoff": listing_seen,
                            "next_page": next_page, "status": "partial"})
            _save_cache(record)

    if window_complete:
        status = "complete"
    elif capped:
        status = "capped"   
    else:
        status = "partial"  

    record.update({
        "transactions": txs_in_window,
        "listing_seen_before_cutoff": listing_seen,
        "next_page": next_page,
        "status": status,
        "hit_max_cap": capped,
        "last_error": error,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_cache(record)
    return record


def pull_wallet_batch(addresses, force=False, max_seconds_per_wallet=None):
    """Pull every address, resumable at the per-wallet AND per-page level.
    Never raises for an individual wallet's network failure - a wallet that
    doesn't finish this call is left `status="partial"` (network/time budget -
    resumable) or `status="capped"` (safety valve fired inside the window -
    raise config.MAX_TX_PER_WALLET/MAX_PAGES_PER_WALLET, then re-run) on disk
    and picked up automatically the next time this function (or dataset.py) runs."""
    out = []
    n_complete = n_partial = n_capped = n_error = 0
    for i, addr in enumerate(addresses):
        try:
            rec = pull_wallet_raw(addr, force=force, max_seconds=max_seconds_per_wallet)
            out.append(rec)
            if rec["status"] == "complete":
                n_complete += 1
            elif rec["status"] == "capped":
                n_capped += 1
            else:
                n_partial += 1
        except Exception as exc:  
            logger.warning("Unexpected failure pulling %s: %s", addr, exc)
            n_error += 1
        if (i + 1) % 10 == 0 or (i + 1) == len(addresses):
            logger.info("Progress: %d/%d wallets attempted this run "
                        "(%d complete, %d partial, %d capped, %d errored)",
                        i + 1, len(addresses), n_complete, n_partial, n_capped, n_error)
    return out


def save_sample_manifest(sample, miners, buckets_summary=None):
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample": sample,
        "miners": list(miners),
        "buckets_summary": buckets_summary or {},
    }
    with open(config.SAMPLE_MANIFEST_PATH, "w") as f:
        json.dump(manifest, f)
    return manifest


def load_sample_manifest():
    if os.path.exists(config.SAMPLE_MANIFEST_PATH):
        with open(config.SAMPLE_MANIFEST_PATH) as f:
            return json.load(f)
    return None


def wallet_pull_status_summary(addresses):
    """Quick disk-only check (no network) of how many sampled wallets are
    already complete/partial/capped/not-started, for progress reporting before a run."""
    complete = partial = capped = missing = 0
    for addr in addresses:
        cached = _load_cache(addr)
        if cached is None:
            missing += 1
        elif cached.get("status") == "complete":
            complete += 1
        elif cached.get("status") == "capped":
            capped += 1
        else:
            partial += 1
    return {"complete": complete, "partial": partial, "capped": capped, "not_started": missing, "total": len(addresses)}
