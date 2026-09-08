import argparse
import config
import acquisition


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Report only, don't rewrite any files.")
    args = p.parse_args()

    import os, json
    records = []
    for fname in os.listdir(config.RAW_DIR):
        if fname.endswith(".json") and not fname.endswith(".tmp"):
            with open(os.path.join(config.RAW_DIR, fname)) as f:
                records.append(json.load(f))

    stale = [
        r for r in records
        if r.get("status") == "complete" and r.get("hit_max_cap") and not r.get("saw_older_than_window")
    ]

    print(f"Scanned {len(records)} wallets on disk.")
    print(f"Found {len(stale)} with the stale complete+capped contradiction.")

    if not stale:
        print("Nothing to repair.")
        return

    for r in stale:
        print(f"  {r['address']}  (tx_collected={len(r.get('transactions', []))}, "
              f"next_page={r.get('next_page')})")

    if args.dry_run:
        print("\n--dry-run: no files were changed. Re-run without --dry-run to apply.")
        return

    for r in stale:
        r["status"] = "capped"
        acquisition._save_cache(r)

    print(f"\nRepaired {len(stale)} wallets: status corrected from 'complete' to 'capped'.")
    print("They are now correctly excluded from the training CSV. To pull their full month:")
    print("  python dataset.py --max-tx-per-wallet 200000 --max-pages-per-wallet 10000")
    print("(resumes each from its saved page - won't re-fetch already-collected pages)")


if __name__ == "__main__":
    main()
