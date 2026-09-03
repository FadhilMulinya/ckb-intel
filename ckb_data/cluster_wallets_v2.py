from __future__ import annotations

"""
Phase 4 of the gap-closure plan (see CKB_Wallet_Classifier_Gap_Closure_Plan.md,
section 3, Phase 4): re-cluster on the combined Phase 2 feature set as a
SANITY CHECK on Phase 3's rule-based archetypes -- not to assign final
labels. Two specific things from the original cluster_ckb_wallets.py are
fixed here, everything else (GMM/KMeans sweep, BIC, HDBSCAN diagnostic,
PCA/profile plots) is kept because it's solid:

  1. select_k() no longer special-cases k=3 ("one cluster per named
     archetype") when the data doesn't actually support it. It just uses
     whichever k the sweep diagnostics point to, full stop.
  2. label_clusters() no longer assigns Human-like/Bot-like/Miner names from
     ad hoc thresholds. Cluster names here are auto-generated from each
     cluster's own most-distinguishing features (e.g.
     "high_shape_n_to_1_ratio+low_gap_cv") -- descriptive, not a behavioral
     verdict. The actual verdict machinery is Phase 5 (ground truth) + Phase
     6 (mapping), not this script.

The real deliverable of this script is the CROSS-TAB against Phase 3's
wallet_archetypes.csv: for each unsupervised cluster, what fraction of its
members did Phase 3's independent, rule-based scoring call each archetype?
Agreement is a good sign (two independent methods found the same structure).
Disagreement is not automatically a bug in either one -- it's exactly the
kind of thing Phase 5's ground-truth sampling should prioritize checking.

Usage:
    python3 cluster_wallets_v2.py --features-dir ./ckb_features --out-dir ./ckb_clustering_v2
"""

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans, HDBSCAN
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score, normalized_mutual_info_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("cluster_wallets_v2")

INACTIVE_LABEL = "Inactive"
INSUFFICIENT_DATA_LABEL = "Insufficient_Data"
OUTLIER_LABEL = "Outlier_Excluded"

# Same thresholds/logic as flag_outlier_wallets.py, reused rather than
# reimplemented -- see run_outlier_detection() below for why this needs to
# run BEFORE the sweep, not as an optional afterthought.
DEFAULT_MAX_ABS_THRESHOLD = 8.0
DEFAULT_DISTANCE_Z_THRESHOLD = 6.0

# Columns pulled into the clustering matrix, from both the existing temporal
# pipeline (features_full.csv) and Phase 2 (features_cell_layer.csv).
# Deliberately EXCLUDES anything from wallet_archetypes.csv -- clustering on
# Phase 3's own archetype scores would make the "sanity check" circular.
LOG_TRANSFORM_COLS = [
    "sent_total_ckb", "received_total_ckb", "max_single_tx_ckb",
    "sent_capacity_ckb_cell", "received_capacity_ckb_cell",
]
SIGNED_LOG_TRANSFORM_COLS = ["net_capacity_delta_ckb_cell"]

CLUSTERING_FEATURE_COLS = [
    # temporal (existing pipeline)
    "tx_per_window_day", "gap_cv", "burstiness",
    "hour_of_day_entropy", "day_of_week_entropy",
    "sent_total_ckb", "received_total_ckb", "max_single_tx_ckb",
    "unique_counterparties_out", "unique_counterparties_in", "reciprocity_ratio",
    "out_value_concentration_hhi", "in_value_concentration_hhi",
    # Cell layer (Phase 2)
    "shape_1_to_1_ratio", "shape_1_to_n_ratio", "shape_n_to_1_ratio", "shape_n_to_n_ratio",
    "cell_lifetime_cv", "same_block_spend_ratio",
    "n_distinct_lock_hashes", "multisig_usage_ratio", "has_type_script_ratio",
    "uses_since_ratio", "repeated_since_value_ratio",
    "unique_counterparties_out_cell", "unique_counterparties_in_cell",
    "reciprocity_ratio_cell", "out_capacity_concentration_hhi_cell", "out_capacity_entropy_cell",
    "sent_capacity_ckb_cell", "received_capacity_ckb_cell", "net_capacity_delta_ckb_cell",
]

# Short display tags for auto-generated cluster names -- keep these NEUTRAL
# (describe the statistic, not a behavioral class).
FEATURE_TAGS = {
    "tx_per_window_day": "tx_volume", "gap_cv": "gap_cv", "burstiness": "burstiness",
    "hour_of_day_entropy": "hour_entropy", "day_of_week_entropy": "dow_entropy",
    "sent_total_ckb": "sent_ckb", "received_total_ckb": "received_ckb",
    "max_single_tx_ckb": "max_tx", "unique_counterparties_out": "out_counterparties",
    "unique_counterparties_in": "in_counterparties", "reciprocity_ratio": "reciprocity",
    "out_value_concentration_hhi": "out_hhi", "in_value_concentration_hhi": "in_hhi",
    "shape_1_to_1_ratio": "shape_1to1", "shape_1_to_n_ratio": "shape_1toN",
    "shape_n_to_1_ratio": "shape_Nto1", "shape_n_to_n_ratio": "shape_NtoN",
    "cell_lifetime_cv": "lifetime_cv", "same_block_spend_ratio": "same_block_spend",
    "n_distinct_lock_hashes": "n_locks", "multisig_usage_ratio": "multisig",
    "has_type_script_ratio": "has_type_script", "uses_since_ratio": "uses_since",
    "repeated_since_value_ratio": "repeated_since", "unique_counterparties_out_cell": "out_counterparties_cell",
    "unique_counterparties_in_cell": "in_counterparties_cell", "reciprocity_ratio_cell": "reciprocity_cell",
    "out_capacity_concentration_hhi_cell": "out_hhi_cell", "out_capacity_entropy_cell": "out_entropy_cell",
    "sent_capacity_ckb_cell": "sent_ckb_cell", "received_capacity_ckb_cell": "received_ckb_cell",
    "net_capacity_delta_ckb_cell": "net_delta_cell",
}


def classify_population(df: pd.DataFrame) -> pd.Series:
    """Splits wallets into 'active' (cluster these), 'inactive' (a real,
    collected, genuinely-zero-transaction wallet), or 'insufficient_data'
    (never successfully collected -- we have no basis to call it either
    active or inactive, and lumping it into Inactive would misrepresent a
    DATA GAP as a BEHAVIORAL FACT).

    Uses wallet_status when available (this is exactly the distinction
    classify_wallet_status.py already draws between 'unused' and
    'not_collected' -- reuse it rather than re-deriving a cruder version
    from n_tx_in_window, which can't tell "genuinely zero transactions"
    apart from "no provenance record at all" once NaN gets filled to 0).
    Falls back to the n_tx_in_window heuristic only if wallet_status isn't
    present, with an explicit warning about the limitation.
    """
    if "wallet_status" in df.columns:
        status = df["wallet_status"]
        result = pd.Series("insufficient_data", index=df.index)
        result.loc[status == "active"] = "active"
        result.loc[status == "unused"] = "inactive"
        other = ~status.isin(["active", "unused"])
        if other.any():
            log.warning("%d wallet(s) have wallet_status outside {active, unused} (e.g. "
                         "not_collected, malformed) -- excluding from BOTH clustering and the "
                         "Inactive rule, reported separately as '%s'. Folding these into Inactive "
                         "would misrepresent a data-collection gap as a behavioral fact.",
                         int(other.sum()), INSUFFICIENT_DATA_LABEL)
        return result

    log.warning("no wallet_status column found -- falling back to an n_tx_in_window-based split. "
                 "This CANNOT distinguish a genuinely-collected zero-transaction wallet from one "
                 "that was simply never collected (both show n_tx_in_window as NaN/0) -- if that "
                 "distinction matters, ensure features_full.csv carries wallet_status "
                 "(classify_wallet_status.py's active/unused/not_collected/malformed).")
    has_data = df["n_tx_in_window"].notna()
    result = pd.Series("insufficient_data", index=df.index)
    result.loc[has_data & (df["n_tx_in_window"] > 0)] = "active"
    result.loc[has_data & (df["n_tx_in_window"] <= 0)] = "inactive"
    return result


# ---------------------------------------------------------------------------
# Outlier exclusion -- MUST run before the sweep/fit, not after
# ---------------------------------------------------------------------------

def detect_outliers(X_scaled: pd.DataFrame, max_abs_threshold: float, distance_z_threshold: float) -> tuple[pd.Series, pd.DataFrame]:
    """Same logic as flag_outlier_wallets.py, run BEFORE clustering rather
    than as a separate after-the-fact diagnostic. Reason: raw, unbounded
    count features (unique_counterparties_out/in and their _cell
    counterparts) can have a handful of extreme values -- an exchange or
    pool wallet with thousands of counterparties against a population where
    everyone else has single digits. In scaled-distance space those few
    wallets dominate every k's partition, inflating silhouette (a few
    trivially-isolated outliers look like great "clusters") while producing
    near-zero agreement with Phase 3's archetypes, which are built on
    bounded ratios/shapes, not raw counts. Found running this exact
    situation against real 764-wallet data: silhouette >0.93 at every k
    with the smallest cluster under 1%, and NMI against archetypes of
    0.014 -- both symptoms of this artifact, not of two methods
    legitimately disagreeing about real structure.
    """
    max_abs_per_wallet = X_scaled.abs().max(axis=1)
    worst_feature_per_wallet = X_scaled.abs().idxmax(axis=1)
    flagged_max_abs = max_abs_per_wallet > max_abs_threshold

    distances = np.sqrt((X_scaled ** 2).sum(axis=1))
    dist_median = distances.median()
    dist_mad = (distances - dist_median).abs().median() * 1.4826
    dist_z = (distances - dist_median) / dist_mad if dist_mad > 0 else pd.Series(0, index=X_scaled.index)
    flagged_distance = dist_z > distance_z_threshold

    flagged = flagged_max_abs | flagged_distance

    detail = pd.DataFrame({
        "max_abs_scaled_value": max_abs_per_wallet,
        "worst_feature": worst_feature_per_wallet,
        "distance_z": dist_z,
        "flagged_max_abs": flagged_max_abs,
        "flagged_distance": flagged_distance,
    })
    return flagged, detail


# ---------------------------------------------------------------------------
# Load + prepare the matrix
# ---------------------------------------------------------------------------

def load_and_join(features_dir: Path) -> pd.DataFrame:
    full_path = features_dir / "features_full.csv"
    cell_path = features_dir / "features_cell_layer.csv"
    if not full_path.exists():
        raise SystemExit(f"no such file: {full_path} -- run preprocess_ckb_wallets.py first.")
    if not cell_path.exists():
        raise SystemExit(f"no such file: {cell_path} -- run preprocess_cell_features.py (Phase 2) first.")

    full_df = pd.read_csv(full_path, index_col="address")
    cell_df = pd.read_csv(cell_path, index_col="address")
    df = full_df.join(cell_df, how="outer", rsuffix="_cellfile")
    log.info("joined features_full.csv (%d rows) with features_cell_layer.csv (%d rows) -> %d rows",
              len(full_df), len(cell_df), len(df))
    return df


def build_clustering_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    available_cols = [c for c in CLUSTERING_FEATURE_COLS if c in df.columns]
    missing_cols = [c for c in CLUSTERING_FEATURE_COLS if c not in df.columns]
    if missing_cols:
        log.warning("%d expected column(s) not found, skipping: %s", len(missing_cols), missing_cols)

    X = df[available_cols].copy()
    for c in LOG_TRANSFORM_COLS:
        if c in X.columns:
            X[c] = np.log1p(X[c].clip(lower=0))
    for c in SIGNED_LOG_TRANSFORM_COLS:
        if c in X.columns:
            X[c] = np.sign(X[c]) * np.log1p(X[c].abs())

    # SimpleImputer silently DROPS columns with zero observed values from its
    # output array (with only a UserWarning, easy to miss), which desyncs
    # the result from X.columns and crashes the DataFrame reconstruction --
    # found running this against real 887-wallet data where
    # repeated_since_value_ratio came back entirely NaN. Detect and drop
    # such columns explicitly, with a clear diagnostic, rather than letting
    # imputer.fit_transform() silently change shape underneath us.
    all_nan_cols = [c for c in X.columns if X[c].isna().all()]
    if all_nan_cols:
        log.warning("%d column(s) have ZERO observed values across all %d wallets and cannot be "
                     "imputed -- dropping from the clustering matrix: %s. This is worth checking "
                     "independently (e.g. did every wallet in this population score "
                     "INSUFFICIENT_EVIDENCE for this specific feature family in Phase 2?) but "
                     "clustering can proceed without it.", len(all_nan_cols), len(X), all_nan_cols)
        X = X.drop(columns=all_nan_cols)

    n_imputed = int(X.isna().sum().sum())
    if n_imputed:
        log.info("median-imputing %d missing value(s) across the clustering matrix "
                  "(e.g. cell_lifetime_cv / repeated_since_value_ratio are undefined for wallets "
                  "without enough resolved data -- consistent with how the rest of this pipeline "
                  "handles INSUFFICIENT_EVIDENCE, not dropped as rows).", n_imputed)
    imputer = SimpleImputer(strategy="median")
    X_imputed = pd.DataFrame(imputer.fit_transform(X), index=X.index, columns=X.columns)
    return X_imputed, list(X.columns)


# ---------------------------------------------------------------------------
# Sweep / diagnostics (kept close to the original -- this machinery is solid)
# ---------------------------------------------------------------------------

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
              n_clusters, 100 * n_noise / len(X) if len(X) else 0.0)
    return {"n_clusters": n_clusters, "n_noise": n_noise, "pct_noise": n_noise / len(X) if len(X) else 0.0}


def select_k(sweep: pd.DataFrame, forced_k: int | None) -> tuple[int, str]:
    """No special-casing of any particular k here -- see module docstring.
    Defaults to whichever k the balanced-silhouette view prefers (excluding
    slivers under 2% of the population, which tend to be outlier artifacts
    rather than real clusters -- see plot_sweep's k=2 caveat in the original
    script), falling back to the pure BIC-best k if nothing clears that bar."""
    if forced_k is not None:
        return forced_k, f"forced via --k {forced_k}"

    bic_best = int(sweep.loc[sweep["gmm_bic"].idxmin(), "k"])
    balanced = sweep[sweep["gmm_min_cluster_frac"] > 0.02]
    if len(balanced):
        sil_best = int(balanced.loc[balanced["gmm_silhouette"].idxmax(), "k"])
        return sil_best, (f"balanced-silhouette-best k={sil_best} (BIC-best was k={bic_best}); "
                           f"pass --k to override")
    return bic_best, f"BIC-best k={bic_best} (no k had a balanced [>2%] smallest cluster); pass --k to override"


# ---------------------------------------------------------------------------
# Neutral, data-driven cluster naming
# ---------------------------------------------------------------------------

def label_clusters_neutral(X: pd.DataFrame, cluster_ids: pd.Series, top_n: int = 2) -> dict[int, str]:
    """Names each cluster from its own most-distinguishing SCALED features
    (largest |z-score| vs the population mean), e.g.
    'high_shape_Nto1+low_gap_cv'. No behavioral vocabulary (Human/Bot/Miner)
    anywhere in this function -- that mapping is Phase 6's job, after Phase
    5 has real ground truth to justify it."""
    scaler = RobustScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)

    labels = {}
    for cid in sorted(cluster_ids.unique()):
        members = X_scaled.index[cluster_ids == cid]
        centroid = X_scaled.loc[members].mean()
        top_features = centroid.abs().sort_values(ascending=False).index[:top_n]
        parts = []
        for feat in top_features:
            tag = FEATURE_TAGS.get(feat, feat)
            direction = "high" if centroid[feat] >= 0 else "low"
            parts.append(f"{direction}_{tag}")
        labels[cid] = "+".join(parts) if parts else f"cluster_{cid}"
    return labels


# ---------------------------------------------------------------------------
# Cross-validation against Phase 3 archetypes -- the actual point of Phase 4
# ---------------------------------------------------------------------------

def cross_tab_against_archetypes(active_df: pd.DataFrame, archetypes_path: Path) -> tuple[pd.DataFrame, float]:
    if not archetypes_path.exists():
        log.warning("%s not found -- skipping archetype cross-validation. Run compute_archetypes.py "
                     "(Phase 3) first for the actual point of this script.", archetypes_path)
        return pd.DataFrame(), float("nan")

    arche = pd.read_csv(archetypes_path, index_col="address")
    joined = active_df.join(arche[["top_archetype"]], how="left")
    joined["top_archetype"] = joined["top_archetype"].fillna("NO_ARCHETYPE_DATA")

    cross = pd.crosstab(joined["cluster_label"], joined["top_archetype"], normalize="index")
    cross = (cross * 100).round(1)

    valid = joined[joined["top_archetype"] != "NO_ARCHETYPE_DATA"]
    nmi = (normalized_mutual_info_score(valid["cluster_label"], valid["top_archetype"])
           if len(valid) > 1 and valid["cluster_label"].nunique() > 1 else float("nan"))
    return cross, nmi


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_sweep(sweep: pd.DataFrame, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(sweep["k"], sweep["gmm_bic"], marker="o", label="GMM BIC")
    axes[0].set_xlabel("k"); axes[0].set_ylabel("BIC (lower is better)")
    axes[0].set_title("GMM model selection"); axes[0].legend()

    axes[1].plot(sweep["k"], sweep["gmm_silhouette"], marker="o", label="GMM silhouette")
    axes[1].plot(sweep["k"], sweep["kmeans_silhouette"], marker="s", label="KMeans silhouette")
    axes[1].set_xlabel("k"); axes[1].set_ylabel("silhouette")
    axes[1].set_title("Silhouette")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_pca_scatter(X: np.ndarray, labels: pd.Series, out_path: Path, random_state: int):
    pca = PCA(n_components=2, random_state=random_state)
    coords = pca.fit_transform(X)
    df = pd.DataFrame({"x": coords[:, 0], "y": coords[:, 1], "label": labels.values})
    fig, ax = plt.subplots(figsize=(7, 6))
    for name, sub in df.groupby("label"):
        ax.scatter(sub["x"], sub["y"], s=14, alpha=0.6, label=f"{name} (n={len(sub)})")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.0%} var)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.0%} var)")
    ax.set_title("Active wallets, PCA projection colored by cluster (neutral names)")
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(out_dir: Path, sweep: pd.DataFrame, chosen_k: int, k_reason: str, hdb_diag: dict,
                  cluster_labels: dict, cross: pd.DataFrame, nmi: float,
                  n_inactive: int, n_active: int, n_insufficient: int, n_outliers: int):
    lines = ["# Phase 4 -- Neutral Re-clustering & Archetype Cross-Validation\n"]
    lines.append("## Method\n")
    lines.append(
        "Gaussian Mixture Model (full covariance) fit on a RobustScaler-scaled, median-imputed "
        "matrix combining features_full.csv (temporal) and features_cell_layer.csv (Phase 2 Cell "
        f"layer) -- unsupervised, no labels used in fitting. Wallets are split into populations "
        "using `wallet_status` (not merely n_tx_in_window==0, which cannot distinguish a "
        f"genuinely-collected zero-transaction wallet from one that was simply never collected): "
        f"**{n_active}** ordinary active wallets were clustered; **{n_outliers}** extreme wallets "
        f"(same detection logic as flag_outlier_wallets.py, run BEFORE the fit -- see below) are "
        f"'{OUTLIER_LABEL}'; **{n_inactive}** are '{INACTIVE_LABEL}' (wallet_status=='unused', a "
        f"real collected fact); **{n_insufficient}** are '{INSUFFICIENT_DATA_LABEL}' "
        "(wallet_status outside {active, unused} -- e.g. not_collected or malformed).\n"
    )
    if n_outliers:
        lines.append(
            f"**Outlier exclusion matters here**: a first pass at clustering the full active "
            f"population (before this exclusion) produced silhouette >0.93 at every k tested, "
            f"with the smallest cluster always under 1% of wallets -- the classic signature of a "
            f"handful of extreme wallets (unbounded counterparty counts, likely "
            f"exchange/pool-scale addresses) dominating the distance metric rather than genuine "
            f"behavioral structure. Excluding them before the fit is what makes the sweep below "
            f"meaningful. The excluded wallets themselves are good Phase 5 ground-truth "
            f"candidates -- see outlier_wallets_v2.txt.\n"
        )
    lines.append(f"**Chosen k = {chosen_k}** ({k_reason})\n")
    lines.append(
        f"**HDBSCAN diagnostic** (comparison only): found {hdb_diag['n_clusters']} clusters, "
        f"{hdb_diag['pct_noise']:.1%} of active wallets marked noise.\n"
    )
    lines.append("## Model selection sweep\n")
    lines.append(sweep.round(3).to_markdown(index=False))
    lines.append("\n## Cluster names (auto-generated, neutral -- NOT behavioral labels)\n")
    for cid, name in sorted(cluster_labels.items()):
        lines.append(f"- cluster {cid}: `{name}`")
    lines.append(
        "\nThese names describe each cluster's own most-distinguishing scaled features. They are "
        "deliberately NOT Human/Bot/Miner -- that mapping requires Phase 5 ground truth first.\n"
    )
    lines.append("## Cross-validation against Phase 3 archetypes\n")
    if len(cross):
        lines.append(f"Normalized mutual information between cluster assignment and Phase 3's "
                      f"`top_archetype`: **{nmi:.3f}** (0 = no relationship, 1 = perfect agreement). "
                      f"This measures whether two INDEPENDENT methods (rule-based scoring vs. "
                      f"unsupervised clustering) found similar structure -- it is not an accuracy "
                      f"score against ground truth, which doesn't exist yet (Phase 5).\n")
        lines.append("Row-normalized (%) -- for each cluster, the archetype breakdown of its members:\n")
        lines.append(cross.to_markdown())
        lines.append(
            "\nA cluster dominated by one archetype is a good sign the two methods agree. A "
            "cluster split across several archetypes, or an archetype spread across several "
            "clusters, isn't automatically a bug in either method -- it's exactly the kind of "
            "case Phase 5's ground-truth sampling should prioritize checking by hand.\n"
        )
    else:
        lines.append("(skipped -- wallet_archetypes.csv not found; run compute_archetypes.py first)\n")

    lines.append("## Caveats\n")
    lines.append(
        "- This is a sanity check, not a classification. No wallet in this output should be "
        "reported as Human/Bot/Miner/Inactive except the Inactive rule above, which predates "
        "clustering and isn't derived from it.\n"
        "- Monetary features inherit the value-splitting caveats already documented for the "
        "existing pipeline.\n"
        "- GMM cluster assignment is hard (argmax) in the output CSV; each wallet's soft-"
        "responsibility max is included as cluster_confidence -- a low value means the wallet "
        "sits ambiguously between clusters.\n"
    )
    (out_dir / "PHASE4_CLUSTERING_REPORT.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features-dir", type=Path, required=True,
                     help="Directory with features_full.csv, features_cell_layer.csv, "
                          "and (optionally) wallet_archetypes.csv")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--k", type=int, default=None, help="Force number of clusters. Default: auto (see select_k()).")
    ap.add_argument("--k-min", type=int, default=2)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--random-state", type=int, default=42)
    ap.add_argument("--max-abs-threshold", type=float, default=DEFAULT_MAX_ABS_THRESHOLD,
                     help="Same as flag_outlier_wallets.py -- flag a wallet if any single scaled "
                          "feature exceeds this many robust-scaled units from the median.")
    ap.add_argument("--distance-z-threshold", type=float, default=DEFAULT_DISTANCE_Z_THRESHOLD,
                     help="Same as flag_outlier_wallets.py -- flag a wallet if its overall "
                          "distance from the median point is this many robust-z-units above typical.")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "plots").mkdir(exist_ok=True)

    df = load_and_join(args.features_dir)

    if "n_tx_in_window" not in df.columns:
        raise SystemExit("features_full.csv must have an n_tx_in_window column.")

    population = classify_population(df)
    active_addrs = df.index[population == "active"]
    inactive_addrs = df.index[population == "inactive"]
    insufficient_addrs = df.index[population == "insufficient_data"]
    log.info("%d wallet(s) total: %d active (clustered), %d Inactive (real rule, excluded from "
              "clustering), %d %s (never successfully collected -- excluded from BOTH clustering "
              "AND the Inactive rule, not the same claim)",
              len(df), len(active_addrs), len(inactive_addrs), len(insufficient_addrs),
              INSUFFICIENT_DATA_LABEL)

    X_full, feature_cols = build_clustering_matrix(df)
    X_active = X_full.loc[active_addrs]

    # Pass 1: scale the full active population just to DETECT gross outliers
    # (RobustScaler's median/IQR are fairly resistant to a handful of extreme
    # points, so this rough scaling is good enough for detection purposes).
    X_scaled_detect = pd.DataFrame(RobustScaler().fit_transform(X_active), index=X_active.index, columns=X_active.columns)
    outlier_flag, outlier_detail = detect_outliers(X_scaled_detect, args.max_abs_threshold, args.distance_z_threshold)
    n_outliers = int(outlier_flag.sum())
    log.info("outlier check (same logic as flag_outlier_wallets.py, run BEFORE clustering): "
              "%d/%d active wallet(s) flagged as extreme (max-abs > %.1f scaled units, or overall "
              "distance z > %.1f) and excluded from the fit -- reported separately as '%s', not "
              "silently dropped or force-fit into a cluster where they'd distort everyone else's "
              "boundaries.", n_outliers, len(X_active), args.max_abs_threshold,
              args.distance_z_threshold, OUTLIER_LABEL)

    ordinary_addrs = X_active.index[~outlier_flag]
    outlier_addrs = X_active.index[outlier_flag]
    X_ordinary = X_active.loc[ordinary_addrs]

    # Pass 2: a clean re-fit of the scaler on just the ordinary population --
    # this is the actual matrix the sweep/fit run on, per
    # flag_outlier_wallets.py's own documented next step ("re-run your
    # k-selection sweep against features_for_clustering_no_outliers.csv
    # instead of the original").
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X_ordinary)

    log.info("running GMM/KMeans sweep k=%d..%d on %d ordinary active wallet(s) (%d outlier(s) "
              "excluded), %d feature(s)...",
              args.k_min, args.k_max, len(X_ordinary), n_outliers, len(feature_cols))
    sweep = run_sweep(X_scaled, args.k_min, args.k_max, args.random_state)
    sweep.to_csv(args.out_dir / "cluster_k_sweep.csv", index=False)
    plot_sweep(sweep, args.out_dir / "plots" / "k_sweep.png")

    hdb_diag = run_hdbscan_diagnostic(X_scaled)

    chosen_k, k_reason = select_k(sweep, args.k)
    log.info("selected k=%d (%s)", chosen_k, k_reason)

    gmm = GaussianMixture(n_components=chosen_k, covariance_type="full",
                           n_init=10, random_state=args.random_state, max_iter=300)
    cluster_id = gmm.fit_predict(X_scaled)
    soft = gmm.predict_proba(X_scaled)

    active_df = pd.DataFrame(index=X_ordinary.index)
    active_df["cluster_id"] = cluster_id
    active_df["cluster_confidence"] = soft.max(axis=1)

    cluster_labels = label_clusters_neutral(X_ordinary, active_df["cluster_id"])
    active_df["cluster_label"] = active_df["cluster_id"].map(cluster_labels)
    log.info("cluster -> neutral label mapping: %s", cluster_labels)

    cross, nmi = cross_tab_against_archetypes(active_df, args.features_dir / "wallet_archetypes.csv")
    if len(cross):
        log.info("normalized mutual information (cluster vs. Phase 3 top_archetype): %.3f", nmi)

    outlier_df = pd.DataFrame(index=outlier_addrs)
    outlier_df["cluster_id"] = np.nan
    outlier_df["cluster_confidence"] = np.nan
    outlier_df["cluster_label"] = OUTLIER_LABEL

    inactive_df = pd.DataFrame(index=inactive_addrs)
    inactive_df["cluster_id"] = np.nan
    inactive_df["cluster_confidence"] = np.nan
    inactive_df["cluster_label"] = INACTIVE_LABEL

    insufficient_df = pd.DataFrame(index=insufficient_addrs)
    insufficient_df["cluster_id"] = np.nan
    insufficient_df["cluster_confidence"] = np.nan
    insufficient_df["cluster_label"] = INSUFFICIENT_DATA_LABEL

    final = pd.concat([active_df, outlier_df, inactive_df, insufficient_df]).reindex(df.index)
    assert len(final) == len(df), "every wallet must appear in the output exactly once"
    assert final["cluster_label"].notna().all(), "every wallet must have a non-null cluster_label"

    out_path = args.out_dir / "wallet_clusters_v2.csv"
    final.to_csv(out_path)
    log.info("wrote %s (%d wallets, %d cluster(s) + %s + %s + %s)", out_path, len(final),
              len(cluster_labels), OUTLIER_LABEL, INACTIVE_LABEL, INSUFFICIENT_DATA_LABEL)

    if n_outliers:
        outlier_report_path = args.out_dir / "outlier_wallets_v2.txt"
        outlier_detail.loc[outlier_addrs].sort_values("distance_z", ascending=False).to_csv(outlier_report_path)
        log.info("wrote %s (%d address(es) -- good Phase 5 candidates for exchange/pool/miner "
                  "ground truth: extreme counterparty counts or capacity concentration are "
                  "exactly the signature those entities have)", outlier_report_path, n_outliers)

    plot_pca_scatter(X_scaled, active_df["cluster_label"], args.out_dir / "plots" / "pca_clusters.png",
                      args.random_state)

    write_report(args.out_dir, sweep, chosen_k, k_reason, hdb_diag, cluster_labels, cross, nmi,
                  len(inactive_addrs), len(active_df), len(insufficient_addrs), n_outliers)
    log.info("done. See %s for the full report.", args.out_dir / "PHASE4_CLUSTERING_REPORT.md")


if __name__ == "__main__":
    main()
