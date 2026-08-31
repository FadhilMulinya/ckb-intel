from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--features-dir", type=Path, required=True,
                   help="Output dir from preprocess_ckb_wallets.py (contains "
                        "features_for_clustering.csv and features_full.csv)")
    p.add_argument("--k", type=int, default=2)
    args = p.parse_args()

    scaled_path = args.features_dir / "features_for_clustering.csv"
    full_path = args.features_dir / "features_full.csv"
    if not scaled_path.exists():
        raise SystemExit(f"no such file: {scaled_path}")
    if not full_path.exists():
        raise SystemExit(f"no such file: {full_path}")

    X_scaled = pd.read_csv(scaled_path, index_col=0)
    full = pd.read_csv(full_path, index_col=0)

    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    km = KMeans(n_clusters=args.k, n_init=10, random_state=0)
    labels = km.fit_predict(X_scaled.values)
    sizes = pd.Series(labels).value_counts().sort_index()

    print(f"KMeans k={args.k}")
    print("Cluster sizes:")
    for cluster_id, size in sizes.items():
        pct = 100 * size / len(labels)
        flag = "  <-- tiny cluster, likely an outlier/artifact, not a behavioral group" if pct < 3 else ""
        print(f"  cluster {cluster_id}: {size} wallets ({pct:.1f}%){flag}")

    if len(sizes) == 2:
        sil = silhouette_score(X_scaled.values, labels)
        print(f"\nSilhouette: {sil:.3f}", end="")
        if sil > 0.85:
            print("  <-- very high; check the feature breakdown below before "
                  "trusting this as a real behavioral split")
        else:
            print()


    df = X_scaled.copy()
    df["_cluster"] = labels
    means = df.groupby("_cluster").mean()

    if args.k == 2:
        gap = (means.loc[1] - means.loc[0]).abs().sort_values(ascending=False)
    else:
        gap = means.var(axis=0).sort_values(ascending=False)

    print("\nTop features driving the split (scaled units, biggest gap first):")
    print(f"{'feature':<32}" + "".join(f"cluster {c:<10}" for c in means.index) + "gap")
    for feat in gap.index[:15]:
        row = "".join(f"{means.loc[c, feat]:<18.3f}" for c in means.index)
        print(f"{feat:<32}{row}{gap[feat]:.3f}")


    print("\n--- Artifact checks ---")
    if "n_tx_in_window" in full.columns:
        full_aligned = full.reindex(X_scaled.index)
        tx_by_cluster = pd.Series(full_aligned["n_tx_in_window"].values, index=X_scaled.index).groupby(labels).describe()
        print("\nn_tx_in_window (RAW, not scaled) by cluster:")
        print(tx_by_cluster[["count", "mean", "50%", "min", "max"]].to_string())
        print("(if one cluster is essentially 'low tx count' and the other "
              "'high tx count' with little else distinguishing them, the "
              "split is closer to 'active vs quiet' than a rich behavioral "
              "pattern -- still potentially useful, just know what it is)")

    if "detail_coverage" in full.columns:
        cov_aligned = full.reindex(X_scaled.index)["detail_coverage"]
        cov_by_cluster = pd.Series(cov_aligned.values, index=X_scaled.index).groupby(labels).describe()
        print("\ndetail_coverage (RAW) by cluster:")
        print(cov_by_cluster[["count", "mean", "50%", "min", "max"]].to_string())
        print("(if this differs sharply between clusters, the split may be "
              "tracking data completeness rather than wallet behavior)")

    top_feature_names = set(gap.index[:5])
    imputation_prone = {
        "sent_mean_ckb", "sent_median_ckb", "sent_cv", "received_mean_ckb",
        "received_median_ckb", "received_cv", "reciprocity_ratio",
        "out_value_concentration_hhi", "in_value_concentration_hhi",
        "max_single_tx_ckb", "gap_mean_s", "gap_median_s", "gap_cv", "burstiness",
    }
    overlap = top_feature_names & imputation_prone
    coverage_differs = False
    if "detail_coverage" in full.columns:
        cov_means = pd.Series(cov_aligned.values, index=X_scaled.index).groupby(labels).mean()
        coverage_differs = (cov_means.max() - cov_means.min()) > 0.1

    if len(overlap) >= 3 and coverage_differs:
        print(f"\n {len(overlap)} of the top 5 driving features ({sorted(overlap)}) "
              f"are ones that get median-imputed for wallets missing that data, AND "
              f"detail_coverage differs meaningfully between clusters. This is a "
              f"strong signal the split is (at least partly) a data-completeness "
              f"artifact rather than a purely behavioral one -- worth checking "
              f"cluster membership against columns_with_imputation in "
              f"feature_manifest.json before drawing conclusions from k={args.k}.")
    elif len(overlap) >= 3:
        print(f"\nNote: {len(overlap)} of the top 5 driving features ({sorted(overlap)}) "
              f"are ones that CAN be median-imputed -- but detail_coverage is "
              f"essentially equal across clusters, which rules out imputation as "
              f"the cause here. These are more likely genuine extreme values in a "
              f"small number of wallets (see the tiny-cluster check below if any "
              f"cluster is small) rather than a data-completeness artifact.")


    tiny_clusters = [c for c, size in sizes.items() if 100 * size / len(labels) < 3]
    if tiny_clusters:
        print("\n--- Tiny-cluster wallet identification ---")
        for c in tiny_clusters:
            members = X_scaled.index[labels == c]
            print(f"\nCluster {c} ({len(members)} wallet(s)):")
            for addr in members:
                print(f"  {addr}")
            if all(m in full.index for m in members):
                cols_of_interest = [c for c in [
                    "n_tx_in_window", "sent_tx_count", "received_tx_count", "sent_edge_count", "received_edge_count",
                    "sent_total_ckb", "received_total_ckb", "sent_cv", "received_cv",
                    "unique_counterparties_out", "unique_counterparties_in",
                    "max_single_tx_ckb", "detail_coverage",
                ] if c in full.columns]
                print(full.loc[members, cols_of_interest].to_string())
            print("  Look this address up on a CKB block explorer -- a single "
                  "wallet this far from everyone else is often an exchange "
                  "hot wallet, a mixer/tumbler, a bridge/contract address, or "
                  "some other non-'ordinary user' entity that got swept into "
                  "the address list. If so, it's usually better excluded from "
                  "the main clustering population and reported/labeled "
                  "separately, the same way unused wallets are.")


if __name__ == "__main__":
    main()
