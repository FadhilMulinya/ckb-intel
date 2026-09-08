import json
import logging
import argparse
from collections import Counter

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

import config
import labeling
from features import FEATURE_COLUMNS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("ckb_wallet_intel.cluster_model")

DATASET_PATH = f"{config.PROCESSED_DIR}/wallet_dataset.csv"
SCALER_PATH = f"{config.MODELS_DIR}/cluster_scaler.joblib"
MODEL_PATH = f"{config.MODELS_DIR}/cluster_model.joblib"
PROFILES_PATH = f"{config.MODELS_DIR}/cluster_profiles.json"
FEATURE_COLUMNS_PATH = f"{config.MODELS_DIR}/cluster_feature_columns.json"


CLUSTER_FEATURE_COLUMNS = [c for c in FEATURE_COLUMNS if c not in ("is_inactive",)]


FEATURE_PHRASES = {
    "periodicity_strength": ("fires on a stable repeating schedule", "no detectable schedule"),
    "interarrival_cv": ("irregular timing between transactions", "very consistent timing between transactions"),
    "burstiness": ("activity comes in dense bursts", "activity is spread evenly over time"),
    "fanout_tx_ratio": ("frequently pays out to many recipients at once", "rarely pays multiple recipients at once"),
    "fanin_tx_ratio": ("frequently aggregates funds from many sources", "rarely aggregates from multiple sources"),
    "topology_repetition": ("repeats the same transaction shape over and over", "varies its transaction shape"),
    "cellbase_reward_ratio": ("receives block/mining rewards directly", "never receives mining rewards"),
    "dao_capacity_share": ("holds most value in Nervos DAO deposits", "little to no DAO activity"),
    "udt_capacity_share": ("actively moves UDT/token cells", "little to no token activity"),
    "capacity_fragmentation": ("splits capacity into many small cells", "rarely splits capacity"),
    "capacity_consolidation": ("consolidates many cells into one", "rarely consolidates cells"),
    "round_trip_partner_ratio": ("counterparties often send funds back (round-trip)", "counterparties rarely send funds back"),
    "short_lived_cell_ratio": ("spends newly-created cells almost immediately", "rarely spends cells immediately"),
    "long_lived_cell_ratio": ("holds cells for long periods before spending", "rarely holds cells long-term"),
    "capacity_turnover": ("moves a large amount of total capacity", "moves relatively little capacity"),
    "fanout_dest_count": ("has a large number of distinct payees", "has few distinct payees"),
    "fanin_source_count": ("has a large number of distinct payers", "has few distinct payers"),
    "same_block_spend_ratio": ("often spends a cell in the same block it was created", "rarely same-block spends"),
}


def load_clusterable_frame(path=None):
    path = path or DATASET_PATH
    df = pd.read_csv(path)
    excluded = df[(df["evidence_state"] == "INSUFFICIENT_EVIDENCE") | (df["is_inactive"] == 1)].copy()
    clusterable = df[~df.index.isin(excluded.index)].copy()
    logger.info("Loaded %d wallets: %d clusterable, %d excluded (inactive/insufficient evidence)",
                len(df), len(clusterable), len(excluded))
    missing = [c for c in CLUSTER_FEATURE_COLUMNS if c not in clusterable.columns]
    if missing:
        raise ValueError(f"Dataset missing expected feature columns: {missing}")
    return clusterable, excluded


def choose_k(X_scaled, k_min=3, k_max=10, random_state=42):
    k_max = min(k_max, max(k_min, len(X_scaled) // 3))  
    if k_max < k_min:
        return k_min, {}
    scores = {}
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit(X_scaled)
        if len(set(km.labels_)) < 2:
            continue
        scores[k] = silhouette_score(X_scaled, km.labels_)
    if not scores:
        return k_min, {}
    best_k = max(scores, key=scores.get)
    logger.info("Silhouette scores by k: %s -> chose k=%d", {k: round(v, 3) for k, v in scores.items()}, best_k)
    return best_k, scores


def _top_distinguishing_features(cluster_mean, global_mean, global_std, top_n=6):
    z_scores = {}
    for f in CLUSTER_FEATURE_COLUMNS:
        std = global_std.get(f, 0.0)
        if std < 1e-9:
            continue
        z_scores[f] = (cluster_mean[f] - global_mean[f]) / std
    ranked = sorted(z_scores.items(), key=lambda kv: -abs(kv[1]))[:top_n]
    return ranked  


def _describe_cluster(ranked_features):
    phrases = []
    for feature, z in ranked_features:
        if abs(z) < 0.4:
            continue
        high, low = FEATURE_PHRASES.get(feature, (f"high {feature}", f"low {feature}"))
        phrases.append(high if z > 0 else low)
    if not phrases:
        return "No strongly distinguishing behaviour vs. the rest of the sampled population."
    return "Typically " + "; ".join(phrases) + "."


def build_cluster_profiles(df: pd.DataFrame, labels: np.ndarray):
    df = df.copy()
    df["cluster"] = labels
    global_mean = df[CLUSTER_FEATURE_COLUMNS].mean()
    global_std = df[CLUSTER_FEATURE_COLUMNS].std().replace(0, np.nan)

    
    heuristic_labels = []
    for _, row in df.iterrows():
        feat = {c: row[c] for c in CLUSTER_FEATURE_COLUMNS}
        feat["is_inactive"] = 0.0
        meta = {
            "transactions_observed": row["transactions_observed"],
            "evidence_state": row["evidence_state"],
            "periodicity_evidence": row["periodicity_evidence"],
        }
        lbl, _, _ = labeling.heuristic_label(feat, meta)
        heuristic_labels.append(lbl)
    df["_heuristic_hint"] = heuristic_labels

    profiles = {}
    for cluster_id in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == cluster_id]
        cluster_mean = sub[CLUSTER_FEATURE_COLUMNS].mean()
        ranked = _top_distinguishing_features(cluster_mean, global_mean, global_std)
        description = _describe_cluster(ranked)

        vote_counts = Counter(sub["_heuristic_hint"])
        dominant_label, dominant_count = vote_counts.most_common(1)[0]
        purity = dominant_count / len(sub)
        suggested_name = dominant_label if purity >= 0.5 else "MIXED_" + "_".join(
            f.upper().split("_")[0] for f, _ in ranked[:2]
        )

        profiles[str(cluster_id)] = {
            "cluster_id": int(cluster_id),
            "n_wallets": int(len(sub)),
            "suggested_archetype": suggested_name,
            "purity": round(float(purity), 3),
            "heuristic_vote_breakdown": dict(vote_counts),
            "description": description,
            "top_distinguishing_features": [{"feature": f, "z_score": round(float(z), 2)} for f, z in ranked],
            "feature_means": {f: round(float(cluster_mean[f]), 4) for f in CLUSTER_FEATURE_COLUMNS},
            "example_addresses": sub["address"].head(5).tolist(),
        }
    return profiles


def fit(n_blocks_note=None, k_min=3, k_max=10, random_state=42):
    clusterable, excluded = load_clusterable_frame()
    if len(clusterable) < k_min * 3:
        raise ValueError(
            f"Only {len(clusterable)} clusterable wallets - need at least {k_min * 3} "
            f"for a meaningful clustering. Widen --per-bucket in dataset.py and re-run."
        )

    X = clusterable[CLUSTER_FEATURE_COLUMNS].fillna(0.0).values
    scaler = StandardScaler().fit(X)
    X_scaled = scaler.transform(X)

    best_k, silhouette_scores = choose_k(X_scaled, k_min=k_min, k_max=k_max, random_state=random_state)
    km = KMeans(n_clusters=best_k, n_init=10, random_state=random_state).fit(X_scaled)

    profiles = build_cluster_profiles(clusterable, km.labels_)

    joblib.dump(scaler, SCALER_PATH)
    joblib.dump(km, MODEL_PATH)
    with open(PROFILES_PATH, "w") as f:
        json.dump(profiles, f, indent=2)
    with open(FEATURE_COLUMNS_PATH, "w") as f:
        json.dump(CLUSTER_FEATURE_COLUMNS, f)

    logger.info("Fitted k=%d clusters over %d wallets (%d excluded as inactive/insufficient evidence)",
                best_k, len(clusterable), len(excluded))
    for cid, p in profiles.items():
        logger.info("Cluster %s (n=%d): %s [purity=%.2f]\n    %s",
                    cid, p["n_wallets"], p["suggested_archetype"], p["purity"], p["description"])

    return scaler, km, profiles, silhouette_scores


def load_artifacts():
    scaler = joblib.load(SCALER_PATH)
    km = joblib.load(MODEL_PATH)
    with open(PROFILES_PATH) as f:
        profiles = json.load(f)
    with open(FEATURE_COLUMNS_PATH) as f:
        feature_columns = json.load(f)
    return scaler, km, profiles, feature_columns


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Discover CKB wallet behaviour clusters (unsupervised).")
    p.add_argument("--dataset", default=DATASET_PATH)
    p.add_argument("--k-min", type=int, default=3)
    p.add_argument("--k-max", type=int, default=10)
    args = p.parse_args()
    fit(k_min=args.k_min, k_max=args.k_max)
