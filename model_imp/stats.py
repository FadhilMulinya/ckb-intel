import os
import sys
import json
import argparse
from collections import Counter
from datetime import datetime, timezone

import numpy as np

import config




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
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  ! skipping unreadable raw file {fname}: {exc}", file=sys.stderr)
    return records


def load_manifest():
    return acquisition_load_sample_manifest_safe()


def acquisition_load_sample_manifest_safe():
    if os.path.exists(config.SAMPLE_MANIFEST_PATH):
        with open(config.SAMPLE_MANIFEST_PATH) as f:
            return json.load(f)
    return None


def load_processed_dataset():
    path = f"{config.PROCESSED_DIR}/wallet_dataset.csv"
    if not os.path.exists(path):
        return None
    import pandas as pd
    return pd.read_csv(path)


def load_cluster_profiles():
    path = f"{config.MODELS_DIR}/cluster_profiles.json"
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)




def _pct(x, n):
    return f"{100 * x / n:.1f}%" if n else "n/a"


def _percentiles(values, ps=(0, 25, 50, 75, 90, 99, 100)):
    if not values:
        return {f"p{p}": None for p in ps}
    arr = np.array(values)
    return {f"p{p}": float(np.percentile(arr, p)) for p in ps}


ACTIVITY_HISTOGRAM_BUCKETS = [
    (0, 0, "0 (inactive)"), (1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"),
    (201, 1000, "201-1,000"), (1001, 5000, "1,001-5,000"), (5001, 10 ** 12, "5,001+"),
]


def _bucket_label(n):
    for lo, hi, label in ACTIVITY_HISTOGRAM_BUCKETS:
        if lo <= n <= hi:
            return label
    return "unknown"


def summarize_raw(records):
    n = len(records)
    status_counts = Counter(r.get("status", "unknown") for r in records)
    tx_counts = [len(r.get("transactions", [])) for r in records]
    listing_seen = [r.get("listing_seen_before_cutoff", len(r.get("transactions", []))) for r in records]
    hit_cap = [r for r in records if r.get("hit_max_cap")]
    errored = [r for r in records if r.get("last_error")]
    missing_address_info = [r for r in records if r.get("address_info") is None]
    saw_boundary = [r for r in records if r.get("saw_older_than_window")]
    window_days_seen = Counter(r.get("window_days") for r in records)

    activity_hist = Counter(_bucket_label(c) for c in tx_counts)
    total_tx = sum(tx_counts)

    error_messages = Counter()
    for r in errored:
        msg = r.get("last_error") or ""
        # collapse to a short signature so similar timeouts group together
        sig = msg.split(":")[0][:80]
        error_messages[sig] += 1

    largest = sorted(records, key=lambda r: len(r.get("transactions", [])), reverse=True)

    return {
        "n_wallets_on_disk": n,
        "status_counts": dict(status_counts),
        "status_pct": {k: _pct(v, n) for k, v in status_counts.items()},
        "total_transactions_collected": total_tx,
        "tx_per_wallet_percentiles": _percentiles(tx_counts),
        "tx_per_wallet_mean": float(np.mean(tx_counts)) if tx_counts else 0.0,
        "activity_histogram": dict(activity_hist),
        "wallets_hit_cap": len(hit_cap),
        "wallets_hit_cap_pct": _pct(len(hit_cap), n),
        "wallets_with_errors": len(errored),
        "error_signatures": dict(error_messages.most_common(10)),
        "wallets_missing_address_info": len(missing_address_info),
        "wallets_that_reached_window_boundary": len(saw_boundary),
        "window_days_seen": dict(window_days_seen),
        "largest_wallets": [
            {"address": r["address"], "status": r.get("status"), "tx_collected": len(r.get("transactions", [])),
             "hit_max_cap": r.get("hit_max_cap", False)}
            for r in largest[:20]
        ],
        "capped_addresses": [r["address"] for r in hit_cap],
        "partial_addresses": [r["address"] for r in records if r.get("status") == "partial"],
        "errored_addresses": [r["address"] for r in errored],
    }


def summarize_manifest(manifest, raw_records):
    if manifest is None:
        return None
    sample = manifest.get("sample", [])
    miners = set(manifest.get("miners", []))
    by_address = {r["address"]: r for r in raw_records}
    pulled = [a for a in sample if a in by_address]
    not_started = [a for a in sample if a not in by_address]
    miners_pulled = [a for a in sample if a in miners and a in by_address]
    miners_complete = [a for a in miners_pulled if by_address[a].get("status") == "complete"]

    return {
        "created_at": manifest.get("created_at"),
        "sample_size": len(sample),
        "pulled_at_all": len(pulled),
        "not_started": len(not_started),
        "not_started_addresses": not_started[:20],
        "buckets_summary": manifest.get("buckets_summary", {}),
        "known_miner_addresses_in_sample": len(miners),
        "known_miner_addresses_pulled": len(miners_pulled),
        "known_miner_addresses_complete": len(miners_complete),
    }


def summarize_processed(df):
    if df is None or len(df) == 0:
        return None
    out = {
        "n_wallets_in_dataset": len(df),
        "evidence_state_counts": df["evidence_state"].value_counts().to_dict() if "evidence_state" in df else {},
        "label_counts": df["label"].value_counts().to_dict() if "label" in df else {},
        "is_inactive_count": int(df["is_inactive"].sum()) if "is_inactive" in df else None,
        "known_miner_flag_count": int(df["is_known_miner_address"].sum()) if "is_known_miner_address" in df else None,
    }
    if "transactions_observed" in df:
        out["transactions_observed_percentiles"] = _percentiles(df["transactions_observed"].tolist())
    return out


def summarize_clusters(profiles):
    if not profiles:
        return None
    return {
        cid: {
            "n_wallets": p["n_wallets"],
            "suggested_archetype": p["suggested_archetype"],
            "purity": p["purity"],
        }
        for cid, p in profiles.items()
    }




def format_report(raw_stats, manifest_stats, processed_stats, cluster_stats, top_n=10):
    lines = []
    w = lines.append
    now = datetime.now(timezone.utc).isoformat()
    w(f"CKB Wallet Intel - Raw Data Statistics  (generated {now})")
    w("=" * 70)

    w("\n## Pull status (data/raw/*.json)")
    n = raw_stats["n_wallets_on_disk"]
    w(f"  Wallets on disk:        {n}")
    for status in ("complete", "partial", "capped"):
        c = raw_stats["status_counts"].get(status, 0)
        w(f"    {status:<10} {c:>5}  ({raw_stats['status_pct'].get(status, '0.0%')})")
    other = {k: v for k, v in raw_stats["status_counts"].items() if k not in ("complete", "partial", "capped")}
    if other:
        w(f"    other statuses: {other}")

    w("\n## Transaction volume")
    w(f"  Total transactions collected (in-window, across all wallets): {raw_stats['total_transactions_collected']:,}")
    pct = raw_stats["tx_per_wallet_percentiles"]
    w(f"  Per-wallet tx count:  min={pct['p0']:.0f}  p25={pct['p25']:.0f}  median={pct['p50']:.0f}  "
      f"p75={pct['p75']:.0f}  p90={pct['p90']:.0f}  p99={pct['p99']:.0f}  max={pct['p100']:.0f}"
      if pct['p0'] is not None else "  (no wallets pulled yet)")
    w(f"  Mean tx per wallet:   {raw_stats['tx_per_wallet_mean']:.1f}")

    w("\n## Activity histogram (in-window tx count)")
    for _, _, label in ACTIVITY_HISTOGRAM_BUCKETS:
        count = raw_stats["activity_histogram"].get(label, 0)
        bar = "#" * min(50, count)
        w(f"  {label:<14} {count:>4}  {bar}")

    w("\n## Data quality flags")
    w(f"  Wallets that hit a safety cap (status=capped, TRUNCATED window):  "
      f"{raw_stats['wallets_hit_cap']} ({raw_stats['wallets_hit_cap_pct']})")
    if raw_stats["capped_addresses"]:
        w(f"    -> {raw_stats['capped_addresses'][:10]}")
    w(f"  Wallets with a recorded last_error (still partial):               {raw_stats['wallets_with_errors']}")
    if raw_stats["error_signatures"]:
        for sig, cnt in raw_stats["error_signatures"].items():
            w(f"    [{cnt}x] {sig}")
    w(f"  Wallets missing address_info (lock_hash/balance lookup failed):   {raw_stats['wallets_missing_address_info']}")
    w(f"  Wallets that proved full window coverage (saw an older tx):      {raw_stats['wallets_that_reached_window_boundary']}")
    w(f"  Observation window length(s) seen: {raw_stats['window_days_seen']}")

    w(f"\n## Largest wallets by in-window tx count (top {top_n})")
    for item in raw_stats["largest_wallets"][:top_n]:
        flag = " [CAPPED]" if item["hit_max_cap"] else ""
        w(f"  {item['tx_collected']:>6}  {item['status']:<10} {item['address']}{flag}")

    if manifest_stats:
        w("\n## Sample manifest (data/processed/sample_manifest.json)")
        w(f"  Created:                 {manifest_stats['created_at']}")
        w(f"  Sample size:             {manifest_stats['sample_size']}")
        w(f"  Pulled at all so far:    {manifest_stats['pulled_at_all']}")
        w(f"  Not yet started:         {manifest_stats['not_started']}")
        if manifest_stats["not_started_addresses"]:
            w(f"    -> {manifest_stats['not_started_addresses'][:10]}")
        w(f"  Activity buckets sampled: {manifest_stats['buckets_summary']}")
        w(f"  Known miner addresses in sample: {manifest_stats['known_miner_addresses_in_sample']}  "
          f"(pulled: {manifest_stats['known_miner_addresses_pulled']}, "
          f"complete: {manifest_stats['known_miner_addresses_complete']})")

    if processed_stats:
        w("\n## Processed dataset (data/processed/wallet_dataset.csv)")
        w(f"  Wallets included (status=complete only): {processed_stats['n_wallets_in_dataset']}")
        w(f"  Evidence state:  {processed_stats['evidence_state_counts']}")
        w(f"  Heuristic label distribution:  {processed_stats['label_counts']}")
        w(f"  Inactive wallets:     {processed_stats['is_inactive_count']}")
        w(f"  Known miner wallets:  {processed_stats['known_miner_flag_count']}")
    else:
        w("\n## Processed dataset")
        w("  Not built yet - run `python dataset.py` to generate data/processed/wallet_dataset.csv")

    if cluster_stats:
        w("\n## Discovered clusters (models/cluster_profiles.json)")
        for cid, c in cluster_stats.items():
            w(f"  Cluster {cid}: n={c['n_wallets']:<4} suggested={c['suggested_archetype']:<20} purity={c['purity']}")
    else:
        w("\n## Discovered clusters")
        w("  Not built yet - run `python cluster_model.py` after the dataset has enough complete wallets")

    return "\n".join(lines)


def address_deep_dive(address):
    path = os.path.join(config.RAW_DIR, f"{address}.json")
    if not os.path.exists(path):
        print(f"No raw record found for {address} at {path}")
        return
    with open(path) as f:
        rec = json.load(f)
    txs = rec.get("transactions", [])
    print(f"Address:          {rec['address']}")
    print(f"Status:           {rec.get('status')}")
    print(f"Window:           {rec.get('window_days')} days "
          f"({rec.get('window_start_ms')} -> {rec.get('window_end_ms')})")
    print(f"Transactions:     {len(txs)} collected, "
          f"{rec.get('listing_seen_before_cutoff', len(txs))} listing entries scanned")
    print(f"Next page cursor: {rec.get('next_page')}")
    print(f"Hit max cap:      {rec.get('hit_max_cap', False)}")
    print(f"Saw older tx:     {rec.get('saw_older_than_window', False)}")
    print(f"Last error:       {rec.get('last_error')}")
    print(f"Address info:     {'present' if rec.get('address_info') else 'MISSING'}")
    if txs:
        first_ts = min(int(t.get("block_timestamp", 0)) for t in txs if t.get("block_timestamp"))
        last_ts = max(int(t.get("block_timestamp", 0)) for t in txs if t.get("block_timestamp"))
        print(f"Tx time range:    {datetime.fromtimestamp(first_ts/1000, tz=timezone.utc)} "
              f"-> {datetime.fromtimestamp(last_ts/1000, tz=timezone.utc)}")




def main():
    p = argparse.ArgumentParser(description="Statistics on the collected raw CKB wallet data.")
    p.add_argument("--top", type=int, default=10, help="How many of the largest wallets to list.")
    p.add_argument("--save-json", help="Write the full stats dict to this path as JSON.")
    p.add_argument("--save-markdown", help="Write the human-readable report to this path.")
    p.add_argument("--address", help="Skip the aggregate report and deep-dive on one wallet's raw record.")
    args = p.parse_args()

    if args.address:
        address_deep_dive(args.address)
        return

    raw_records = load_raw_records()
    manifest = acquisition_load_sample_manifest_safe()
    df = load_processed_dataset()
    profiles = load_cluster_profiles()

    raw_stats = summarize_raw(raw_records)
    manifest_stats = summarize_manifest(manifest, raw_records)
    processed_stats = summarize_processed(df)
    cluster_stats = summarize_clusters(profiles)

    report = format_report(raw_stats, manifest_stats, processed_stats, cluster_stats, top_n=args.top)
    print(report)

    if args.save_json:
        payload = {
            "raw": raw_stats, "manifest": manifest_stats,
            "processed": processed_stats, "clusters": cluster_stats,
        }
        with open(args.save_json, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nSaved JSON stats -> {args.save_json}")

    if args.save_markdown:
        with open(args.save_markdown, "w") as f:
            f.write("```\n" + report + "\n```\n")
        print(f"Saved markdown report -> {args.save_markdown}")


if __name__ == "__main__":
    main()
