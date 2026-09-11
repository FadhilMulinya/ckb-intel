from __future__ import annotations

import argparse
import json
from pathlib import Path

LONG_ADDRESS_THRESHOLD = 150  


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
                    help=f"Classify addresses longer than this as malformed. Default: {LONG_ADDRESS_THRESHOLD}")
    args = p.parse_args()

    prov_dir = args.data_dir / "provenance"
    if not prov_dir.exists():
        raise SystemExit(f"no such directory: {prov_dir}")
    if not args.addresses.exists():
        raise SystemExit(f"no such file: {args.addresses}")

    addresses = load_address_list(args.addresses)
    provenance_by_addr = scan_provenance(prov_dir)

    active, unused, malformed, not_collected = [], [], [], []

    for addr in addresses:
        rec = provenance_by_addr.get(addr)

        if len(addr) > args.long_address_threshold:
            malformed.append((addr, f"unusually long ({len(addr)} chars) -- likely not a real wallet"))
            continue

        if rec is None:
            not_collected.append(addr)
        elif rec.get("n_tx_in_window", 0) == 0:
            unused.append(addr)
        else:
            active.append(addr)

    print(f"{len(addresses)} address(es) in {args.addresses}\n")
    print(f"  active         {len(active):4d}  -- has activity, use for clustering")
    print(f"  unused         {len(unused):4d}  -- valid, dormant wallets, kept as their own category")
    print(f"  malformed      {len(malformed):4d}  -- implausible address, genuine exclusion candidate")
    print(f"  not_collected  {len(not_collected):4d}  -- retry collection")

    def write_list(path: Path, items, with_reason=False):
        with open(path, "w") as f:
            if with_reason:
                f.write("# address\treason\n")
                for addr, reason in items:
                    f.write(f"{addr}\t{reason}\n")
            else:
                for addr in items:
                    f.write(addr + "\n")
        return path

    p_active = write_list(args.data_dir / "wallets_active.txt", active)
    p_unused = write_list(args.data_dir / "wallets_unused.txt", unused)
    p_malformed = write_list(args.data_dir / "wallets_malformed.txt", malformed, with_reason=True)
    p_not_collected = write_list(args.data_dir / "wallets_not_collected.txt", not_collected)

    print(f"\nWrote {p_active}")
    print(f"Wrote {p_unused}")
    print(f"Wrote {p_malformed}")
    print(f"Wrote {p_not_collected}")
    print(f"\nFor clustering/classification: use wallets_active.txt as the population to featurize.")
    print(f"wallets_unused.txt should stay in the broader dataset as a labeled 'unused' group, "
          f"not be discarded -- it's real information about those wallets, just not behavioral "
          f"activity to characterize.")
    if not_collected:
        print(f"\n{len(not_collected)} address(es) were never collected -- re-run "
              f"collect_target_wallets.py against wallets_not_collected.txt before finalizing.")


if __name__ == "__main__":
    main()
