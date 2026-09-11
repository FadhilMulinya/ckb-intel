from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def scan_provenance(prov_dir: Path) -> list[dict]:
    records = []
    for f in prov_dir.glob("*.json"):
        try:
            records.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def categorize(r: dict) -> str:
    if r.get("n_tx_in_window", 0) == 0:
        return "zero_data"
    if r.get("listing_truncated"):
        return "truncated_beyond_cap"         
    if r.get("detail_sampled"):
        return "known_total_partial_detail"    
    return "fully_collected"                   


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=Path("./ckb_data_v2"))
    args = p.parse_args()

    prov_dir = args.data_dir / "provenance"
    if not prov_dir.exists():
        raise SystemExit(f"no such directory: {prov_dir}")

    records = scan_provenance(prov_dir)
    if not records:
        raise SystemExit(f"no provenance files found in {prov_dir}")

    for r in records:
        r["_category"] = categorize(r)

    n = len(records)
    counts = {}
    for r in records:
        counts[r["_category"]] = counts.get(r["_category"], 0) + 1

    print(f"{n} wallet(s) with provenance data\n")
    print("=== Category breakdown ===")
    print(f"  fully_collected            {counts.get('fully_collected', 0):4d}  -- nothing to do")
    print(f"  known_total_partial_detail {counts.get('known_total_partial_detail', 0):4d}  -- "
          f"true count known, safe to top up detail only")
    print(f"  truncated_beyond_cap       {counts.get('truncated_beyond_cap', 0):4d}  -- "
          f"true count UNKNOWN, needs re-listing first")
    print(f"  zero_data                  {counts.get('zero_data', 0):4d}  -- "
          f"see flag_empty_wallets.py")

   
    csv_path = args.data_dir / "wallet_collection_status.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "category", "n_tx_in_window", "n_tx_detail_fetched",
                          "n_tx_detail_remaining", "listing_truncated", "detail_sampled",
                          "deepest_block_number", "shallowest_block_number"])
        for r in sorted(records, key=lambda r: -r.get("n_tx_in_window", 0)):
            deepest = (r.get("deepest_block") or {}).get("block_number")
            shallow = (r.get("shallowest_block") or {}).get("block_number")
            writer.writerow([
                r["address"], r["_category"], r.get("n_tx_in_window", 0),
                r.get("n_tx_detail_fetched", 0), r.get("n_tx_detail_remaining", 0),
                r.get("listing_truncated", False), r.get("detail_sampled", False),
                deepest, shallow,
            ])
    print(f"\nWrote {csv_path} ({n} rows, sorted by activity level)")

    
    cat_a = [r for r in records if r["_category"] == "truncated_beyond_cap"]
    cat_a.sort(key=lambda r: -r.get("n_tx_in_window", 0))
    path_a = args.data_dir / "wallets_truncated_beyond_cap.txt"
    with open(path_a, "w") as f:
        for r in cat_a:
            f.write(r["address"] + "\n")
    print(f"Wrote {path_a} ({len(cat_a)} address(es) -- true totals unknown, need re-listing)")

    
    cat_b = [r for r in records if r["_category"] == "known_total_partial_detail"]
    cat_b.sort(key=lambda r: r.get("n_tx_detail_remaining", 0))  # cheapest first
    path_b = args.data_dir / "wallets_detail_capped_known_total.txt"
    with open(path_b, "w") as f:
        f.write("# address\tn_tx_detail_remaining\tn_tx_in_window\n")
        for r in cat_b:
            f.write(f"{r['address']}\t{r.get('n_tx_detail_remaining', 0)}\t{r.get('n_tx_in_window', 0)}\n")
    total_remaining_b = sum(r.get("n_tx_detail_remaining", 0) for r in cat_b)
    print(f"Wrote {path_b} ({len(cat_b)} address(es), {total_remaining_b} total tx still "
          f"needing detail -- exact, safe number)")

    print("\n=== Recommended order of operations ===")
    print(f"1. Re-list Category A first (true totals unknown):")
    print(f"   python3 collect_target_wallets.py --data-dir {args.data_dir} "
          f"--addresses {path_a} --max-tx-listed 0 --max-tx-details <same as before> --as-of <same date>")
    print(f"2. Then top up Category B (or both, once A's true totals are known) to each "
          f"wallet's own full total -- no shared ceiling, matching what each wallet actually needs:")
    print(f"   python3 collect_target_wallets.py --data-dir {args.data_dir} "
          f"--addresses {path_b} --max-tx-details 0 --as-of <same date>")


if __name__ == "__main__":
    main()
