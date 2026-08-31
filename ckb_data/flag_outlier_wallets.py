from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--features-dir", type=Path, required=True,
                   help="Output dir from preprocess_ckb_wallets.py")
    p.add_argument("--max-abs-threshold", type=float, default=8.0,
                   help="Flag a wallet if any single scaled feature exceeds this "
                        "many robust-scaled units from the median. Default: 8.0")
    p.add_argument("--distance-z-threshold", type=float, default=6.0,
                   help="Flag a wallet if its overall distance from the median "
                        "point is this many robust-z-units above the typical "
                        "distance across all wallets. Default: 6.0")
    args = p.parse_args()

    scaled_path = args.features_dir / "features_for_clustering.csv"
    full_path = args.features_dir / "features_full.csv"
    if not scaled_path.exists():
        raise SystemExit(f"no such file: {scaled_path}")

    X = pd.read_csv(scaled_path, index_col=0)
    full = pd.read_csv(full_path, index_col=0) if full_path.exists() else None

    max_abs_per_wallet = X.abs().max(axis=1)
    worst_feature_per_wallet = X.abs().idxmax(axis=1)
    flagged_max_abs = max_abs_per_wallet > args.max_abs_threshold

    distances = np.sqrt((X ** 2).sum(axis=1))
    dist_median = distances.median()
    dist_mad = (distances - dist_median).abs().median() * 1.4826  # normal-consistent MAD
    dist_z = (distances - dist_median) / dist_mad if dist_mad > 0 else pd.Series(0, index=X.index)
    flagged_distance = dist_z > args.distance_z_threshold

    flagged = flagged_max_abs | flagged_distance
    n_flagged = int(flagged.sum())

    print(f"{len(X)} wallets checked.")
    print(f"Flagged by max-abs (>{args.max_abs_threshold} scaled units on any one feature): "
          f"{int(flagged_max_abs.sum())}")
    print(f"Flagged by distance (robust z > {args.distance_z_threshold} on overall distance): "
          f"{int(flagged_distance.sum())}")
    print(f"Total flagged (either criterion): {n_flagged}\n")

    if n_flagged == 0:
        print("No outlier wallets found at these thresholds -- your clustering "
              "population looks reasonably homogeneous. No changes made.")
        return

    print("--- Flagged wallets ---")
    report_rows = []
    for addr in X.index[flagged]:
        reasons = []
        if flagged_max_abs[addr]:
            reasons.append(f"max_abs={max_abs_per_wallet[addr]:.1f} on '{worst_feature_per_wallet[addr]}'")
        if flagged_distance[addr]:
            reasons.append(f"distance_z={dist_z[addr]:.1f}")
        reason_str = "; ".join(reasons)
        print(f"\n{addr}")
        print(f"  reason: {reason_str}")
        report_rows.append({"address": addr, "reason": reason_str})
        if full is not None and addr in full.index:
            cols_of_interest = [c for c in [
                "n_tx_in_window", "sent_tx_count", "received_tx_count", "sent_edge_count", "received_edge_count",
                "sent_total_ckb", "received_total_ckb",
                "unique_counterparties_out", "unique_counterparties_in",
                "max_single_tx_ckb", "detail_coverage",
            ] if c in full.columns]
            print(full.loc[[addr], cols_of_interest].to_string(index=False))

    print(f"\nWrite-up: {n_flagged} wallet(s) flagged as likely non-ordinary-user "
          f"outliers (exchange/pool/bridge/consolidation addresses tend to look "
          f"like this: huge counterparty counts, huge single transactions, or "
          f"extreme coefficient-of-variation in transaction size). Confirm on a "
          f"CKB block explorer before excluding permanently.")

    out_txt = args.features_dir / "outlier_wallets.txt"
    with open(out_txt, "w") as f:
        f.write("# address\treason\n")
        for row in report_rows:
            f.write(f"{row['address']}\t{row['reason']}\n")
    print(f"\nWrote {out_txt}")

    X_clean = X.loc[~flagged]
    out_csv = args.features_dir / "features_for_clustering_no_outliers.csv"
    X_clean.to_csv(out_csv)
    print(f"Wrote {out_csv} ({len(X_clean)} wallets, {n_flagged} excluded)")
    print("\nNext: re-run your k-selection sweep / inspect_clusters.py against "
          f"{out_csv.name} instead of the original -- the outlier(s) above were "
          "likely inflating the silhouette score and distorting cluster shape "
          "for everyone else.")


if __name__ == "__main__":
    main()
