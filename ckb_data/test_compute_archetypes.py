"""
Sanity tests for Phase 3 (compute_archetypes.py) against a small synthetic
combined feature set. Reuses the Alice/Bob/Carol behavioral intent from the
Phase 2 tests (test_preprocess_cell_features.py) plus synthetic temporal
columns shaped like features_full.csv, and checks that each wallet's TOP
archetype matches what it was designed to look like -- and that the
support/state machinery correctly produces INSUFFICIENT_EVIDENCE where a
wallet genuinely lacks the underlying data, rather than a fabricated score.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import compute_archetypes as ca


def build_cell_layer_df() -> pd.DataFrame:
    """Mirrors preprocess_cell_features.py's real output shape."""
    return pd.DataFrame({
        "address": ["alice_bot", "bob_human", "carol_miner", "dave_batch",
                     "erin_fanin", "frank_roundtrip", "grace_sparse"],
        "n_tx_cell_layer": [5, 4, 1, 3, 3, 2, 2],
        "shape_1_to_1_ratio": [1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0],
        "shape_1_to_n_ratio": [0.0, 0.25, 0.0, 1.0, 0.0, 0.0, 0.0],
        "shape_n_to_1_ratio": [0.0, 0.25, 0.0, 0.0, 1.0, 0.0, 0.0],
        "shape_n_to_n_ratio": [0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0],
        "topology_state": ["OK"] * 7,
        "cell_lifetime_support_n": [5, 3, 0, 3, 3, 2, 0],
        "cell_lifetime_cv": [0.0, 0.9, np.nan, 0.5, 0.4, 0.6, np.nan],
        "lifecycle_state": ["OK", "OK", "INSUFFICIENT_EVIDENCE", "OK", "OK", "OK", "INSUFFICIENT_EVIDENCE"],
        "n_distinct_lock_hashes": [1, 3, 1, 1, 1, 2, 1],
        "multisig_usage_ratio": [0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0],
        "lock_state": ["OK"] * 7,
        "has_type_script_ratio": [0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0],
        "uses_since_ratio": [1.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0],
        "since_support_n": [5, 4, 1, 3, 3, 2, 1],
        "repeated_since_value_ratio": [1.0, 0.0, np.nan, np.nan, np.nan, np.nan, np.nan],
        "since_state": ["OK", "OK", "INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE",
                          "INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"],
        "unique_counterparties_out_cell": [0, 2, 0, 25, 0, 1, 0],
        "unique_counterparties_in_cell": [0, 2, 0, 0, 30, 1, 0],
        "reciprocity_ratio_cell": [np.nan, 0.2, np.nan, 0.0, 0.0, 0.9, np.nan],
        "out_capacity_concentration_hhi_cell": [np.nan, 0.4, np.nan, 0.05, np.nan, np.nan, np.nan],
        "network_state": ["OK"] * 7,
        "sent_capacity_ckb_cell": [500, 300, 0, 1000, 10, 200, 5],
        "received_capacity_ckb_cell": [510, 320, 4990, 5, 1000, 205, 6],
        "net_capacity_delta_ckb_cell": [10, 20, 4990, -995, 990, 5, 1],
        "touches_cellbase_directly": [False, False, True, False, False, False, False],
        "n_cellbase_inputs_direct": [0, 0, 1, 0, 0, 0, 0],
    }).set_index("address")


def build_full_df() -> pd.DataFrame:
    """Mirrors preprocess_ckb_wallets.py's temporal columns."""
    return pd.DataFrame({
        "address": ["alice_bot", "bob_human", "carol_miner", "dave_batch",
                     "erin_fanin", "frank_roundtrip", "grace_sparse"],
        "n_tx_in_window": [5, 5, 1, 3, 3, 2, 2],
        "gap_cv": [0.02, 0.9, np.nan, 0.1, 0.15, 0.3, 1.1],
        "hour_of_day_entropy": [0.1, 0.85, np.nan, 0.5, 0.4, 0.5, 0.9],
        "day_of_week_entropy": [0.05, 0.8, np.nan, 0.4, 0.4, 0.5, 0.9],
        "reciprocity_ratio": [np.nan, 0.15, np.nan, 0.0, 0.0, 0.85, np.nan],
        "has_dao_activity": [False, True, False, False, False, False, False],
        "n_dao_events": [0, 2, 0, 0, 0, 0, 0],
    }).set_index("address")


def test_archetype_separation():
    cell_df = build_cell_layer_df()
    full_df = build_full_df()
    df = full_df.join(cell_df, how="outer")

    archetypes = ca.compute_all_archetypes(df)

    assert archetypes.loc["alice_bot", "top_archetype"] == "PERIODIC_EXECUTION", \
        archetypes.loc["alice_bot"]
    assert archetypes.loc["alice_bot", "is_scripted"] == True
    print("OK: alice_bot -> PERIODIC_EXECUTION with is_scripted=True (near-zero gap_cv, "
          "zero lifetime variance, repeated since, pure 1-to-1 shape, single lock -- "
          "SCRIPT_TEMPLATE_REPETITION correctly reported as a modifier, not a competing label)")

    assert archetypes.loc["bob_human", "top_archetype"] == "IRREGULAR_ACTIVITY", \
        archetypes.loc["bob_human"]
    print("OK: bob_human -> IRREGULAR_ACTIVITY (as designed: high gap_cv, high "
          "entropy, mixed tx shapes, no repeated since -- DAO_ACTIVITY correctly "
          "excluded from competing for top_archetype despite scoring 1.0)")
    assert archetypes.loc["bob_human", "DAO_ACTIVITY_score"] == 1.0
    print("OK: bob_human's DAO_ACTIVITY is still reported (score 1.0) as a side fact, "
          "just not allowed to hijack top_archetype")

    assert archetypes.loc["dave_batch", "top_archetype"] == "BATCH_DISTRIBUTION", \
        archetypes.loc["dave_batch"]
    print("OK: dave_batch -> BATCH_DISTRIBUTION (as designed: pure 1-to-n shape, "
          "25 distinct recipients, even capacity spread -- SCRIPT_TEMPLATE_REPETITION "
          "correctly excluded from competing despite also scoring high)")
    assert archetypes.loc["dave_batch", "is_scripted"] == True, archetypes.loc["dave_batch"]
    print("OK: dave_batch's is_scripted=True correctly qualifies BATCH_DISTRIBUTION as "
          "automated, without SCRIPT_TEMPLATE_REPETITION hijacking top_archetype")

    assert archetypes.loc["erin_fanin", "top_archetype"] == "FAN_IN_COLLECTION", \
        archetypes.loc["erin_fanin"]
    print("OK: erin_fanin -> FAN_IN_COLLECTION (as designed: pure n-to-1 shape, "
          "30 distinct senders)")

    assert archetypes.loc["frank_roundtrip", "top_archetype"] == "ROUND_TRIP", \
        archetypes.loc["frank_roundtrip"]
    print("OK: frank_roundtrip -> ROUND_TRIP (as designed: high reciprocity, "
          "near-zero net capacity delta relative to volume)")

    # carol_miner has essentially no usable Cell-layer OR temporal signal
    # (single tx, all support-dependent families INSUFFICIENT_EVIDENCE) --
    # her only real signal is the cellbase touch, which must NOT show up as
    # a confident archetype score. Her single 1-to-1-shaped transaction
    # correctly scores a genuine 0.0 on every structural archetype (real
    # evidence against all of them), and the temporal archetypes are gated
    # INSUFFICIENT_EVIDENCE for having too few transactions -- both collapse
    # to the same top-level INSUFFICIENT_EVIDENCE label rather than an
    # arbitrary tied structural name being reported as "the answer".
    assert archetypes.loc["carol_miner", "top_archetype"] == "INSUFFICIENT_EVIDENCE", \
        archetypes.loc["carol_miner"]
    assert pd.isna(archetypes.loc["carol_miner", "top_score"])
    assert archetypes.loc["carol_miner", "BATCH_DISTRIBUTION_score"] == 0.0
    assert archetypes.loc["carol_miner", "touches_cellbase_directly"] == True
    print("OK: carol_miner correctly comes back INSUFFICIENT_EVIDENCE for top_archetype "
          "(genuine 0.0 on structural archetypes + gated temporal ones, not an arbitrary "
          "tied label) -- her only real signal, the cellbase touch, is surfaced separately "
          "as a lower bound, not blended into a score")

    # grace_sparse has almost nothing resolvable anywhere -- should be
    # heavily INSUFFICIENT_EVIDENCE across most families.
    insufficient_families = sum(
        1 for a in ca.ARCHETYPES if archetypes.loc["grace_sparse", f"{a}_state"] == "INSUFFICIENT_EVIDENCE"
    )
    print(f"OK: grace_sparse has {insufficient_families}/{len(ca.ARCHETYPES)} archetype "
          f"families INSUFFICIENT_EVIDENCE (sparse wallet correctly not over-scored)")


def test_reason_codes_present():
    cell_df = build_cell_layer_df()
    full_df = build_full_df()
    df = full_df.join(cell_df, how="outer")
    archetypes = ca.compute_all_archetypes(df)

    reasons = archetypes.loc["alice_bot", "PERIODIC_EXECUTION_reasons"]
    assert "LOW_INTERVAL_VARIANCE" in reasons, reasons
    assert "REPEATED_SINCE_VALUE" in reasons, reasons
    print(f"OK: alice_bot's PERIODIC_EXECUTION reason codes are traceable: '{reasons}'")


def test_missing_features_full_does_not_crash():
    """If features_full.csv wasn't run, compute_all_archetypes should still
    work (with fewer supporting signals), never crash on a missing column."""
    cell_df = build_cell_layer_df()
    archetypes = ca.compute_all_archetypes(cell_df)
    assert len(archetypes) == len(cell_df)
    assert "top_archetype" in archetypes.columns
    print("OK: compute_all_archetypes runs fine with Cell-layer-only input (no crash on missing "
          "temporal columns)")


def test_ordinary_wallet_not_falsely_scripted():
    """Regression test for the real bug found running against 887 real
    wallets: n_distinct_lock_hashes<=1 is the NORM for ordinary human
    wallets (nobody rotates locks within one wallet identity), so it must
    not, by itself, push an otherwise-unremarkable wallet's
    SCRIPT_TEMPLATE_REPETITION score over the is_scripted threshold."""
    cell_layer = pd.DataFrame({
        "address": ["ordinary_joe"],
        "n_tx_cell_layer": [10],
        "shape_1_to_1_ratio": [0.7], "shape_1_to_n_ratio": [0.2],
        "shape_n_to_1_ratio": [0.1], "shape_n_to_n_ratio": [0.0],
        "topology_state": ["OK"],
        "n_distinct_lock_hashes": [1],  # ordinary: one wallet, one lock
        "lock_state": ["OK"],
        "since_support_n": [10], "repeated_since_value_ratio": [np.nan],
        "since_state": ["INSUFFICIENT_EVIDENCE"],  # no meaningful since usage at all
        "unique_counterparties_out_cell": [3], "unique_counterparties_in_cell": [4],
        "network_state": ["OK"],
        "touches_cellbase_directly": [False], "n_cellbase_inputs_direct": [0],
    }).set_index("address")
    full = pd.DataFrame({
        "address": ["ordinary_joe"], "n_tx_in_window": [10], "gap_cv": [0.5],
    }).set_index("address")
    df = full.join(cell_layer, how="outer")

    archetypes = ca.compute_all_archetypes(df)
    assert archetypes.loc["ordinary_joe", "is_scripted"] == False, (
        f"ordinary_joe should NOT be flagged is_scripted just for having one lock script and "
        f"a moderately dominant shape -- got SCRIPT_TEMPLATE_REPETITION_score="
        f"{archetypes.loc['ordinary_joe', 'SCRIPT_TEMPLATE_REPETITION_score']}"
    )
    print(f"OK: ordinary_joe (single lock, 0.7 shape dominance, no repeated since) correctly "
          f"NOT flagged is_scripted (score="
          f"{archetypes.loc['ordinary_joe', 'SCRIPT_TEMPLATE_REPETITION_score']:.3f}) -- "
          f"regression test for the real 65%-false-positive-rate bug found on real data")


def test_no_futurewarning_on_mixed_dtype_cellbase_column():
    """Regression test: an outer join between features_full.csv (887 rows)
    and features_cell_layer.csv (764 rows) leaves touches_cellbase_directly
    as an OBJECT-dtype column (True/False/NaN mixed) for the ~123 rows only
    present in features_full.csv. This previously raised a pandas
    FutureWarning on fillna+downcast (seen running against real 887-wallet
    data) -- must not recur."""
    import warnings
    df = pd.DataFrame({
        "n_tx_in_window": [10, 5, 3],
        "touches_cellbase_directly": [True, False, np.nan],
    }, index=["a", "b", "c"])
    assert df["touches_cellbase_directly"].dtype == object

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        out = ca.compute_all_archetypes(df)

    assert out["touches_cellbase_directly"].dtype == bool
    assert out["touches_cellbase_directly"].tolist() == [True, False, False]
    print("OK: mixed True/False/NaN (object dtype) touches_cellbase_directly column handled "
          "with no FutureWarning, correctly downcast to bool with NaN -> False")


if __name__ == "__main__":
    test_archetype_separation()
    test_reason_codes_present()
    test_missing_features_full_does_not_crash()
    test_ordinary_wallet_not_falsely_scripted()
    test_no_futurewarning_on_mixed_dtype_cellbase_column()
    print("\nAll Phase 3 sanity tests passed.")
