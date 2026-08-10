import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# reuse fetch_real_data.py's HTTP client unmodified -- same retry/backoff/
# rate-limit behavior as the original collection run, no reimplementation
import importlib.util


def load_fetch_module(repo_root):
    path = os.path.join(repo_root, "fetch_real_data.py")
    spec = importlib.util.spec_from_file_location("fetch_real_data", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def collect_target_addresses(repo_root):
    """Every address in the committed 264-address dataset (both manifests),
    deduplicated. This is deliberately the committed set, not the full
    441-address discovered/classified pool in checkpoint.json -- the
    retrain step later can only use addresses we have transaction history
    files for on disk, which is exactly this set."""
    addrs = []
    seen = set()
    for bucket in ("bot_like", "human_like"):
        manifest_path = os.path.join(repo_root, "data", "real", bucket, "manifest.json")
        manifest = json.load(open(manifest_path))
        for entry in manifest:
            a = entry["address"]
            if a not in seen:
                seen.add(a)
                addrs.append((a, bucket, entry["label_source"]))
    return addrs


def load_existing(out_path):
    done = {}
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                done[rec["address"]] = rec
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=".", help="path to the ckb-intel repo root")
    ap.add_argument("--out", default="data/real/lifetime_stats.jsonl")
    ap.add_argument("--min-interval", type=float, default=0.25, help="seconds between API calls")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    fetch_mod = load_fetch_module(repo_root)

    targets = collect_target_addresses(repo_root)
    print(f"{len(targets)} unique addresses in the committed dataset (bot_like + human_like manifests)",
          file=sys.stderr)

    out_path = os.path.join(repo_root, args.out) if not os.path.isabs(args.out) else args.out
    done = load_existing(out_path)
    print(f"{len(done)} already fetched (resuming)", file=sys.stderr)

    with open(out_path, "a") as f:
        for i, (addr, bucket_dir, original_label) in enumerate(targets):
            if addr in done:
                continue
            try:
                data = fetch_mod.api_get(
                    f"/addresses/{addr}", min_interval=args.min_interval,
                )
            except fetch_mod.ApiError as e:
                rec = {
                    "address": addr, "original_label": original_label,
                    "tx_count": None, "is_special": None, "error": str(e),
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                print(f"  [{i+1}/{len(targets)}] ERROR {addr}: {e}", file=sys.stderr)
                continue

            tx_count, is_special = 0, False
            if data and data.get("data"):
                record = data["data"]
                records = record if isinstance(record, list) else [record]
                for r in records:
                    attrs = r.get("attributes", {})
                    tx_count += int(attrs.get("transactions_count") or 0)
                    is_special = is_special or (str(attrs.get("is_special", "false")).lower() == "true")

            rec = {
                "address": addr, "original_label": original_label,
                "tx_count": tx_count, "is_special": is_special, "error": None,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if i % 10 == 0:
                print(f"  [{i+1}/{len(targets)}] {addr[:24]}... tx_count={tx_count} is_special={is_special}",
                      file=sys.stderr)

    print(f"done. wrote lifetime stats to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
