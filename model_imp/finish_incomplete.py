import argparse
import logging

import config
import acquisition
from stats import load_raw_records

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("ckb_wallet_intel.finish_incomplete")


def find_incomplete_addresses(only=None):
    records = load_raw_records()
    statuses = {"partial", "capped"} if only is None else {only}
    matches = [r for r in records if r.get("status") in statuses]
    return [r["address"] for r in matches], {
        r["address"]: len(r.get("transactions", [])) for r in matches
    }


def status_snapshot(addresses):
    """Re-reads current on-disk status for exactly these addresses (cheap, disk-only)."""
    records = load_raw_records()
    by_addr = {r["address"]: r for r in records}
    counts = {"complete": 0, "partial": 0, "capped": 0, "missing": 0}
    still_incomplete = []
    for addr in addresses:
        rec = by_addr.get(addr)
        if rec is None:
            counts["missing"] += 1
            continue
        status = rec.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
        if status != "complete":
            still_incomplete.append(addr)
    return counts, still_incomplete


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=["partial", "capped"], default=None,
                   help="Restrict to just this status instead of both partial and capped.")
    p.add_argument("--address", help="Only process this one address (must already be partial/capped on disk).")
    p.add_argument("--max-seconds-per-wallet", type=int, default=config.MAX_SECONDS_PER_WALLET,
                   help="Per-wallet, per-pass time budget before checkpointing and moving to the next wallet.")
    p.add_argument("--max-tx-per-wallet", type=int, default=config.MAX_TX_PER_WALLET,
                   help="Raise this BEFORE running if you have capped wallets you actually want to finish.")
    p.add_argument("--max-pages-per-wallet", type=int, default=config.MAX_PAGES_PER_WALLET)
    p.add_argument("--max-passes", type=int, default=1,
                   help="Sweep the remaining (still-incomplete) list this many times in one invocation, "
                        "instead of you having to re-run the command manually between passes.")
    args = p.parse_args()

    config.MAX_TX_PER_WALLET = args.max_tx_per_wallet
    config.MAX_PAGES_PER_WALLET = args.max_pages_per_wallet

    if args.address:
        addresses = [args.address]
        _, tx_so_far = find_incomplete_addresses()
        if args.address not in tx_so_far:
            print(f"Note: {args.address} was not found as partial/capped on disk (it may already be "
                  f"complete, or was never pulled). Attempting it anyway.")
    else:
        addresses, tx_so_far = find_incomplete_addresses(only=args.only)

    if not addresses:
        scope = args.only or "partial/capped"
        print(f"No {scope} wallets found on disk - nothing to do.")
        return

    print(f"Targeting {len(addresses)} wallet(s) currently {args.only or 'partial/capped'}.")
    print(f"Settings: max_seconds_per_wallet={args.max_seconds_per_wallet}  "
          f"max_tx_per_wallet={config.MAX_TX_PER_WALLET}  max_pages_per_wallet={config.MAX_PAGES_PER_WALLET}\n")

    remaining = addresses
    for pass_num in range(1, args.max_passes + 1):
        if args.max_passes > 1:
            print(f"--- Pass {pass_num}/{args.max_passes} ({len(remaining)} wallet(s) targeted) ---")
        acquisition.pull_wallet_batch(remaining, max_seconds_per_wallet=args.max_seconds_per_wallet)
        counts, remaining = status_snapshot(addresses)
        print(f"After pass {pass_num}: {counts['complete']}/{len(addresses)} complete, "
              f"{counts.get('partial', 0)} partial, {counts.get('capped', 0)} capped remaining")
        if not remaining:
            break

    print()
    if remaining:
        counts, _ = status_snapshot(addresses)
        print(f"{len(remaining)} wallet(s) still not complete. Re-run this same command to continue - "
              f"already-collected pages are never re-fetched.")
        if counts.get("capped", 0):
            print(f"{counts['capped']} of those are still 'capped' - raise --max-tx-per-wallet / "
                  f"--max-pages-per-wallet further if you need their full month.")
    else:
        print(f"All {len(addresses)} targeted wallet(s) are now complete.")
        print("Run `python dataset.py` to rebuild wallet_dataset.csv including them, "
              "then `python cluster_model.py` to re-cluster.")


if __name__ == "__main__":
    main()
