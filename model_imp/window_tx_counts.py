"""
Shows how many transactions were collected WITHIN the fixed observation
window, per wallet and in aggregate - and for wallets that AREN'T finished yet
(partial/capped), estimates how many more transactions are likely left to
pull before that wallet reaches a genuine full-window `complete` state.

Only `status == "complete"` wallets have a trustworthy "full window" count -
that's the whole reason the complete/partial/capped distinction exists (see
README's "Full-window guarantee" section). This script's main total only
counts `complete` wallets for exactly that reason.

THE REMAINING-TRANSACTIONS ESTIMATE (for partial/capped wallets) works like this:
  - We know exactly how many transactions we've collected so far, and the
    timestamp of the OLDEST one we've reached (how far back in time the pull
    has gotten).
  - We know the window's total time span (window_end_ms - window_start_ms)
    and how much of that span is still uncovered (from the oldest tx we've
    seen back to the window start).
  - Assuming the wallet's transaction RATE stays roughly the same across the
    uncovered time span as it was across the covered span, we extrapolate:
        remaining_tx ~= (tx_collected / time_covered) * time_remaining
  - This is a heuristic, not a guarantee. A wallet that was quiet for weeks
    then suddenly active (or vice versa) will make this estimate wrong in
    either direction. It's meant to answer "roughly how many more pulls do I
    need", not to be exact - the only way to get an exact number is to finish
    the pull.

Reads only from disk (data/raw/*.json) - no network calls, safe to run
anytime, including mid-collection in another terminal.

Usage:
  python window_tx_counts.py                     # full report to stdout
  python window_tx_counts.py --include-incomplete # also list the raw
                                                   # partial/capped tx-so-far
                                                   # table (in addition to the
                                                   # remaining-tx estimate,
                                                   # which is always shown)
  python window_tx_counts.py --min-tx 100         # only show wallets with at
                                                   # least this many in-window tx
  python window_tx_counts.py --save-csv out.csv   # write the per-wallet table
                                                   # (includes the estimate
                                                   # columns for incomplete wallets)
"""

import os
import json
import argparse
from datetime import datetime, timezone

import config

PAGE_SIZE = config.PAGE_SIZE


def load_raw_records():
    records = []
    if not os.path.isdir(config.RAW_DIR):
        return records
    for fname in os.listdir(config.RAW_DIR):
        if not fname.endswith(".json") or fname.endswith(".tmp"):
            continue
        path = os.path.join(config.RAW_DIR, fname)
        try:
            with open(path) as f:
                records.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def estimate_remaining(record):
    """Returns None if there isn't enough data to estimate, else a dict with
    the remaining-transactions estimate for this partial/capped wallet."""
    txs = record.get("transactions", [])
    tx_collected = len(txs)
    if tx_collected == 0:
        return None

    timestamps = [int(t["block_timestamp"]) for t in txs if t.get("block_timestamp") is not None]
    if not timestamps:
        return None

    newest_ts = max(timestamps)
    oldest_ts = min(timestamps)
    window_end_ms = record.get("window_end_ms") or newest_ts
    window_start_ms = record.get("window_start_ms")
    if window_start_ms is None:
        window_days = record.get("window_days", config.OBSERVATION_WINDOW_DAYS)
        window_start_ms = window_end_ms - window_days * 24 * 3600 * 1000

    total_window_ms = window_end_ms - window_start_ms
    time_covered_ms = max(newest_ts - oldest_ts, 0)
    time_remaining_ms = max(total_window_ms - time_covered_ms, 0)

    if time_covered_ms <= 0 or total_window_ms <= 0:
        return {"estimate_possible": False, "reason": "not enough time spread in collected data yet"}

    rate_tx_per_ms = tx_collected / time_covered_ms
    estimated_remaining_tx = rate_tx_per_ms * time_remaining_ms
    pct_time_covered = min(100.0, 100.0 * time_covered_ms / total_window_ms)

    return {
        "estimate_possible": True,
        "tx_collected": tx_collected,
        "pct_time_covered": pct_time_covered,
        "days_covered": time_covered_ms / (24 * 3600 * 1000),
        "days_remaining": time_remaining_ms / (24 * 3600 * 1000),
        "estimated_remaining_tx": estimated_remaining_tx,
        "estimated_remaining_pages": estimated_remaining_tx / PAGE_SIZE,
        "estimated_full_window_total_tx": tx_collected + estimated_remaining_tx,
    }


def build_rows(records):
    rows = []
    for r in records:
        rows.append({
            "address": r["address"],
            "status": r.get("status", "unknown"),
            "full_window": r.get("status") == "complete",
            "tx_in_window": len(r.get("transactions", [])),
            "window_days": r.get("window_days"),
            "hit_max_cap": r.get("hit_max_cap", False),
        })
    return rows


def print_remaining_estimate_section(incomplete_records):
    print(f"\nEstimated transactions remaining to finish the window (partial/capped wallets: {len(incomplete_records)})")
    print("Based on each wallet's own observed rate so far - assumes roughly steady activity across the")
    print("uncovered time span. Treat as a rough guide for how many more pulls to expect, not an exact count.")
    print("-" * 110)
    header = f"{'ADDRESS':<58} {'STATUS':<9} {'COVERED':>9} {'TX SO FAR':>10} {'EST. REMAINING':>15} {'EST. PAGES LEFT':>16}"
    print(header)
    print("-" * 110)

    total_remaining_est = 0.0
    n_estimable = 0
    for r in incomplete_records:
        est = estimate_remaining(r)
        addr = r["address"]
        status = r.get("status", "unknown")
        tx_so_far = len(r.get("transactions", []))
        if est is None:
            print(f"{addr:<58} {status:<9} {'n/a':>9} {tx_so_far:>10,} {'no data yet':>15} {'-':>16}")
            continue
        if not est["estimate_possible"]:
            print(f"{addr:<58} {status:<9} {'n/a':>9} {tx_so_far:>10,} {'unknown':>15} {'-':>16}")
            continue
        n_estimable += 1
        total_remaining_est += est["estimated_remaining_tx"]
        covered_str = f"{est['pct_time_covered']:.0f}%"
        print(f"{addr:<58} {status:<9} {covered_str:>9} {tx_so_far:>10,} "
              f"{est['estimated_remaining_tx']:>15,.0f} {est['estimated_remaining_pages']:>16,.1f}")

    print("-" * 110)
    if n_estimable:
        print(f"{'ESTIMATED TOTAL REMAINING (summed across estimable wallets)':<88} {total_remaining_est:>15,.0f}")
        print(f"{'ESTIMATED TOTAL REMAINING PAGES (at ' + str(PAGE_SIZE) + ' tx/page)':<88} "
              f"{total_remaining_est / PAGE_SIZE:>15,.1f}")
    else:
        print("Not enough data yet to estimate any of these wallets - run `python dataset.py` at least once "
              "more so each has some collected transactions to extrapolate from.")


def main():
    p = argparse.ArgumentParser(description="Show full-window transaction counts, and for partial/capped "
                                             "wallets, estimate how many more transactions remain to pull.")
    p.add_argument("--include-incomplete", action="store_true",
                   help="Also list the raw tx-so-far table for partial/capped wallets "
                        "(the remaining-tx estimate section is shown either way).")
    p.add_argument("--min-tx", type=int, default=0, help="Only show wallets with at least this many in-window tx.")
    p.add_argument("--sort", choices=["desc", "asc"], default="desc", help="Sort order by tx count.")
    p.add_argument("--save-csv", help="Write the per-wallet table (with estimate columns) to this CSV path.")
    args = p.parse_args()

    records = load_raw_records()
    if not records:
        print(f"No raw data found in {config.RAW_DIR} - run `python dataset.py` first.")
        return

    rows = build_rows(records)
    full = [r for r in rows if r["full_window"] and r["tx_in_window"] >= args.min_tx]
    incomplete_rows = [r for r in rows if not r["full_window"] and r["tx_in_window"] >= args.min_tx]
    incomplete_records = [r for r in records if r["address"] in {row["address"] for row in incomplete_rows}]

    full.sort(key=lambda r: r["tx_in_window"], reverse=(args.sort == "desc"))
    incomplete_rows.sort(key=lambda r: r["tx_in_window"], reverse=(args.sort == "desc"))
    incomplete_records.sort(key=lambda r: len(r.get("transactions", [])), reverse=(args.sort == "desc"))

    window_days = next((r["window_days"] for r in rows if r["window_days"]), config.OBSERVATION_WINDOW_DAYS)
    now = datetime.now(timezone.utc).isoformat()

    print(f"Full-window transaction counts (window = {window_days} days)  (generated {now})")
    print("=" * 78)
    print(f"\nWallets with a FULL {window_days}-day window (status=complete): {len(full)}")
    print(f"{'ADDRESS':<70} {'TX IN WINDOW':>12}")
    print("-" * 84)
    total = 0
    for r in full:
        print(f"{r['address']:<70} {r['tx_in_window']:>12,}")
        total += r["tx_in_window"]

    print("-" * 84)
    print(f"{'TOTAL (full-window wallets only)':<70} {total:>12,}")
    if full:
        print(f"{'AVERAGE per wallet':<70} {total / len(full):>12,.1f}")

    if incomplete_records:
        print_remaining_estimate_section(incomplete_records)

        if args.include_incomplete:
            print(f"\nRaw tx-so-far table for partial/capped wallets ({len(incomplete_rows)}):")
            print(f"{'ADDRESS':<70} {'TX SO FAR':>12}  STATUS")
            print("-" * 92)
            for r in incomplete_rows:
                flag = " [CAPPED]" if r["hit_max_cap"] else ""
                print(f"{r['address']:<70} {r['tx_in_window']:>12,}  {r['status']}{flag}")
    else:
        print("\nNo partial/capped wallets - every wallet on disk has a full window. Nothing left to estimate.")

    if args.save_csv:
        import csv
        fieldnames = ["address", "status", "full_window", "tx_in_window", "window_days", "hit_max_cap",
                      "estimated_remaining_tx", "estimated_remaining_pages", "pct_time_covered"]
        with open(args.save_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in full:
                out = dict(r)
                out.update({"estimated_remaining_tx": "", "estimated_remaining_pages": "", "pct_time_covered": ""})
                writer.writerow(out)
            by_address = {rec["address"]: rec for rec in incomplete_records}
            for r in incomplete_rows:
                est = estimate_remaining(by_address[r["address"]])
                out = dict(r)
                if est and est.get("estimate_possible"):
                    out["estimated_remaining_tx"] = round(est["estimated_remaining_tx"], 1)
                    out["estimated_remaining_pages"] = round(est["estimated_remaining_pages"], 2)
                    out["pct_time_covered"] = round(est["pct_time_covered"], 1)
                else:
                    out.update({"estimated_remaining_tx": "", "estimated_remaining_pages": "", "pct_time_covered": ""})
                writer.writerow(out)
        print(f"\nSaved per-wallet table -> {args.save_csv}")


if __name__ == "__main__":
    main()
