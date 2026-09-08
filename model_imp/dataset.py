import logging
import pandas as pd

import config
import acquisition
import features as feat_mod
import labeling
import explorer_client as ec

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ckb_wallet_intel.dataset")


def build_dataset(n_blocks: int = 400, per_bucket: int = None, force_refresh: bool = False,
                   inactive_quota: int = 20, resume: bool = True, max_seconds_per_wallet: int = None):
    per_bucket = per_bucket or config.TARGET_WALLETS_PER_BUCKET

    manifest = acquisition.load_sample_manifest() if resume else None
    if manifest:
        logger.info("Resuming from existing sample manifest (%s, created %s) - %d wallets sampled. "
                     "Use --force-reseed to discover a fresh sample instead.",
                     config.SAMPLE_MANIFEST_PATH, manifest["created_at"], len(manifest["sample"]))
        sample = manifest["sample"]
        miners = set(manifest["miners"])
    else:
        logger.info("Discovering seed addresses from the last %d blocks...", n_blocks)
        candidates, miners = acquisition.discover_seed_addresses(n_blocks=n_blocks)

        logger.info("Stratifying %d candidates by activity level...", len(candidates))
        sample, buckets = acquisition.stratify_by_activity(candidates, per_bucket=per_bucket)

        zero_tx_bucket = buckets.get(f"{config.ACTIVITY_BUCKETS[0][0]}-{config.ACTIVITY_BUCKETS[0][1]}", [])
        inactive_candidates = [a for a in candidates if a not in sample][:inactive_quota]
        sample = list(dict.fromkeys(sample + inactive_candidates))

        acquisition.save_sample_manifest(sample, miners, {k: len(v) for k, v in buckets.items()})
        logger.info("Saved sample manifest -> %s (%d wallets). Re-running this command will "
                     "resume from here instead of re-sampling.", config.SAMPLE_MANIFEST_PATH, len(sample))

    status_before = acquisition.wallet_pull_status_summary(sample)
    logger.info("Pull status before this run: %s", status_before)

    logger.info("Pulling raw transaction windows for %d wallets (resumable per-wallet/per-page)...", len(sample))
    raw_records = acquisition.pull_wallet_batch(sample, force=force_refresh, max_seconds_per_wallet=max_seconds_per_wallet)

    complete_records = [r for r in raw_records if r["status"] == "complete"]
    partial_records = [r for r in raw_records if r["status"] == "partial"]
    capped_records = [r for r in raw_records if r["status"] == "capped"]
    logger.info("This run: %d wallets reached status=complete, %d still partial (network/time-budget - "
                "just re-run to continue), %d capped (safety valve fired inside the window).",
                len(complete_records), len(partial_records), len(capped_records))
    if capped_records:
        logger.warning(
            "%d wallets hit MAX_TX_PER_WALLET/MAX_PAGES_PER_WALLET before their %d-day window was fully "
            "covered - their data would be a TRUNCATED slice of the month, not the full window, so they "
            "are excluded rather than silently under-counted. If this is expected (e.g. exchange hot "
            "wallets), raise --max-tx-per-wallet / --max-pages-per-wallet and re-run; the same command "
            "resumes these wallets from where they stopped instead of re-fetching. Affected addresses: %s",
            len(capped_records), config.OBSERVATION_WINDOW_DAYS,
            [r["address"] for r in capped_records][:10],
        )

    rows = []
    for rec in complete_records:
        address = rec["address"]
        addr_info = rec.get("address_info")
        is_miner = address in miners
        try:
            feat, meta = feat_mod.compute_wallet_features(rec, address_info=addr_info, is_known_miner_address=is_miner)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Feature computation failed for %s: %s", address, exc)
            continue
        label_info = labeling.label_dataframe_row(feat, meta)
        row = {"address": address}
        row.update(feat)
        row.update(meta)
        row.update(label_info)  
                                 
        rows.append(row)

    df = pd.DataFrame(rows)
    out_path = f"{config.PROCESSED_DIR}/wallet_dataset.csv"
    df.to_csv(out_path, index=False)
    logger.info("Wrote %d wallet rows (status=complete, full-window only) to %s", len(df), out_path)
    if partial_records:
        logger.info("%d wallets are still mid-pull (network/time-budget) and were excluded from this CSV - "
                     "re-run `python dataset.py` (same args) to continue them; already-collected pages are "
                     "never re-fetched.", len(partial_records))
    if len(df):
        logger.info("Label distribution:\n%s", df["label"].value_counts().to_string())
    return df


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Build the CKB wallet behaviour dataset from CKB Explorer. "
                                             "Safe to Ctrl-C and re-run - resumes automatically.")
    p.add_argument("--n-blocks", type=int, default=400, help="How many recent blocks to crawl for seed addresses "
                                                               "(only used on first run / --force-reseed).")
    p.add_argument("--per-bucket", type=int, default=config.TARGET_WALLETS_PER_BUCKET,
                   help="Max wallets sampled per activity bucket (only used on first run / --force-reseed).")
    p.add_argument("--force-refresh", action="store_true",
                   help="Ignore ALL cached raw JSON (even status=complete) and re-pull from API.")
    p.add_argument("--force-reseed", action="store_true",
                   help="Ignore the saved sample manifest and re-run block discovery + stratified sampling.")
    p.add_argument("--max-seconds-per-wallet", type=int, default=config.MAX_SECONDS_PER_WALLET,
                   help="Give up on a wallet after this many seconds THIS run and checkpoint it as partial.")
    p.add_argument("--max-tx-per-wallet", type=int, default=config.MAX_TX_PER_WALLET,
                   help="Safety valve: if a wallet's in-window tx count exceeds this, it's marked "
                        "'capped' (excluded from the CSV) instead of silently truncated. Raise this if "
                        "you see capped wallets in the log and want their full month.")
    p.add_argument("--max-pages-per-wallet", type=int, default=config.MAX_PAGES_PER_WALLET,
                   help="Same idea as --max-tx-per-wallet but counted in API pages, in case the API "
                        "ever returns fewer than PAGE_SIZE items per page.")
    args = p.parse_args()
    config.MAX_TX_PER_WALLET = args.max_tx_per_wallet
    config.MAX_PAGES_PER_WALLET = args.max_pages_per_wallet
    build_dataset(n_blocks=args.n_blocks, per_bucket=args.per_bucket, force_refresh=args.force_refresh,
                  resume=not args.force_reseed, max_seconds_per_wallet=args.max_seconds_per_wallet)
