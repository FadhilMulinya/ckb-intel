from __future__ import annotations

"""
Phase 5 of the gap-closure plan (see CKB_Wallet_Classifier_Gap_Closure_Plan.md,
section 3, Phase 5): this is fundamentally a MANUAL task -- hand-verifying a
small (30-50 per class) ground-truth sample against a block explorer. This
script does the part that can be automated: turning Phases 3/4's outputs
into a stratified, ready-to-annotate candidate list, so the manual work is
spent looking things up, not deciding what to look up.

Candidate pools, and why each one is selected the way it is:

  bot_candidates          -- top-confidence is_scripted / PERIODIC_EXECUTION
                             wallets PLUS a random sample from the same pool
                             at lower confidence. Only sampling the top
                             scorers would cherry-pick the easiest cases and
                             tell you nothing about where the threshold
                             actually breaks down.
  human_candidates        -- same stratified top+random sampling on
                             IRREGULAR_ACTIVITY.
  miner_exchange_candidates -- from Phase 4's outlier_wallets_v2.txt
                             (extreme counterparty count / capacity
                             concentration -- the actual signature these
                             entities have) plus any direct-cellbase-touch
                             wallets from Phase 3. This is your best lead
                             for the hardest class given the plan's own
                             repeated warning that miner detection needs
                             more than what's in this dataset.
  inactive_qa_sample      -- a small spot-check sample of wallet_status ==
                             'unused' wallets. Not really "ground truth"
                             (the rule is already exact) -- this is a
                             sanity check that the rule matches real-world
                             intuition, not a validation exercise.
  disagreement_candidates -- wallets whose OWN top_archetype does NOT match
                             their cluster's dominant archetype (per Phase
                             4's cross-tab). Per the gap-closure plan:
                             "disagreement isn't automatically a bug in
                             either method -- it's exactly the kind of case
                             Phase 5 should prioritize checking." These are
                             the highest-information wallets to hand-verify,
                             not the easiest.

Usage:
    python3 select_ground_truth_candidates.py \
        --features-dir ./ckb_features --clustering-dir ./ckb_clustering_v2 \
        --out ./ground_truth_candidates.csv --n-per-pool 20
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("select_ground_truth_candidates")

EXPLORER_ADDRESS_URL = "https://explorer.nervos.org/address/{address}"

CANDIDATE_COLUMNS = [
    "address", "candidate_pool", "source_signal", "explorer_url",
    "top_archetype", "top_score", "is_scripted", "cluster_label",
    "touches_cellbase_directly", "wallet_status",
    "verified_label", "verified_notes", "verified_by", "verified_date",
]


def stratified_sample(df: pd.DataFrame, score_col: str, n: int, top_frac: float, random_state: int) -> pd.DataFrame:
    """Top-scorers (the easy/confident cases) + a random sample from the
    rest (the cases that actually test where the rule breaks down). Purely
    top-N sampling would only ever validate the model's most confident
    predictions, which tells you nothing about its error rate."""
    df = df.dropna(subset=[score_col]).sort_values(score_col, ascending=False)
    if len(df) <= n:
        return df
    n_top = max(1, int(round(n * top_frac)))
    n_random = n - n_top
    top = df.iloc[:n_top]
    remainder = df.iloc[n_top:]
    random_part = remainder.sample(n=min(n_random, len(remainder)), random_state=random_state)
    return pd.concat([top, random_part])


def build_bot_and_human_pools(archetypes: pd.DataFrame, n_per_pool: int, random_state: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    bot_pool = archetypes[
        (archetypes["top_archetype"] == "PERIODIC_EXECUTION") | (archetypes.get("is_scripted") == True)
    ].copy()
    bot_pool["source_signal"] = bot_pool.apply(
        lambda r: f"top_archetype={r['top_archetype']} score={r.get('top_score', float('nan')):.2f}"
                  f"{' is_scripted' if r.get('is_scripted') else ''}", axis=1)
    bot_sample = stratified_sample(bot_pool, "top_score", n_per_pool, top_frac=0.5, random_state=random_state)

    human_pool = archetypes[archetypes["top_archetype"] == "IRREGULAR_ACTIVITY"].copy()
    human_pool["source_signal"] = human_pool.apply(
        lambda r: f"top_archetype=IRREGULAR_ACTIVITY score={r.get('top_score', float('nan')):.2f}", axis=1)
    human_sample = stratified_sample(human_pool, "top_score", n_per_pool, top_frac=0.5, random_state=random_state)

    return bot_sample, human_sample


def build_miner_exchange_pool(archetypes: pd.DataFrame, outlier_path: Path, n_per_pool: int) -> pd.DataFrame:
    parts = []
    if outlier_path.exists():
        outliers = pd.read_csv(outlier_path, index_col=0)
        outliers = outliers.sort_values("distance_z", ascending=False).head(n_per_pool)
        outliers["source_signal"] = outliers.apply(
            lambda r: f"outlier distance_z={r['distance_z']:.1f} worst_feature={r['worst_feature']}", axis=1)
        parts.append(outliers[["source_signal"]])
    else:
        log.warning("%s not found -- run cluster_wallets_v2.py (Phase 4) first for outlier candidates.", outlier_path)

    if "touches_cellbase_directly" in archetypes.columns:
        cellbase = archetypes[archetypes["touches_cellbase_directly"] == True].copy()
        if len(cellbase):
            cellbase["source_signal"] = "direct cellbase input touch"
            parts.append(cellbase[["source_signal"]])

    if not parts:
        return pd.DataFrame(columns=["source_signal"])
    combined = pd.concat(parts)
    return combined[~combined.index.duplicated(keep="first")]


def build_inactive_qa_sample(full_features: pd.DataFrame, n: int, random_state: int) -> pd.DataFrame:
    if "wallet_status" not in full_features.columns:
        return pd.DataFrame(columns=["source_signal"])
    inactive = full_features[full_features["wallet_status"] == "unused"].copy()
    if not len(inactive):
        return pd.DataFrame(columns=["source_signal"])
    sample = inactive.sample(n=min(n, len(inactive)), random_state=random_state)
    sample["source_signal"] = "wallet_status=unused (spot-check, not a validation exercise)"
    return sample[["source_signal"]]


def build_disagreement_pool(archetypes: pd.DataFrame, clusters: pd.DataFrame, n: int, random_state: int) -> pd.DataFrame:
    """Wallets whose own top_archetype does NOT match their cluster's
    dominant archetype -- per the plan, these are the highest-information
    cases to hand-verify, not the easiest."""
    if clusters is None or "cluster_label" not in clusters.columns:
        return pd.DataFrame(columns=["source_signal"])

    joined = clusters[["cluster_label"]].join(archetypes[["top_archetype"]], how="inner")
    joined = joined[~joined["cluster_label"].isin(["Inactive", "Insufficient_Data", "Outlier_Excluded"])]
    joined = joined[joined["top_archetype"] != "INSUFFICIENT_EVIDENCE"]
    if not len(joined):
        return pd.DataFrame(columns=["source_signal"])

    dominant = joined.groupby("cluster_label")["top_archetype"].agg(lambda s: s.value_counts().idxmax())
    joined["cluster_dominant_archetype"] = joined["cluster_label"].map(dominant)
    disagreement = joined[joined["top_archetype"] != joined["cluster_dominant_archetype"]].copy()
    if not len(disagreement):
        return pd.DataFrame(columns=["source_signal"])

    disagreement["source_signal"] = disagreement.apply(
        lambda r: f"cluster={r['cluster_label']} (dominant archetype={r['cluster_dominant_archetype']}) "
                  f"but this wallet's own top_archetype={r['top_archetype']}", axis=1)
    sample = disagreement.sample(n=min(n, len(disagreement)), random_state=random_state)
    return sample[["source_signal"]]


def assemble_candidates(pools: dict[str, pd.DataFrame], archetypes: pd.DataFrame,
                          clusters: pd.DataFrame | None, full_features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pool_name, pool_df in pools.items():
        for address, row in pool_df.iterrows():
            rows.append({
                "address": address,
                "candidate_pool": pool_name,
                "source_signal": row.get("source_signal", ""),
            })
    if not rows:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)

    out = pd.DataFrame(rows).drop_duplicates(subset=["address", "candidate_pool"]).set_index("address")
    out["explorer_url"] = [EXPLORER_ADDRESS_URL.format(address=a) for a in out.index]

    for col in ("top_archetype", "top_score", "is_scripted", "touches_cellbase_directly"):
        if col in archetypes.columns:
            out[col] = archetypes[col].reindex(out.index)
    if clusters is not None and "cluster_label" in clusters.columns:
        out["cluster_label"] = clusters["cluster_label"].reindex(out.index)
    if "wallet_status" in full_features.columns:
        out["wallet_status"] = full_features["wallet_status"].reindex(out.index)

    for col in ("verified_label", "verified_notes", "verified_by", "verified_date"):
        out[col] = ""

    out = out.reset_index()
    for col in CANDIDATE_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan
    return out[CANDIDATE_COLUMNS]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features-dir", type=Path, required=True,
                     help="Directory with features_full.csv and wallet_archetypes.csv")
    ap.add_argument("--clustering-dir", type=Path, default=None,
                     help="Directory with wallet_clusters_v2.csv and outlier_wallets_v2.txt "
                          "(from cluster_wallets_v2.py). Optional -- disagreement and "
                          "miner/exchange pools are skipped without it.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-per-pool", type=int, default=20,
                     help="Target candidates per pool. Aim for the total across bot+human+"
                          "miner_exchange to land in the 30-50 per CLASS the plan recommends -- "
                          "this script produces candidates, not final verified counts.")
    ap.add_argument("--random-state", type=int, default=0)
    args = ap.parse_args()

    archetypes_path = args.features_dir / "wallet_archetypes.csv"
    full_path = args.features_dir / "features_full.csv"
    if not archetypes_path.exists():
        raise SystemExit(f"no such file: {archetypes_path} -- run compute_archetypes.py (Phase 3) first.")
    if not full_path.exists():
        raise SystemExit(f"no such file: {full_path} -- run preprocess_ckb_wallets.py first.")

    archetypes = pd.read_csv(archetypes_path, index_col="address")
    full_features = pd.read_csv(full_path, index_col="address")

    clusters = None
    outlier_path = Path("/nonexistent")
    if args.clustering_dir:
        clusters_path = args.clustering_dir / "wallet_clusters_v2.csv"
        outlier_path = args.clustering_dir / "outlier_wallets_v2.txt"
        if clusters_path.exists():
            clusters = pd.read_csv(clusters_path, index_col="address")
        else:
            log.warning("%s not found -- disagreement pool will be skipped.", clusters_path)

    bot_sample, human_sample = build_bot_and_human_pools(archetypes, args.n_per_pool, args.random_state)
    miner_exchange_sample = build_miner_exchange_pool(archetypes, outlier_path, args.n_per_pool)
    inactive_sample = build_inactive_qa_sample(full_features, min(10, args.n_per_pool), args.random_state)
    disagreement_sample = build_disagreement_pool(archetypes, clusters, args.n_per_pool, args.random_state)

    pools = {
        "bot_candidate": bot_sample,
        "human_candidate": human_sample,
        "miner_exchange_candidate": miner_exchange_sample,
        "inactive_qa_sample": inactive_sample,
        "disagreement_candidate": disagreement_sample,
    }

    candidates = assemble_candidates(pools, archetypes, clusters, full_features)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(args.out, index=False)

    print(f"\nWrote {args.out} ({len(candidates)} candidate(s))\n")
    print("=== Candidates per pool ===")
    for pool_name, pool_df in pools.items():
        print(f"  {pool_name:<26s} {len(pool_df):4d}")

    print(
        "\nNext: open explorer_url for each row, look up the address's real transaction history, "
        "and fill in verified_label (Human / Bot / Miner / Exchange / Inactive / Unclear), "
        "verified_notes, verified_by, verified_date. For miner_exchange_candidate specifically, "
        "also check https://explorer.nervos.org/charts (Top Miners chart, renders in-browser only) "
        "and known pool names (2Miners, F2Pool, AntPool, DxPool, ViaBTC, Poolin, HashPool) against "
        "the address's counterparty list -- this dataset alone doesn't have strong miner signal "
        "(see the gap-closure plan's repeated caution that miner detection needs Cell lineage back "
        "to cellbase, which Phase 1 could only partially resolve).\n"
        "\nAim for 30-50 CONFIRMED examples per class once verified -- this script gives you more "
        "candidates than that per pool on purpose, since not every candidate will turn out to be a "
        "clean, confident example once you actually look at it."
    )


if __name__ == "__main__":
    main()
