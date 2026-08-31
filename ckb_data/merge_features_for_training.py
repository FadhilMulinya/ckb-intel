from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

LABEL_COLS = ["segment", "cluster_id", "segment_confidence", "wallet_status"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--segments", type=Path, required=True, help="wallet_segments.csv (has address + segment)")
    p.add_argument("--full-features", type=Path, required=True, help="features_full.csv from preprocess_ckb_wallets.py")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    segments = pd.read_csv(args.segments)
    if "address" not in segments.columns:
        raise SystemExit("--segments file must have an 'address' column")
    segments = segments.set_index("address")

    full = pd.read_csv(args.full_features)
    if "address" not in full.columns:
        raise SystemExit("--full-features file must have an 'address' column")
    full = full.set_index("address")

    label_cols_present = [c for c in LABEL_COLS if c in segments.columns and c not in full.columns]
    skipped_overlap = [c for c in LABEL_COLS if c in segments.columns and c in full.columns]
    missing = [c for c in LABEL_COLS if c not in segments.columns]
    if missing:
        print(f"Note: --segments is missing {missing} -- proceeding with what's available.")
    if skipped_overlap:
        print(f"Note: {skipped_overlap} already present in --full-features -- using the "
              f"full-features version of these columns rather than overwriting them.")

    merged = full.join(segments[label_cols_present], how="inner")
    n_lost = len(full) - len(merged)
    if n_lost:
        print(f"Warning: {n_lost} address(es) in --full-features had no matching row in --segments "
              f"and were dropped (inner join). Check both files came from the same collection run.")

    if "segment" not in merged.columns:
        raise SystemExit("Merge failed to bring in a 'segment' column -- check --segments has one.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.out)

    numeric_cols = merged.select_dtypes(include="number").columns.tolist()
    reserved = {"cluster_id", "segment_confidence"}
    feature_cols = [c for c in numeric_cols if c not in reserved]
    print(f"\nWrote {args.out} ({len(merged)} wallets, {len(feature_cols)} numeric feature column(s) "
          f"available to train_wallet_classifier.py's auto-detection)")
    print(f"\nSegment counts in merged file:")
    print(merged["segment"].value_counts().to_string())


if __name__ == "__main__":
    main()
