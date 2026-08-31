from __future__ import annotations

import argparse
import json
from pathlib import Path

LONG_ADDRESS_THRESHOLD = 150  # normal CKB addresses run 46-155 chars


def load_address_list(path: Path) -> list[str]:
    addrs, seen = [], set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line in seen:
            continue
        seen.add(line)
        addrs.append(line)
    return addrs


def scan_provenance(prov_dir: Path) -> dict[str, dict]:
    by_address = {}
    for f in prov_dir.glob("*.json"):
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        addr = rec.get("address")
        if addr:
            by_address[addr] = rec
    return by_address


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=Path("./ckb_data_v2"))
    p.add_argument("--addresses", type=Path, required=True,
                    help="The original address list this collection run was based on")
    p.add_argument("--long-address-threshold", type=int, default=LONG_ADDRESS_THRESHOLD,
                    help=f"Flag addresses longer than this as likely-malformed. Default: {LONG_ADDRESS_THRESHOLD}")
    args = p.parse_args()

    prov_dir = args.data_dir / "provenance"
    if not prov_dir.exists():
        raise SystemExit(f"no such directory: {prov_dir}")
    if not args.addresses.exists():
        raise SystemExit(f"no such file: {args.addresses}")

    addresses = load_address_list(args.addresses)
    provenance_by_addr = scan_provenance(prov_dir)

    flagged = []  
    clean = []

    for addr in addresses:
        rec = provenance_by_addr.get(addr)
        reasons = []

        if len(addr) > args.long_address_threshold:
            reasons.append(f"unusually long address ({len(addr)} chars) -- likely not a real wallet")

        if rec is None:
            reasons.append("never successfully collected (no provenance record)")
        elif rec.get("n_tx_in_window", 0) == 0:
            reasons.append("zero transactions in the collection window")

        if reasons:
            flagged.append((addr, reasons))
        else:
            clean.append(addr)

    print(f"{len(addresses)} address(es) in {args.addresses}")
    print(f"  {len(clean)} clean (have real activity, normal-length address)")
    print(f"  {len(flagged)} flagged for removal")

    if flagged:
        by_reason = {}
        for addr, reasons in flagged:
            for r in reasons:
                key = r.split(" (")[0].split(" --")[0]
                by_reason[key] = by_reason.get(key, 0) + 1
        print("\nBreakdown:")
        for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {reason}")

    flagged_path = args.data_dir / "wallets_flagged_removal.txt"
    with open(flagged_path, "w") as f:
        f.write("# address\treason(s)\n")
        for addr, reasons in flagged:
            f.write(f"{addr}\t{'; '.join(reasons)}\n")

    clean_path = args.data_dir / "addresses_clean.txt"
    with open(clean_path, "w") as f:
        for addr in clean:
            f.write(addr + "\n")

    print(f"\nWrote {flagged_path}")
    print(f"Wrote {clean_path}")
    print(f"\nUse addresses_clean.txt for anything downstream (preprocessing, a future "
          f"top-up collection run) instead of the original list.")


if __name__ == "__main__":
    main()
