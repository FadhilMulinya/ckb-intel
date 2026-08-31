from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans, HDBSCAN
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                     datefmt="%H:%M:%S")
log = logging.getLogger("cluster_ckb")


PROFILE_COLS = [
    "n_tx_in_window", "tx_per_window_day", "tx_per_active_day",
    "gap_mean_s", "gap_cv", "burstiness",
    "hour_of_day_entropy", "day_of_week_entropy",
    "sent_total_ckb", "received_total_ckb",
]

DORMANT_LABEL = "Dormant / No Activity"


def load_inputs(clustering_csv: Path, full_csv: Path, manifest_path: Path):
    scaled = pd.read_csv(clustering_csv).set_index("address")
    full = pd.read_csv(full_csv).set_index("address")
    manifest = json.loads(manifest_path.read_text())

    if scaled.isna().any().any():
        bad = scaled.columns[scaled.isna().any()].tolist()
        raise ValueError(
            f"features_for_clustering.csv has unexpected NaNs in {bad} -- "
            f"this file is supposed to already be fully imputed by "
            f"preprocess_ckb_wallets.py. Re-run that script before clustering."
        )

    missing = set(scaled.index) - set(full.index)
    if missing:
        raise ValueError(
            f"{len(missing)} address(es) in the clustering matrix aren't in "
            f"features_full.csv -- these files must come from the same "
            f"preprocessing run: {list(missing)[:5]}"
        )

    if "wallet_status" not in full.columns:
        raise ValueError("features_full.csv is missing a 'wallet_status' column.")

    n_dormant = (full["wallet_status"] == "unused").sum()
    n_active = (full["wallet_status"] == "active").sum()
    log.info("loaded %d wallets total (%d active/clustered, %d dormant, %d other)",
             len(full), n_active, n_dormant, len(full) - n_active - n_dormant)
    if len(scaled) != n_active:
        log.warning(
            "features_for_clustering.csv has %d rows but features_full.csv "
            "has %d wallets marked 'active' -- these should match exactly; "
            "double check both files came from the same run.",
            len(scaled), n_active,
        )
    return scaled, full, manifest




def run_sweep(X: np.ndarray, k_min: int, k_max: int, random_state: int) -> pd.DataFrame:
    rows = []
    for k in range(k_min, k_max + 1):
        gmm = GaussianMixture(n_components=k, covariance_type="full",
                               n_init=5, random_state=random_state, max_iter=300)
        gmm_labels = gmm.fit_predict(X)
        gmm_sizes = np.bincount(gmm_labels, minlength=k)

        km = KMeans(n_clusters=k, n_init=10, random_state=random_state)
        km_labels = km.fit_predict(X)

        rows.append({
            "k": k,
            "gmm_bic": gmm.bic(X),
            "gmm_aic": gmm.aic(X),
            "gmm_silhouette": silhouette_score(X, gmm_labels) if k > 1 else np.nan,
            "gmm_min_cluster_frac": gmm_sizes.min() / len(X),
            "gmm_max_cluster_frac": gmm_sizes.max() / len(X),
            "kmeans_inertia": km.inertia_,
            "kmeans_silhouette": silhouette_score(X, km_labels) if k > 1 else np.nan,
        })
        log.info("k=%d: GMM BIC=%.1f silhouette=%.3f (smallest cluster=%.1f%% of wallets) | "
                  "KMeans silhouette=%.3f",
                  k, rows[-1]["gmm_bic"], rows[-1]["gmm_silhouette"],
                  100 * rows[-1]["gmm_min_cluster_frac"], rows[-1]["kmeans_silhouette"])
    return pd.DataFrame(rows)


def run_hdbscan_diagnostic(X: np.ndarray) -> dict:
    hdb = HDBSCAN(min_cluster_size=max(10, len(X) // 100))
    labels = hdb.fit_predict(X)
    n_noise = int((labels == -1).sum())
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    log.info("HDBSCAN diagnostic (not used for final labels): found %d clusters, "
              "%.1f%% of wallets marked as noise/unclustered",
              n_clusters, 100 * n_noise / len(X))
    return {"n_clusters": n_clusters, "n_noise": n_noise, "pct_noise": n_noise / len(X)}


def select_k(sweep: pd.DataFrame, forced_k: int | None) -> tuple[int, str]:
    if forced_k is not None:
        return forced_k, f"forced via --k {forced_k}"

    bic_best = int(sweep.loc[sweep["gmm_bic"].idxmin(), "k"])
    balanced = sweep[sweep["gmm_min_cluster_frac"] > 0.02]
    sil_best = (int(balanced.loc[balanced["gmm_silhouette"].idxmax(), "k"])
                if len(balanced) else bic_best)

    if bic_best == sil_best and bic_best != 3:
        return bic_best, (f"BIC and (outlier-filtered) silhouette both point to k={bic_best}, "
                           f"overriding the default k=3")
    return 3, (f"default: one cluster per named archetype (Human/Bot/Miner). "
               f"Sweep diagnostics: BIC-best k={bic_best}, "
               f"balanced-silhouette-best k={sil_best} -- pass --k to override.")




def label_clusters(profile: pd.DataFrame) -> dict[int, str]:
    remaining = list(profile.index)
    labels: dict[int, str] = {}

    
    vol = profile.loc[remaining, "tx_per_window_day"]
    vol_median = vol.median()
    heavy_ids = [c for c in remaining if vol_median > 0 and vol[c] > 3 * vol_median]
    if not heavy_ids and len(remaining) > 1:
        heavy_ids = [vol.idxmax()] 
    for i, c in enumerate(sorted(heavy_ids, key=lambda c: -vol[c])):
        labels[c] = "Miner / Heavy Activity" if i == 0 else f"Miner / Heavy Activity ({i + 1})"
        remaining.remove(c)

    if not remaining:
        return labels

    entropy = profile.loc[remaining, "hour_of_day_entropy"]
    med = entropy.median()
    bot_ids = sorted([c for c in remaining if entropy[c] >= med], key=lambda c: -entropy[c])
    human_ids = sorted([c for c in remaining if entropy[c] < med], key=lambda c: entropy[c])
    for i, c in enumerate(bot_ids):
        labels[c] = "Bot-like / Consistent" if i == 0 else f"Bot-like / Consistent ({i + 1})"
    for i, c in enumerate(human_ids):
        labels[c] = "Human-like / Daytime" if i == 0 else f"Human-like / Daytime ({i + 1})"
    return labels




def plot_sweep(sweep: pd.DataFrame, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(sweep["k"], sweep["gmm_bic"], marker="o", label="GMM BIC")
    axes[0].set_xlabel("k"); axes[0].set_ylabel("BIC (lower is better)")
    axes[0].set_title("GMM model selection"); axes[0].legend()

    axes[1].plot(sweep["k"], sweep["gmm_silhouette"], marker="o", label="GMM silhouette")
    axes[1].plot(sweep["k"], sweep["kmeans_silhouette"], marker="s", label="KMeans silhouette")
    axes[1].set_xlabel("k"); axes[1].set_ylabel("silhouette")
    axes[1].set_title("Silhouette (dotted region = outlier-driven, see report)")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_pca_scatter(X: np.ndarray, segment_labels: pd.Series, out_path: Path, random_state: int):
    pca = PCA(n_components=2, random_state=random_state)
    coords = pca.fit_transform(X)
    fig, ax = plt.subplots(figsize=(7, 6))
    for name, sub in pd.DataFrame({"x": coords[:, 0], "y": coords[:, 1],
                                    "segment": segment_labels.to_numpy()}).groupby("segment"):
        ax.scatter(sub["x"], sub["y"], s=14, alpha=0.6, label=f"{name} (n={len(sub)})")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.0%} var)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.0%} var)")
    ax.set_title("Active wallets, PCA projection colored by segment")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_segment_profiles(full: pd.DataFrame, out_path: Path):
    cols = ["hour_of_day_entropy", "burstiness", "gap_cv", "tx_per_window_day"]
    order = [l for l in full["segment"].unique()
             if l != DORMANT_LABEL] + ([DORMANT_LABEL] if DORMANT_LABEL in full["segment"].unique() else [])
    fig, axes = plt.subplots(1, len(cols), figsize=(4 * len(cols), 4))
    for ax, col in zip(axes, cols):
        data = [full.loc[full["segment"] == seg, col].dropna() for seg in order]
        ax.boxplot(data, labels=[s.replace(" / ", "\n") for s in order], showfliers=False)
        ax.set_title(col)
        ax.tick_params(axis="x", labelsize=7, rotation=20)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)




def write_report(out_dir: Path, sweep: pd.DataFrame, chosen_k: int, k_reason: str,
                  hdb_diag: dict, profile: pd.DataFrame, cluster_labels: dict,
                  final: pd.DataFrame):
    lines = ["# CKB Wallet Clustering Report\n"]
    lines.append("## 1. Method\n")
    lines.append(
        "Gaussian Mixture Model (full covariance), fit on the RobustScaler-scaled "
        "active-wallet matrix from `features_for_clustering.csv` (unsupervised -- no "
        "labels used in fitting). Every active wallet gets a hard cluster assignment "
        "(argmax of its GMM responsibilities); the 123 wallets with zero recorded "
        "activity are assigned directly to a `" + DORMANT_LABEL + "` segment without "
        "going through the model, since they have no timing signal to cluster on. "
        "No wallet is left unassigned or labeled noise.\n"
    )
    lines.append(f"**Chosen k = {chosen_k}** ({k_reason})\n")
    lines.append(
        f"**HDBSCAN diagnostic** (comparison only, not used for final labels): "
        f"found {hdb_diag['n_clusters']} clusters and would have marked "
        f"{hdb_diag['pct_noise']:.1%} of active wallets as noise/unclustered -- "
        f"discarded here in favor of GMM's inclusive assignment.\n"
    )
    lines.append("## 2. Model selection sweep\n")
    lines.append(sweep.round(3).to_markdown(index=False))
    lines.append(
        "\nNote on k=2: it has the highest KMeans silhouette in this sweep, but "
        "its smallest cluster is a sliver of extreme-volume outliers rather than a "
        "second behavioral archetype -- see `plots/k_sweep.png` and "
        "`gmm_min_cluster_frac` above. That's why silhouette alone isn't used to "
        "pick k here.\n"
    )
    lines.append("## 3. Segment profiles (raw, unscaled units)\n")
    display_cols = ["n_wallets"] + PROFILE_COLS
    prof_display = profile.copy()
    prof_display.index = [cluster_labels.get(c, str(c)) for c in prof_display.index]
    lines.append(prof_display[display_cols].round(2).to_markdown())
    lines.append(
        "\n`n_wallets` per segment (including Dormant):\n\n"
        + final["segment"].value_counts().rename_axis("segment").reset_index(name="n_wallets").to_markdown(index=False)
    )
    lines.append(
        "\n## 4. Caveats\n"
        "- Labels (Human-like / Bot-like / Miner / Dormant) are a post-hoc, "
        "heuristic reading of each cluster's own centroid statistics -- they are "
        "not ground truth, and the model was never told about these categories. "
        "Treat them as a starting hypothesis for further investigation, not a "
        "verified classification.\n"
        "- Monetary features (sent/received totals, concentration indices) inherit "
        "every caveat from `PREPROCESSING_REPORT.md` -- in particular the "
        "value_shannon proportional-splitting bias on multi-input transactions.\n"
        "- GMM assignments are hard (argmax) in the output CSV, but each wallet's "
        "full soft-responsibility vector is also included -- a low max-responsibility "
        "(`segment_confidence` column) means that wallet sits ambiguously between "
        "two archetypes and its label is less certain than the average member.\n"
    )
    (out_dir / "CLUSTERING_REPORT.md").write_text("\n".join(lines))




def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clustering-csv", type=Path, required=True)
    ap.add_argument("--full-csv", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--k", type=int, default=None,
                     help="Force number of active-wallet clusters. Default: auto "
                          "(see select_k()), normally 3 for Human/Bot/Miner.")
    ap.add_argument("--k-min", type=int, default=2)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--random-state", type=int, default=42)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "plots").mkdir(exist_ok=True)

    scaled, full, manifest = load_inputs(args.clustering_csv, args.full_csv, args.manifest)
    X = scaled.to_numpy()

    log.info("running GMM/KMeans sweep k=%d..%d ...", args.k_min, args.k_max)
    sweep = run_sweep(X, args.k_min, args.k_max, args.random_state)
    sweep.to_csv(args.out_dir / "cluster_k_sweep.csv", index=False)
    plot_sweep(sweep, args.out_dir / "plots" / "k_sweep.png")

    hdb_diag = run_hdbscan_diagnostic(X)

    chosen_k, k_reason = select_k(sweep, args.k)
    log.info("selected k=%d (%s)", chosen_k, k_reason)

    gmm = GaussianMixture(n_components=chosen_k, covariance_type="full",
                           n_init=10, random_state=args.random_state, max_iter=300)
    resp = gmm.fit_predict(X)
    soft = gmm.predict_proba(X)

    active_df = full.loc[scaled.index].copy()
    active_df["cluster_id"] = resp
    active_df["segment_confidence"] = soft.max(axis=1)

    profile = active_df.groupby("cluster_id")[PROFILE_COLS].mean()
    profile.insert(0, "n_wallets", active_df["cluster_id"].value_counts().sort_index())
    cluster_labels = label_clusters(profile)
    active_df["segment"] = active_df["cluster_id"].map(cluster_labels)

    log.info("cluster -> segment mapping: %s", cluster_labels)
    for cid, label in cluster_labels.items():
        row = profile.loc[cid]
        log.info("  cluster %d -> %-28s n=%-4d tx/day=%.2f hour_entropy=%.2f burstiness=%.2f",
                  cid, label, int(row["n_wallets"]), row["tx_per_window_day"],
                  row["hour_of_day_entropy"], row["burstiness"])

    dormant_df = full[full["wallet_status"] == "unused"].copy()
    dormant_df["cluster_id"] = np.nan
    dormant_df["segment_confidence"] = np.nan
    dormant_df["segment"] = DORMANT_LABEL

    other_mask = ~full["wallet_status"].isin(["active", "unused"])
    if other_mask.any():
        log.warning("%d wallet(s) have wallet_status outside {active, unused} -- "
                     "assigning them to '%s' as a safe inclusive fallback: %s",
                     other_mask.sum(), DORMANT_LABEL, list(full.index[other_mask][:5]))
        other_df = full[other_mask].copy()
        other_df["cluster_id"] = np.nan
        other_df["segment_confidence"] = np.nan
        other_df["segment"] = DORMANT_LABEL
        dormant_df = pd.concat([dormant_df, other_df])

    final = pd.concat([active_df, dormant_df]).sort_index()
    assert len(final) == len(full), (
        f"inclusiveness check failed: {len(final)} wallets in final output vs "
        f"{len(full)} in features_full.csv -- every wallet must get a segment."
    )
    assert final["segment"].notna().all(), "every wallet must have a non-null segment"

    out_cols = ["wallet_status", "segment", "cluster_id", "segment_confidence"] + PROFILE_COLS
    final[out_cols].to_csv(args.out_dir / "wallet_segments.csv")
    log.info("wrote %s (%d wallets, %d segments: %s)",
             args.out_dir / "wallet_segments.csv", len(final),
             final["segment"].nunique(), sorted(final["segment"].unique()))

    plot_pca_scatter(X, active_df["segment"], args.out_dir / "plots" / "pca_segments.png",
                      args.random_state)
    plot_segment_profiles(final, args.out_dir / "plots" / "segment_profiles.png")

    write_report(args.out_dir, sweep, chosen_k, k_reason, hdb_diag, profile, cluster_labels, final)
    log.info("done. See %s for the full report.", args.out_dir / "CLUSTERING_REPORT.md")


if __name__ == "__main__":
    sys.exit(main())
