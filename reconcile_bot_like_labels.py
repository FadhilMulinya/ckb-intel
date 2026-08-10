import argparse
import json
import os
import sys

from fetch_real_data import api_get, ApiError, load_checkpoint, save_checkpoint


def get_address_summary(address):
    data = api_get(f"/addresses/{address}")
    if not data or not data.get("data"):
        return None, None
    record = data["data"]
    records = record if isinstance(record, list) else [record]
    tx_count = 0
    is_special = False
    for r in records:
        attrs = r.get("attributes", {})
        tx_count += int(attrs.get("transactions_count") or 0)
        is_special = is_special or (str(attrs.get("is_special", "false")).lower() == "true")
    return tx_count, is_special


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="data/real")
    ap.add_argument("--bot-min-tx", type=int, default=1000,
                     help="must match the value used in fetch_real_data.py -- the rule being reconciled against")
    ap.add_argument("--dry-run", action="store_true", help="report what would change without modifying any files")
    args = ap.parse_args()

    state = load_checkpoint(args.out_dir)
    bucket_dir = os.path.join(args.out_dir, "bot_like")
    manifest_path = os.path.join(bucket_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"no manifest.json found at {manifest_path} -- nothing to reconcile", file=sys.stderr)
        return

    manifest = json.load(open(manifest_path))
    kept, removed = [], []

    for entry in manifest:
        addr = entry["address"]
        tx_count = entry.get("tx_count")
        is_special = entry.get("is_special")
        if tx_count is None:
            cached = state["classified"].get(addr)
            if isinstance(cached, dict) and cached.get("tx_count") is not None:
                tx_count, is_special = cached.get("tx_count"), cached.get("is_special")

        if tx_count is None:
            try:
                tx_count, is_special = get_address_summary(addr)
            except ApiError as e:
                print(f"  SKIP (API error, leaving as-is): {addr}: {e}", file=sys.stderr)
                kept.append({**entry, "reconciliation_note": f"could not re-verify: {e}"})
                continue
            if tx_count is None:
                print(f"  SKIP (address no longer found, leaving as-is): {addr}", file=sys.stderr)
                kept.append({**entry, "reconciliation_note": "address not found on re-query"})
                continue

        still_valid = tx_count >= args.bot_min_tx
        entry["tx_count"] = tx_count
        entry["is_special"] = is_special

        if still_valid:
            kept.append(entry)
        else:
            removed.append({
                "address": addr, "tx_count": tx_count, "is_special": is_special,
                "reason": (
                    f"was bot_like only because is_special=True (old rule: is_special OR tx_count>={args.bot_min_tx}); "
                    f"tx_count={tx_count} < {args.bot_min_tx} under corrected rule (tx_count only)"
                    if is_special else
                    f"tx_count={tx_count} < {args.bot_min_tx} -- unclear why this was ever bucketed bot_like, flagging for review"
                ),
            })

    print(f"\nreconciliation against bot_min_tx={args.bot_min_tx} (tx-count only, is_special ignored):")
    print(f"  kept:    {len(kept)}")
    print(f"  removed: {len(removed)}")
    for r in removed:
        print(f"    - {r['address']}  tx_count={r['tx_count']}  is_special={r['is_special']}\n      {r['reason']}")

    threshold_only = special_only = both = neither = 0
    for entry in kept + [{"tx_count": r["tx_count"], "is_special": r["is_special"]} for r in removed]:
        meets_threshold = entry["tx_count"] >= args.bot_min_tx
        is_spec = bool(entry["is_special"])
        if meets_threshold and is_spec:
            both += 1
        elif meets_threshold:
            threshold_only += 1
        elif is_spec:
            special_only += 1
        else:
            neither += 1  
    print(f"\nbreakdown across all {len(kept) + len(removed)} addresses ever bucketed bot_like (old OR new rule):")
    print(f"  threshold only (tx_count >= {args.bot_min_tx}, is_special=False): {threshold_only}")
    print(f"  is_special only (is_special=True, tx_count < {args.bot_min_tx}):  {special_only}  <- these are the ones being removed")
    print(f"  both (tx_count >= {args.bot_min_tx} AND is_special=True):        {both}")
    print(f"  neither (shouldn't happen -- flag for investigation):            {neither}")

    report = {
        "bot_min_tx_used": args.bot_min_tx,
        "n_kept": len(kept),
        "n_removed": len(removed),
        "breakdown": {
            "threshold_only": threshold_only,
            "is_special_only": special_only,
            "both": both,
            "neither": neither,
        },
        "removed": removed,
    }
    report_path = os.path.join(args.out_dir, "reconciliation_report.json")

    if args.dry_run:
        print(f"\n--dry-run: no files modified. Would write report to {report_path}")
        return

    # reindex kept entries contiguously, delete files for removed ones
    new_manifest = []
    for new_idx, entry in enumerate(kept):
        old_idx = entry["index"]
        old_path = os.path.join(bucket_dir, f"addr_{old_idx}.json")
        new_path = os.path.join(bucket_dir, f"addr_{new_idx}.json")
        if old_idx != new_idx and os.path.exists(old_path):
            os.replace(old_path, new_path)
        entry["index"] = new_idx
        new_manifest.append(entry)

    kept_addrs = {e["address"] for e in kept}
    for entry in manifest:
        if entry["address"] not in kept_addrs:
            old_path = os.path.join(bucket_dir, f"addr_{entry['index']}.json")
            if os.path.exists(old_path) and entry["index"] >= len(new_manifest):
                # only safe to delete indices that weren't reused by the reindex above
                os.remove(old_path)

    with open(manifest_path, "w") as f:
        json.dump(new_manifest, f, indent=2)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    state["fetched"]["bot_like"] = [e["address"] for e in new_manifest]
    for r in removed:
        if r["address"] in state["classified"]:
            state["classified"][r["address"]] = {
                "bucket": None, "tx_count": r["tx_count"], "is_special": r["is_special"],
            }
    save_checkpoint(args.out_dir, state)

    print(f"\nwrote {report_path}")
    print(f"updated manifest.json and checkpoint.json -- bot_like pool is now {len(new_manifest)} addresses")
    print("run fetch_real_data.py again (same command as before) to top the pool back up under the corrected rule.")


if __name__ == "__main__":
    main()
