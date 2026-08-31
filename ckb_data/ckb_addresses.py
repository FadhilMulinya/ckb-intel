from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

try:
    import ckb_explorer_pull as crawler
except ImportError:
    print(
        "Could not import ckb_explorer_pull.py -- it must be in the same "
        "directory as this script (or on PYTHONPATH). This reuses its "
        "fetch_block_transactions/fetch_transaction_detail rather than "
        "reimplementing the HTTP/retry/rate-limit handling from scratch.",
        file=sys.stderr,
    )
    sys.exit(2)


def load_existing(output_path: Path) -> set[str]:
    if not output_path.exists():
        return set()
    seen = set()
    for line in output_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            seen.add(line)
    return seen


def scattered_block_numbers(latest_block: int, lookback: int, rng: random.Random) -> "Iterator[int]":
    lo = max(0, latest_block - lookback)
    hi = latest_block
    block_pool = list(range(lo, hi + 1))
    rng.shuffle(block_pool)
    for b in block_pool:
        yield b


def discover_incremental(target: int, block_lookback: int, output_path: Path,
                          already_seen: set[str], seed: int) -> int:
    rng = random.Random(seed)

    latest = crawler.fetch_latest_block_number()
    if latest is None:
        raise SystemExit("Could not fetch the current block tip from CKB Explorer -- "
                          "check connectivity.")

    n_new = 0
    n_seen_total = len(already_seen)
    scanned_blocks = 0

    
    with open(output_path, "a") as f:
        for block_num in scattered_block_numbers(latest, block_lookback, rng):
            if n_seen_total >= target:
                break
            scanned_blocks += 1
            print(f"  scanning block {block_num} "
                  f"({n_seen_total}/{target} addresses so far, "
                  f"{scanned_blocks} blocks scanned)")

            for tx_item in crawler.fetch_block_transactions(block_num):
                if n_seen_total >= target:
                    break
                attrs = tx_item.get("attributes", {})
                tx_hash = attrs.get("transaction_hash") or tx_item.get("id")
                if not tx_hash:
                    continue

                detail = crawler.fetch_transaction_detail(tx_hash)
                if not detail:
                    continue
                data = detail.get("data")
                if isinstance(data, list):
                    data = data[0] if data else None
                if not data:
                    continue
                tattrs = data.get("attributes", {})
                cells = (tattrs.get("display_inputs") or []) + (tattrs.get("display_outputs") or [])

                for cell in cells:
                    if n_seen_total >= target:
                        break
                    addr = crawler._extract_address(cell)
                    if not addr or addr in already_seen:
                        continue
                    already_seen.add(addr)
                    n_seen_total += 1
                    n_new += 1
                    f.write(addr + "\n")
                    f.flush()  

    return n_new


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", type=int, required=True,
                    help="Total number of unique addresses wanted in --output "
                         "(counts what's already there if the file exists)")
    p.add_argument("--output", type=Path, required=True, help="Output text file, one address per line")
    p.add_argument("--block-lookback", type=int, default=2_000_000,
                    help="How far back from the current tip to sample blocks from. "
                         "Default: 2,000,000 blocks (~a few years at CKB's ~8s block time).")
    p.add_argument("--seed", type=int, default=None,
                    help="Random seed for block sampling order (default: unseeded/random each run)")
    args = p.parse_args()

    already_seen = load_existing(args.output)
    if already_seen:
        print(f"{args.output} already has {len(already_seen)} address(es) -- resuming toward "
              f"--target {args.target}")
        if len(already_seen) >= args.target:
            print("Target already met. Nothing to do.")
            return

    seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    n_new = discover_incremental(args.target, args.block_lookback, args.output, already_seen, seed)

    print(f"\nAdded {n_new} new address(es). {args.output} now has {len(already_seen)} total.")
    print(f"\nNext: python3 collect_target_wallets.py --db ./ckb_data/ckb_explorer.sqlite "
          f"--addresses {args.output}")


if __name__ == "__main__":
    main()
