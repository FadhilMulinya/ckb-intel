"""
Sanity tests for Phase 4 (cluster_wallets_v2.py). Builds a synthetic
population with two genuinely distinct behavioral clusters (a periodic/
scripted group and an irregular/human-like group) plus a batch of inactive
wallets, and checks:
  - select_k() doesn't secretly prefer k=3 -- it should recover k=2 for a
    genuinely bimodal population.
  - label_clusters_neutral() never emits Human/Bot/Miner vocabulary.
  - Inactive wallets are excluded from clustering and handled as a rule.
  - The archetype cross-tab against a synthetic wallet_archetypes.csv works
    and produces a sane NMI.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cluster_wallets_v2 as cw

FORBIDDEN_WORDS = ["human", "bot", "miner", "dormant"]


def build_synthetic_features(n_per_group: int = 60, n_inactive: int = 20, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    def make_group(prefix, n, gap_cv_center, shape_1to1_center, lock_count_center):
        idx = [f"{prefix}_{i}" for i in range(n)]
        # Realistic multi-feature separation: a scripted/bot profile differs
        # from an irregular/human profile across SEVERAL correlated
        # dimensions at once (timing regularity AND time-of-day concentration
        # AND burstiness), not just one -- matching how real archetypes
        # actually separate. A single-feature difference drowns in the noise
        # of ~29 other columns (found by running this fixture: with only
        # gap_cv/shape_1_to_1_ratio varying, GMM partitioned on unrelated
        # noise columns instead, since they outnumbered the real signal).
        is_scripted = gap_cv_center < 0.5
        entropy_center = 0.15 if is_scripted else 0.75
        burstiness_center = -0.6 if is_scripted else 0.6
        return pd.DataFrame({
            "address": idx,
            "n_tx_in_window": rng.integers(10, 50, n),
            "tx_per_window_day": rng.normal(2, 0.3, n).clip(0.1),
            "gap_cv": rng.normal(gap_cv_center, 0.05, n).clip(0.01, 2),
            "burstiness": rng.normal(burstiness_center, 0.1, n),
            "hour_of_day_entropy": rng.normal(entropy_center, 0.05, n).clip(0, 1),
            "day_of_week_entropy": rng.normal(entropy_center, 0.05, n).clip(0, 1),
            "sent_total_ckb": rng.uniform(100, 10000, n),
            "received_total_ckb": rng.uniform(100, 10000, n),
            "max_single_tx_ckb": rng.uniform(100, 5000, n),
            "unique_counterparties_out": rng.integers(1, 10, n),
            "unique_counterparties_in": rng.integers(1, 10, n),
            "reciprocity_ratio": rng.uniform(0, 0.3, n),
            "out_value_concentration_hhi": rng.uniform(0.1, 0.9, n),
            "in_value_concentration_hhi": rng.uniform(0.1, 0.9, n),
        }).set_index("address")

    def make_cell_group(prefix, n, shape_1to1_center):
        idx = [f"{prefix}_{i}" for i in range(n)]
        is_scripted = shape_1to1_center > 0.5
        lifetime_cv_center = 0.1 if is_scripted else 0.9
        since_center = 0.9 if is_scripted else 0.1
        same_block_center = 0.7 if is_scripted else 0.1
        return pd.DataFrame({
            "address": idx,
            "shape_1_to_1_ratio": rng.normal(shape_1to1_center, 0.05, n).clip(0, 1),
            "shape_1_to_n_ratio": rng.uniform(0, 0.1, n),
            "shape_n_to_1_ratio": rng.uniform(0, 0.1, n),
            "shape_n_to_n_ratio": rng.uniform(0, 0.1, n),
            "cell_lifetime_cv": rng.normal(lifetime_cv_center, 0.05, n).clip(0, 2),
            "same_block_spend_ratio": rng.normal(same_block_center, 0.05, n).clip(0, 1),
            "n_distinct_lock_hashes": np.ones(n),
            "multisig_usage_ratio": np.zeros(n),
            "has_type_script_ratio": rng.uniform(0, 0.2, n),
            "uses_since_ratio": rng.normal(since_center, 0.05, n).clip(0, 1),
            "repeated_since_value_ratio": rng.normal(since_center, 0.05, n).clip(0, 1),
            "unique_counterparties_out_cell": rng.integers(1, 10, n),
            "unique_counterparties_in_cell": rng.integers(1, 10, n),
            "reciprocity_ratio_cell": rng.uniform(0, 0.3, n),
            "out_capacity_concentration_hhi_cell": rng.uniform(0.1, 0.9, n),
            "out_capacity_entropy_cell": rng.uniform(0.1, 0.9, n),
            "sent_capacity_ckb_cell": rng.uniform(100, 10000, n),
            "received_capacity_ckb_cell": rng.uniform(100, 10000, n),
            "net_capacity_delta_ckb_cell": rng.normal(0, 100, n),
        }).set_index("address")

    scripted_full = make_group("scripted", n_per_group, gap_cv_center=0.05, shape_1to1_center=0.95, lock_count_center=1)
    scripted_cell = make_cell_group("scripted", n_per_group, shape_1to1_center=0.97)

    irregular_full = make_group("irregular", n_per_group, gap_cv_center=1.2, shape_1to1_center=0.3, lock_count_center=1)
    irregular_cell = make_cell_group("irregular", n_per_group, shape_1to1_center=0.2)

    inactive_full = pd.DataFrame({
        "address": [f"inactive_{i}" for i in range(n_inactive)],
        "n_tx_in_window": np.zeros(n_inactive),
        "wallet_status": ["unused"] * n_inactive,
    }).set_index("address")

    scripted_full["wallet_status"] = "active"
    irregular_full["wallet_status"] = "active"

    full_df = pd.concat([scripted_full, irregular_full, inactive_full])
    cell_df = pd.concat([scripted_cell, irregular_cell])  # inactive wallets never ran Phase 2
    return full_df, cell_df


def test_no_forbidden_vocabulary_and_bimodal_k():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        full_df, cell_df = build_synthetic_features()
        full_df.to_csv(out / "features_full.csv")
        cell_df.to_csv(out / "features_cell_layer.csv")

        df = cw.load_and_join(out)
        inactive_mask = df["n_tx_in_window"].fillna(0) <= 0
        active_addrs = df.index[~inactive_mask]
        assert inactive_mask.sum() == 20
        print("OK: 20 inactive wallets correctly identified for exclusion from clustering")

        X_full, feature_cols = cw.build_clustering_matrix(df)
        X_active = X_full.loc[active_addrs]
        from sklearn.preprocessing import RobustScaler
        X_scaled = RobustScaler().fit_transform(X_active)

        sweep = cw.run_sweep(X_scaled, k_min=2, k_max=6, random_state=0)
        chosen_k, reason = cw.select_k(sweep, forced_k=None)
        assert chosen_k == 2, f"expected select_k to recover k=2 for a genuinely bimodal population, got {chosen_k}"
        print(f"OK: select_k() recovered k=2 for a genuinely bimodal population without any "
              f"special-casing toward k=3 ({reason})")

        gmm_final = __import__("sklearn.mixture", fromlist=["GaussianMixture"]).GaussianMixture(
            n_components=chosen_k, covariance_type="full", n_init=10, random_state=0)
        cluster_id = pd.Series(gmm_final.fit_predict(X_scaled), index=X_active.index)

        labels = cw.label_clusters_neutral(X_active, cluster_id)
        assert len(labels) == 2
        for name in labels.values():
            lowered = name.lower()
            for forbidden in FORBIDDEN_WORDS:
                assert forbidden not in lowered, (
                    f"cluster name '{name}' contains forbidden behavioral vocabulary '{forbidden}' -- "
                    f"Phase 4 must never assign Human/Bot/Miner/Dormant names, only Phase 6 can, "
                    f"after Phase 5 ground truth"
                )
        print(f"OK: auto-generated cluster names are neutral, no forbidden vocabulary: {list(labels.values())}")

        # The two real groups should mostly land in different clusters (not
        # asserting perfect separation, just that it's clearly non-random).
        scripted_ids = cluster_id.loc[cluster_id.index.str.startswith("scripted")]
        irregular_ids = cluster_id.loc[cluster_id.index.str.startswith("irregular")]
        scripted_majority = scripted_ids.value_counts().iloc[0] / len(scripted_ids)
        irregular_majority = irregular_ids.value_counts().iloc[0] / len(irregular_ids)
        assert scripted_majority > 0.8, scripted_ids.value_counts()
        assert irregular_majority > 0.8, irregular_ids.value_counts()
        print(f"OK: the two synthetic behavioral groups landed predominantly in separate clusters "
              f"({scripted_majority:.0%} / {irregular_majority:.0%} majority)")


def test_cross_tab_against_archetypes():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        full_df, cell_df = build_synthetic_features(n_per_group=30, n_inactive=5)
        full_df.to_csv(out / "features_full.csv")
        cell_df.to_csv(out / "features_cell_layer.csv")

        # Synthetic archetypes file: scripted_* -> PERIODIC_EXECUTION,
        # irregular_* -> IRREGULAR_ACTIVITY, matching the real behavioral
        # design of the synthetic population.
        addrs = list(cell_df.index)
        top_archetype = ["PERIODIC_EXECUTION" if a.startswith("scripted") else "IRREGULAR_ACTIVITY" for a in addrs]
        pd.DataFrame({"address": addrs, "top_archetype": top_archetype}).set_index("address").to_csv(
            out / "wallet_archetypes.csv")

        active_df = pd.DataFrame(index=addrs)
        active_df["cluster_label"] = ["cluster_A" if a.startswith("scripted") else "cluster_B" for a in addrs]

        cross, nmi = cw.cross_tab_against_archetypes(active_df, out / "wallet_archetypes.csv")
        assert not cross.empty
        assert nmi > 0.5, f"expected strong agreement (NMI) for a population where clusters perfectly " \
                           f"track archetypes, got {nmi:.3f}"
        print(f"OK: cross-tab against archetypes works, NMI={nmi:.3f} correctly reflects strong "
              f"agreement between independent cluster and archetype assignments")
        print(cross.to_string())


def test_missing_archetypes_file_does_not_crash():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        active_df = pd.DataFrame(index=["a", "b"])
        active_df["cluster_label"] = ["x", "y"]
        cross, nmi = cw.cross_tab_against_archetypes(active_df, out / "wallet_archetypes.csv")
        assert cross.empty
        assert nmi != nmi  # NaN
        print("OK: missing wallet_archetypes.csv handled gracefully (empty cross-tab, NaN NMI, no crash)")


def test_insufficient_data_not_conflated_with_inactive():
    """Regression test for the real bug the user caught: a wallet that was
    never successfully collected (wallet_status == 'not_collected', so
    n_tx_in_window is NaN) must NOT be labeled Inactive -- that would
    misrepresent a data-collection gap as a behavioral fact. It must show
    up as its own separate 'insufficient_data' population, excluded from
    BOTH clustering and the Inactive rule."""
    full_df, cell_df = build_synthetic_features(n_per_group=10, n_inactive=5)
    # Add wallets that were never collected -- distinct from genuinely
    # inactive (unused) wallets.
    not_collected = pd.DataFrame({
        "address": ["skipped_1", "skipped_2"],
        "n_tx_in_window": [np.nan, np.nan],
        "wallet_status": ["not_collected", "not_collected"],
    }).set_index("address")
    full_df = pd.concat([full_df, not_collected])

    population = cw.classify_population(full_df)
    assert population.loc["skipped_1"] == "insufficient_data", population.loc["skipped_1"]
    assert population.loc["skipped_2"] == "insufficient_data", population.loc["skipped_2"]
    assert (population.loc[[f"inactive_{i}" for i in range(5)]] == "inactive").all()
    assert (population.loc[[f"scripted_{i}" for i in range(10)]] == "active").all()
    print("OK: not_collected wallets correctly separated into 'insufficient_data', NOT folded "
          "into 'inactive' -- a data-collection gap is not the same claim as a genuinely "
          "collected zero-transaction wallet")


def test_all_nan_column_dropped_not_crashed():
    """Regression test for the real crash found running against real data:
    SimpleImputer silently drops all-NaN columns from its output array,
    desyncing it from X.columns and crashing DataFrame reconstruction.
    build_clustering_matrix must detect and drop such columns explicitly
    instead of crashing."""
    full_df, cell_df = build_synthetic_features(n_per_group=10, n_inactive=3)
    cell_df["repeated_since_value_ratio"] = np.nan  # simulate the real failure exactly
    full_df["wallet_status"] = np.where(full_df["n_tx_in_window"].fillna(0) > 0, "active", "unused")

    df = full_df.join(cell_df, how="outer", rsuffix="_cellfile")
    X_imputed, feature_cols = cw.build_clustering_matrix(df)  # must not raise
    assert "repeated_since_value_ratio" not in X_imputed.columns
    assert not X_imputed.isna().any().any()
    print("OK: an all-NaN column (repeated_since_value_ratio) is dropped with a warning instead "
          "of crashing SimpleImputer's shape reconstruction")


def test_outlier_exclusion_fixes_inflated_silhouette():
    """Regression test for the real artifact found running against real
    764-wallet data: a handful of extreme wallets (unbounded counterparty
    counts, exchange/pool-scale) dominated scaled distance so completely
    that EVERY k from 2-8 showed silhouette >0.93 with the smallest cluster
    under 1% -- and NMI against Phase 3 archetypes was 0.014, essentially
    zero agreement. This builds the same situation synthetically: two
    genuine behavioral groups plus a few wallets with absurd counterparty
    counts, and checks detect_outliers() catches the extreme wallets
    specifically (not the genuine behavioral groups), so clustering on the
    remainder recovers the real 2-group structure instead of being
    dominated by the outliers.
    """
    rng = np.random.default_rng(1)
    full_df, cell_df = build_synthetic_features(n_per_group=40, n_inactive=0, seed=1)
    full_df["wallet_status"] = "active"

    # A few wallets with absurd, unbounded counterparty counts -- like an
    # exchange or pool wallet -- against a population where everyone else
    # has single digits (see build_synthetic_features's make_group: 1-10).
    outlier_addrs = ["scripted_0", "scripted_1", "irregular_0"]
    for addr in outlier_addrs:
        full_df.loc[addr, "unique_counterparties_out"] = 5000
        full_df.loc[addr, "unique_counterparties_in"] = 5000
        cell_df.loc[addr, "unique_counterparties_out_cell"] = 5000
        cell_df.loc[addr, "unique_counterparties_in_cell"] = 5000

    df = full_df.join(cell_df, how="outer", rsuffix="_cellfile")
    X_full, feature_cols = cw.build_clustering_matrix(df)

    from sklearn.preprocessing import RobustScaler
    X_scaled_detect = pd.DataFrame(RobustScaler().fit_transform(X_full), index=X_full.index, columns=X_full.columns)
    flagged, detail = cw.detect_outliers(X_scaled_detect, cw.DEFAULT_MAX_ABS_THRESHOLD, cw.DEFAULT_DISTANCE_Z_THRESHOLD)

    for addr in outlier_addrs:
        assert flagged.loc[addr], f"{addr} (absurd counterparty count) should be flagged as an outlier"
    n_genuine_flagged = int(flagged.drop(outlier_addrs).sum())
    assert n_genuine_flagged == 0, (
        f"{n_genuine_flagged} genuinely-ordinary wallet(s) were incorrectly flagged as outliers "
        f"-- detect_outliers should only catch the 3 planted extreme wallets"
    )
    print(f"OK: detect_outliers() correctly flagged exactly the {len(outlier_addrs)} planted "
          f"extreme-counterparty wallets and none of the {n_genuine_flagged + (len(X_full) - len(outlier_addrs))} "
          f"genuinely-ordinary wallets")

    # Clustering the ordinary remainder should recover the real 2-group
    # structure with high purity -- the point of excluding outliers first.
    ordinary_idx = X_full.index[~flagged]
    X_ordinary_scaled = RobustScaler().fit_transform(X_full.loc[ordinary_idx])
    sweep = cw.run_sweep(X_ordinary_scaled, k_min=2, k_max=4, random_state=0)
    chosen_k, _ = cw.select_k(sweep, forced_k=None)
    assert chosen_k == 2, f"expected k=2 to be recovered once outliers are excluded, got {chosen_k}"

    from sklearn.mixture import GaussianMixture
    cluster_id = pd.Series(
        GaussianMixture(n_components=2, covariance_type="full", n_init=10, random_state=0).fit_predict(X_ordinary_scaled),
        index=ordinary_idx,
    )
    scripted_ids = cluster_id.loc[cluster_id.index.str.startswith("scripted")]
    irregular_ids = cluster_id.loc[cluster_id.index.str.startswith("irregular")]
    scripted_majority = scripted_ids.value_counts().iloc[0] / len(scripted_ids)
    irregular_majority = irregular_ids.value_counts().iloc[0] / len(irregular_ids)
    assert scripted_majority > 0.8 and irregular_majority > 0.8
    print(f"OK: after excluding outliers, clustering the ordinary remainder correctly recovers "
          f"the real 2-group behavioral structure ({scripted_majority:.0%} / {irregular_majority:.0%} "
          f"majority) instead of being dominated by the 3 extreme wallets")


if __name__ == "__main__":
    test_no_forbidden_vocabulary_and_bimodal_k()
    test_cross_tab_against_archetypes()
    test_missing_archetypes_file_does_not_crash()
    test_insufficient_data_not_conflated_with_inactive()
    test_all_nan_column_dropped_not_crashed()
    test_outlier_exclusion_fixes_inflated_silhouette()
    print("\nAll Phase 4 sanity tests passed.")
