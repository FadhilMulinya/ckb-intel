from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def describe(obj, prefix="", max_depth=3, depth=0, max_list_items=2):
    if depth > max_depth:
        print(f"{prefix}... (max depth reached)")
        return
    if isinstance(obj, dict):
        print(f"{prefix}dict with {len(obj)} key(s): {list(obj.keys())}")
        for k, v in obj.items():
            print(f"{prefix}  ['{k}'] ->", end=" ")
            describe(v, prefix=prefix + "    ", max_depth=max_depth, depth=depth + 1)
    elif isinstance(obj, list):
        print(f"{prefix}list with {len(obj)} item(s)")
        for i, item in enumerate(obj[:max_list_items]):
            print(f"{prefix}  [{i}] ->", end=" ")
            describe(item, prefix=prefix + "    ", max_depth=max_depth, depth=depth + 1)
        if len(obj) > max_list_items:
            print(f"{prefix}  ... ({len(obj) - max_list_items} more item(s) not shown)")
    else:
        val_repr = repr(obj)
        if len(val_repr) > 80:
            val_repr = val_repr[:80] + "..."
        print(f"{prefix}{type(obj).__name__} = {val_repr}")


def find_keys_containing(obj, needle: str, path="") -> list[str]:
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if needle.lower() in k.lower():
                hits.append(new_path)
            hits.extend(find_keys_containing(v, needle, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # don't explode on huge lists
            hits.extend(find_keys_containing(item, needle, f"{path}[{i}]"))
    return hits


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--n", type=int, default=3, help="Number of cached transactions to inspect")
    p.add_argument("--full", action="store_true",
                   help="Also dump the FULL raw JSON of each sampled transaction "
                        "(can be large -- omit for just the structural map)")
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    n_total = conn.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
    print(f"raw_transactions total: {n_total}\n")

    rows = conn.execute(
        "SELECT tx_hash, raw_json FROM raw_transactions LIMIT ?", (args.n,)
    ).fetchall()

    for tx_hash, raw_json in rows:
        print("=" * 70)
        print(f"tx_hash: {tx_hash}")
        print(f"raw_json length: {len(raw_json)} chars")
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as e:
            print(f"!! JSON DID NOT PARSE: {e}")
            print("First 300 chars:", raw_json[:300])
            continue

        print("\n--- structural map ---")
        describe(payload)

        print("\n--- keys anywhere containing 'input' ---")
        for path in find_keys_containing(payload, "input"):
            print(f"  {path}")
        print("--- keys anywhere containing 'output' ---")
        for path in find_keys_containing(payload, "output"):
            print(f"  {path}")
        print("--- keys anywhere containing 'error' ---")
        for path in find_keys_containing(payload, "error"):
            print(f"  {path}")

       
        data = payload.get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        attrs = (data or {}).get("attributes", {})
        display_inputs = attrs.get("display_inputs") or []
        display_outputs = attrs.get("display_outputs") or []

        print("\n--- FIRST INPUT CELL (full, untruncated) ---")
        if display_inputs:
            print(json.dumps(display_inputs[0], indent=2))
        else:
            print("  (display_inputs is empty or missing for this transaction)")

        print("\n--- FIRST OUTPUT CELL (full, untruncated) ---")
        if display_outputs:
            print(json.dumps(display_outputs[0], indent=2))
        else:
            print("  (display_outputs is empty or missing for this transaction)")

        if args.full:
            print("\n--- full JSON ---")
            print(json.dumps(payload, indent=2)[:5000])
            print("... (truncated at 5000 chars)" if len(json.dumps(payload)) > 5000 else "")
        print()

    conn.close()


if __name__ == "__main__":
    main()