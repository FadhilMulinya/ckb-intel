from __future__ import annotations

"""
Phase 3 of the gap-closure plan (see CKB_Wallet_Classifier_Gap_Closure_Plan.md,
section 3, Phase 3): a transparent, rule-based archetype layer computed
directly from Phase 2's feature CSVs. NO clustering, NO training happens
here -- every score below is a hand-written formula over specific columns,
so a reviewer can trace exactly why a wallet got a given score.

This is deliberately NOT the final Human/Bot/Miner/Inactive classification
(that's Phase 6, after Phase 5 builds real ground truth). Treat this as the
committee-facing deliverable the plan describes in Phase 3: named, evidenced
behavior patterns, each with a 0-1 score, an explicit support/state, and
reason codes -- not a verdict.

Archetypes computed:
    PERIODIC_EXECUTION      -- regular timing, fixed holding periods, repeated
                               since values, spend-and-return shape
    SCRIPT_TEMPLATE_REPETITION -- one lock script, one dominant tx shape,
                               repeated since -- "the same script keeps firing"
    BATCH_DISTRIBUTION      -- fans out to many distinct recipients per tx
    FAN_IN_COLLECTION       -- many distinct senders consolidate into this wallet
    CELL_CONSOLIDATION      -- many-to-one shape but NOT from many distinct
                               parties -- this wallet merging its own dust
    CELL_FRAGMENTATION      -- one-to-many shape but NOT to many distinct
                               parties -- splitting capacity among few/self
    ROUND_TRIP              -- high reciprocity + near-zero net flow relative
                               to volume (passthrough behavior)
    IRREGULAR_ACTIVITY      -- catch-all human-like signal: high timing
                               variance, high time-of-day/day-of-week entropy,
                               no single dominant tx shape

DAO_ACTIVITY is computed and reported like the others (exact, from
dao_events, not a fuzzy score) but is deliberately excluded from
top_archetype/top_score: it's a binary exact fact, and would trivially
dominate any continuous 0-1 pattern score once true. It's a side fact,
reported the same way as touches_cellbase_directly below.

Every archetype's score is the mean of only the sub-signals that had
sufficient underlying support (per Phase 2's *_state columns) -- a family
marked INSUFFICIENT_EVIDENCE contributes nothing rather than a fabricated
0 or 1. If NONE of an archetype's sub-signals have support, the archetype
score is NaN and archetype_state is INSUFFICIENT_EVIDENCE, not "0.0 evidence
of this archetype" (those are different claims).

touches_cellbase_directly is surfaced separately as a MINER LOWER BOUND, not
folded into an archetype score -- per the plan's own repeated caution, direct
cellbase touch is necessary-but-not-sufficient evidence and real miner
detection needs Cell lineage back to cellbase (Phase 5), not this heuristic.

Usage:
    python3 compute_archetypes.py --features-dir ./ckb_features \
        --out-dir ./ckb_features
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("compute_archetypes")

MIN_TX_FOR_ARCHETYPES = 5  # informational default; per-archetype thresholds below are authoritative

# Per-archetype minimum transaction counts. NOT uniform on purpose: structural
# archetypes (BATCH_DISTRIBUTION, FAN_IN_COLLECTION, CELL_CONSOLIDATION,
# CELL_FRAGMENTATION) can be genuinely evidenced by a single sufficiently
# lopsided transaction -- one 25-output distribution tx IS real evidence of
# batch distribution, even if it's the wallet's only transaction. ROUND_TRIP
# needs at least an out-leg and a back-leg (2). PERIODIC_EXECUTION,
# IRREGULAR_ACTIVITY, and SCRIPT_TEMPLATE_REPETITION are fundamentally about
# a pattern across MULTIPLE transactions -- "periodic" and "repeated" are
# meaningless for n=1, and without this gate a single-transaction wallet can
# pick up a maximally confident score from one incidental signal (caught by
# this module's own test suite: a 1-transaction wallet scored a full 1.0 on
# PERIODIC_EXECUTION purely because its only transaction was trivially
# "1-to-1 shaped").
ARCHETYPE_MIN_TX = {
    "PERIODIC_EXECUTION": 5,
    "IRREGULAR_ACTIVITY": 5,
    "SCRIPT_TEMPLATE_REPETITION": 3,
    "ROUND_TRIP": 2,
    "BATCH_DISTRIBUTION": 1,
    "FAN_IN_COLLECTION": 1,
    "CELL_CONSOLIDATION": 1,
    "CELL_FRAGMENTATION": 1,
}

ARCHETYPES = [
    "PERIODIC_EXECUTION", "BATCH_DISTRIBUTION",
    "FAN_IN_COLLECTION", "CELL_CONSOLIDATION", "CELL_FRAGMENTATION",
    "ROUND_TRIP", "IRREGULAR_ACTIVITY",
]
# These are deliberately excluded from the top_archetype/top_score
# competition, for two different reasons:
#   DAO_ACTIVITY               -- a binary exact fact (touched the DAO or
#                                  didn't), which would trivially dominate
#                                  any continuous 0-1 pattern score once true.
#   SCRIPT_TEMPLATE_REPETITION -- not really its own behavior SHAPE at all;
#                                  its "one dominant tx shape + one lock
#                                  script" signal fires for a consistent
#                                  batch-distributor just as readily as for a
#                                  spend-and-return bot (caught by this
#                                  module's own test suite: it was
#                                  out-scoring BATCH_DISTRIBUTION for a
#                                  wallet that IS a batch distributor, purely
#                                  by having fewer diluting sub-signals, not
#                                  because it was more true). It's an
#                                  AUTOMATION MODIFIER that can accompany any
#                                  of the structural archetypes above -- see
#                                  is_scripted below -- not a competitor to them.
MODIFIER_ARCHETYPES = ["DAO_ACTIVITY", "SCRIPT_TEMPLATE_REPETITION"]
IS_SCRIPTED_THRESHOLD = 0.7


def col(df: pd.DataFrame, name: str) -> pd.Series:
    """Defensive column access -- returns an all-NaN Series if the column is
    missing (e.g. one of the two source CSVs wasn't run), instead of crashing
    every archetype function."""
    if name in df.columns:
        return df[name]
    return pd.Series(np.nan, index=df.index)


def clip01(x: pd.Series) -> pd.Series:
    return x.clip(lower=0, upper=1)


def low_is_high(x: pd.Series, cap: float) -> pd.Series:
    """Maps a variance/CV-like measure where LOW values indicate strong
    evidence (e.g. gap_cv near 0 = very regular) onto a 0-1 score."""
    return clip01(1 - x.clip(lower=0, upper=cap) / cap)


def log_scale(x: pd.Series, ref: float) -> pd.Series:
    """Maps a count (e.g. unique counterparties) onto 0-1 via log1p, so a
    handful of counterparties doesn't already max out the score."""
    return clip01(np.log1p(x.clip(lower=0)) / np.log1p(ref))


def mean_of_available(*signals: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Row-wise mean ignoring NaN, plus a per-row count of how many signals
    actually contributed. If a row has zero contributing signals, the mean
    is NaN (not silently 0) and support count is 0."""
    stacked = pd.concat(signals, axis=1)
    support = stacked.notna().sum(axis=1)
    mean = stacked.mean(axis=1, skipna=True)
    mean = mean.where(support > 0, np.nan)
    return mean, support


def reason_if(mask: pd.Series, code: str) -> pd.Series:
    """Returns a Series of code-or-empty-string, for building reason_codes."""
    return pd.Series(np.where(mask.fillna(False), code, ""), index=mask.index)


def combine_reasons(*reason_series: pd.Series) -> pd.Series:
    def _join(row):
        codes = [c for c in row if c]
        return ";".join(codes)
    return pd.concat(reason_series, axis=1).apply(_join, axis=1)


# ---------------------------------------------------------------------------
# Individual archetypes
# ---------------------------------------------------------------------------

def score_periodic_execution(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    gap_cv = col(df, "gap_cv")
    lifecycle_ok = col(df, "lifecycle_state") == "OK"
    since_ok = col(df, "since_state") == "OK"

    s_gap = low_is_high(gap_cv, cap=2.0)
    s_lifetime = low_is_high(col(df, "cell_lifetime_cv"), cap=2.0).where(lifecycle_ok)
    s_since = col(df, "repeated_since_value_ratio").where(since_ok)
    s_shape = col(df, "shape_1_to_1_ratio")

    score, support = mean_of_available(s_gap, s_lifetime, s_since, s_shape)
    reasons = combine_reasons(
        reason_if(gap_cv < 0.3, "LOW_INTERVAL_VARIANCE"),
        reason_if(lifecycle_ok & (col(df, "cell_lifetime_cv") < 0.3), "LOW_LIFETIME_VARIANCE"),
        reason_if(since_ok & (col(df, "repeated_since_value_ratio") > 0.7), "REPEATED_SINCE_VALUE"),
        reason_if(col(df, "shape_1_to_1_ratio") > 0.8, "DOMINANT_1TO1_SHAPE"),
    )
    return score, support, reasons


def score_script_template_repetition(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """shape_dominance GATES this score, same pattern as the structural
    archetypes below. n_distinct_lock_hashes<=1 is deliberately NOT used as
    a contributing signal here (it was in an earlier version) -- using a
    single lock script is the norm for ordinary human wallets, not a bot
    signal, since almost nobody rotates locks within one wallet identity.
    Averaging it in inflated scores broadly and non-selectively across the
    whole population (found by running this against real data: 65% of a
    real 887-wallet population came back is_scripted=True, which is not
    plausible). It's kept as an informational reason code only."""
    shape_cols = ["shape_1_to_1_ratio", "shape_1_to_n_ratio", "shape_n_to_1_ratio", "shape_n_to_n_ratio"]
    shape_dominance = pd.concat([col(df, c) for c in shape_cols], axis=1).max(axis=1)
    since_ok = col(df, "since_state") == "OK"
    s_since = col(df, "repeated_since_value_ratio").where(since_ok).fillna(0.5)

    score = (shape_dominance * (0.5 + 0.5 * s_since)).where(shape_dominance.notna())
    support = shape_dominance.notna().astype(int) + since_ok.astype(int)
    reasons = combine_reasons(
        reason_if(shape_dominance > 0.85, "DOMINANT_TX_SHAPE"),
        reason_if(col(df, "n_distinct_lock_hashes") <= 1, "SINGLE_LOCK_SCRIPT"),
        reason_if(since_ok & (col(df, "repeated_since_value_ratio") > 0.7), "REPEATED_SINCE_VALUE"),
    )
    return score, support, reasons


def score_batch_distribution(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """fanout_shape GATES this score (0 shape ratio -> 0, regardless of
    secondary signals) rather than averaging with secondary signals -- a
    flat average let a wallet with a strong counterparty-count signal but
    NO actual 1-to-n transactions still land at 0.5 (caught by this
    module's own test suite). Secondary signals only refine confidence
    within the gated range."""
    fanout_shape = col(df, "shape_1_to_n_ratio")
    fanout_scale = log_scale(col(df, "unique_counterparties_out_cell"), ref=50)
    evenness = (1 - col(df, "out_capacity_concentration_hhi_cell")).where(col(df, "network_state") == "OK")
    secondary, secondary_support = mean_of_available(fanout_scale, evenness)
    secondary_filled = secondary.fillna(0.5)  # neutral (neither confirms nor denies) when unknown

    score = (fanout_shape * (0.5 + 0.5 * secondary_filled)).where(fanout_shape.notna())
    support = fanout_shape.notna().astype(int) + secondary_support
    reasons = combine_reasons(
        reason_if(fanout_shape > 0.5, "FANOUT_DOMINANT_SHAPE"),
        reason_if(col(df, "unique_counterparties_out_cell") >= 10, "MANY_DISTINCT_RECIPIENTS"),
        reason_if(evenness > 0.7, "EVEN_CAPACITY_SPREAD"),
    )
    return score, support, reasons


def score_fan_in_collection(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Same primary-gate pattern as score_batch_distribution -- see its docstring."""
    fanin_shape = col(df, "shape_n_to_1_ratio")
    fanin_scale = log_scale(col(df, "unique_counterparties_in_cell"), ref=50)
    secondary = fanin_scale.fillna(0.5)

    score = (fanin_shape * (0.5 + 0.5 * secondary)).where(fanin_shape.notna())
    support = fanin_shape.notna().astype(int) + fanin_scale.notna().astype(int)
    reasons = combine_reasons(
        reason_if(fanin_shape > 0.5, "FANIN_DOMINANT_SHAPE"),
        reason_if(col(df, "unique_counterparties_in_cell") >= 10, "MANY_DISTINCT_SENDERS"),
    )
    return score, support, reasons


def score_cell_consolidation(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Many-to-one shape GATES this score; the 'many are NOT distinct
    external counterparties' signal only refines confidence within that
    gate -- it should not, by itself, produce a positive score when the
    n-to-1 shape is actually absent (this wallet's transactions might be
    e.g. purely 1-to-1, which trivially has zero distinct sources too, but
    that's not consolidation)."""
    fanin_shape = col(df, "shape_n_to_1_ratio")
    self_merge = (1 - log_scale(col(df, "unique_counterparties_in_cell"), ref=20)).fillna(0.5)

    score = (fanin_shape * (0.5 + 0.5 * self_merge)).where(fanin_shape.notna())
    support = fanin_shape.notna().astype(int) + col(df, "unique_counterparties_in_cell").notna().astype(int)
    reasons = combine_reasons(
        reason_if(fanin_shape > 0.5, "N_TO_1_SHAPE"),
        reason_if(col(df, "unique_counterparties_in_cell") <= 2, "FEW_DISTINCT_SOURCES"),
    )
    return score, support, reasons


def score_cell_fragmentation(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Same primary-gate pattern as score_cell_consolidation -- see its docstring."""
    fanout_shape = col(df, "shape_1_to_n_ratio")
    self_split = (1 - log_scale(col(df, "unique_counterparties_out_cell"), ref=20)).fillna(0.5)

    score = (fanout_shape * (0.5 + 0.5 * self_split)).where(fanout_shape.notna())
    support = fanout_shape.notna().astype(int) + col(df, "unique_counterparties_out_cell").notna().astype(int)
    reasons = combine_reasons(
        reason_if(fanout_shape > 0.5, "1_TO_N_SHAPE"),
        reason_if(col(df, "unique_counterparties_out_cell") <= 2, "FEW_DISTINCT_DESTINATIONS"),
    )
    return score, support, reasons


def score_round_trip(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    recip_cell = col(df, "reciprocity_ratio_cell").where(col(df, "network_state") == "OK")
    recip_old = col(df, "reciprocity_ratio")

    sent = col(df, "sent_capacity_ckb_cell")
    received = col(df, "received_capacity_ckb_cell")
    turnover = sent + received
    net = col(df, "net_capacity_delta_ckb_cell").abs()
    passthrough = clip01(1 - (net / turnover.replace(0, np.nan)))

    score, support = mean_of_available(recip_cell, recip_old, passthrough)
    reasons = combine_reasons(
        reason_if(recip_cell > 0.3, "HIGH_RECIPROCITY_CELL"),
        reason_if(recip_old > 0.3, "HIGH_RECIPROCITY_LEGACY_EDGES"),
        reason_if(passthrough > 0.8, "NEAR_ZERO_NET_FLOW"),
    )
    return score, support, reasons


def score_dao_activity(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Exact, not fuzzy -- dao_events is a direct, reliable signal (see plan
    section 1: DAO features are already exact in the existing pipeline)."""
    has_dao = col(df, "has_dao_activity")
    n_events = col(df, "n_dao_events")
    score = has_dao.astype(float).where(has_dao.notna())
    support = has_dao.notna().astype(int)
    reasons = combine_reasons(reason_if(n_events > 0, "HAS_DAO_EVENTS"))
    return score, support, reasons


def score_irregular_activity(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Human-like catch-all: high timing variance, varied hour/day-of-week
    activity, no single dominant Cell-transaction shape."""
    gap_cv = col(df, "gap_cv")
    s_gap = clip01(gap_cv.clip(lower=0, upper=2.0) / 2.0)  # HIGH cv -> high score (opposite of periodic)
    s_hour = col(df, "hour_of_day_entropy")
    s_dow = col(df, "day_of_week_entropy")

    shape_cols = ["shape_1_to_1_ratio", "shape_1_to_n_ratio", "shape_n_to_1_ratio", "shape_n_to_n_ratio"]
    shape_dominance = pd.concat([col(df, c) for c in shape_cols], axis=1).max(axis=1)
    s_shape_mix = clip01(1 - shape_dominance)

    since_ok = col(df, "since_state") == "OK"
    s_no_since_repeat = (1 - col(df, "repeated_since_value_ratio")).where(since_ok)

    score, support = mean_of_available(s_gap, s_hour, s_dow, s_shape_mix, s_no_since_repeat)
    reasons = combine_reasons(
        reason_if(gap_cv > 0.7, "HIGH_INTERVAL_VARIANCE"),
        reason_if(s_hour > 0.7, "VARIED_TIME_OF_DAY"),
        reason_if(s_dow > 0.7, "VARIED_DAY_OF_WEEK"),
        reason_if(shape_dominance < 0.5, "MIXED_TX_SHAPES"),
    )
    return score, support, reasons


ARCHETYPE_FUNCS = {
    "PERIODIC_EXECUTION": score_periodic_execution,
    "SCRIPT_TEMPLATE_REPETITION": score_script_template_repetition,
    "BATCH_DISTRIBUTION": score_batch_distribution,
    "FAN_IN_COLLECTION": score_fan_in_collection,
    "CELL_CONSOLIDATION": score_cell_consolidation,
    "CELL_FRAGMENTATION": score_cell_fragmentation,
    "ROUND_TRIP": score_round_trip,
    "IRREGULAR_ACTIVITY": score_irregular_activity,
    "DAO_ACTIVITY": score_dao_activity,  # scored, but excluded from top_archetype -- see SIDE_FACT_ARCHETYPES
}


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def compute_all_archetypes(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for name, func in ARCHETYPE_FUNCS.items():
        score, support, reasons = func(df)
        out[f"{name}_score"] = score
        out[f"{name}_support_n"] = support
        out[f"{name}_state"] = np.where(support > 0, "OK", "INSUFFICIENT_EVIDENCE")
        out[f"{name}_reasons"] = reasons

    # Per-archetype activity gate -- see ARCHETYPE_MIN_TX for why these
    # differ by archetype. DAO_ACTIVITY is exempt (single-event exact fact).
    activity_col = "n_tx_in_window" if "n_tx_in_window" in df.columns else (
        "n_tx_cell_layer" if "n_tx_cell_layer" in df.columns else None)
    if activity_col is not None:
        n_tx = df[activity_col].reindex(out.index).fillna(0)
        for name, min_tx in ARCHETYPE_MIN_TX.items():
            insufficient = n_tx < min_tx
            out.loc[insufficient, f"{name}_score"] = np.nan
            out.loc[insufficient, f"{name}_support_n"] = 0
            out.loc[insufficient, f"{name}_state"] = "INSUFFICIENT_EVIDENCE"
    else:
        log.warning("neither n_tx_in_window nor n_tx_cell_layer present -- cannot apply the "
                     "per-archetype activity gate. Archetype scores for low-activity wallets may "
                     "be overconfident. Run preprocess_ckb_wallets.py and/or "
                     "preprocess_cell_features.py first so at least one of these columns is available.")

    score_cols = [f"{a}_score" for a in ARCHETYPES]  # excludes MODIFIER_ARCHETYPES on purpose
    scores_only = out[score_cols]
    max_score = scores_only.max(axis=1, skipna=True)
    # idxmax raises/warns on all-NA rows in newer pandas; give it a value it
    # can safely max over (all rows have at least one non-NA column after
    # fillna(-1), so idxmax never sees an all-NA row) and correct the result
    # for genuinely-all-NA rows afterward via no_signal below.
    out["top_archetype"] = scores_only.fillna(-1).idxmax(axis=1).str.replace("_score", "", regex=False)
    out["top_score"] = max_score
    # A tie at exactly 0.0 across every structural archetype is real evidence
    # AGAINST all of them individually, but reporting one of the tied names
    # as "the answer" (idxmax picks arbitrarily) misrepresents a uniformly
    # negative result as a positive finding. Fold both "no data at all" and
    # "confidently none of these" into the same INSUFFICIENT_EVIDENCE label
    # for the summary field -- the real per-archetype 0.0 scores are still
    # inspectable in the individual *_score columns for anyone who wants them.
    no_signal = max_score.isna() | (max_score <= 0)
    out.loc[no_signal, "top_archetype"] = "INSUFFICIENT_EVIDENCE"
    out.loc[no_signal, "top_score"] = np.nan

    # Automation modifier: does SCRIPT_TEMPLATE_REPETITION support the idea
    # that whichever structural archetype won is being executed by a script,
    # rather than being its own competing category (see MODIFIER_ARCHETYPES).
    out["is_scripted"] = (
        (out["SCRIPT_TEMPLATE_REPETITION_score"] >= IS_SCRIPTED_THRESHOLD)
        & (out["SCRIPT_TEMPLATE_REPETITION_state"] == "OK")
    )

    # Miner lower bound -- surfaced separately, never folded into a score.
    # See module docstring and the gap-closure plan's repeated caution that
    # real miner detection needs Cell lineage back to cellbase (Phase 5).
    # NOTE: deliberately NOT .fillna(False).astype(bool) -- on an
    # object-dtype column (which is exactly what an outer join against
    # features_full.csv produces for wallets missing from
    # features_cell_layer.csv: a mix of True/False/NaN), fillna's internal
    # downcast raises a FutureWarning on pandas 2.x regardless of any
    # .infer_objects() called afterward, since the warning fires DURING
    # fillna itself, not after (found running against real pandas 2.3.3 --
    # my own test environment runs pandas 3.0.2, where this warning no
    # longer fires at all, which is why an earlier fix looked clean here but
    # wasn't). .eq(True) sidesteps fillna's downcast path entirely: NaN==True
    # evaluates to False directly, with no downcast warning on any pandas
    # version, verified against pandas 2.3.3 specifically.
    out["touches_cellbase_directly"] = col(df, "touches_cellbase_directly").eq(True)
    out["n_cellbase_inputs_direct"] = col(df, "n_cellbase_inputs_direct").fillna(0)

    if "n_tx_in_window" in df.columns:
        out["n_tx_in_window"] = df["n_tx_in_window"]

    return out


def load_and_join(features_dir: Path) -> pd.DataFrame:
    full_path = features_dir / "features_full.csv"
    cell_path = features_dir / "features_cell_layer.csv"
    if not cell_path.exists():
        raise SystemExit(f"no such file: {cell_path} -- run preprocess_cell_features.py (Phase 2) first.")

    cell_df = pd.read_csv(cell_path, index_col="address")
    if full_path.exists():
        full_df = pd.read_csv(full_path, index_col="address")
        df = full_df.join(cell_df, how="outer", rsuffix="_cellfile")
        log.info("joined features_full.csv (%d rows) with features_cell_layer.csv (%d rows) -> %d rows",
                  len(full_df), len(cell_df), len(df))
    else:
        log.warning("%s not found -- proceeding with Cell-layer features only. Temporal features "
                     "(gap_cv, burstiness, hour/day entropy) won't be available, which will reduce "
                     "PERIODIC_EXECUTION and IRREGULAR_ACTIVITY to fewer supporting signals.", full_path)
        df = cell_df
    return df


def print_summary(archetypes: pd.DataFrame) -> None:
    print("\n=== Phase 3 archetype summary ===")
    print(f"{len(archetypes)} wallet(s) scored.\n")

    print("Top-archetype distribution:")
    counts = archetypes["top_archetype"].value_counts()
    for name, count in counts.items():
        pct = 100 * count / len(archetypes)
        print(f"  {name:<28s} {count:5d}  ({pct:.1f}%)")

    n_cellbase = int(archetypes["touches_cellbase_directly"].sum())
    print(f"\nMiner lower bound: {n_cellbase} wallet(s) touch a cellbase input directly.")
    print("  This is NECESSARY-but-not-sufficient evidence, not a miner archetype score --")
    print("  see the module docstring. Do not treat this count as your miner population.")

    if "DAO_ACTIVITY_score" in archetypes.columns:
        n_dao = int((archetypes["DAO_ACTIVITY_score"] == 1.0).sum())
        print(f"\nDAO activity (side fact, excluded from top_archetype -- see module docstring): "
              f"{n_dao} wallet(s).")

    if "is_scripted" in archetypes.columns:
        n_scripted = int(archetypes["is_scripted"].sum())
        print(f"\nAutomation modifier: {n_scripted} wallet(s) show strong SCRIPT_TEMPLATE_REPETITION "
              f"evidence (is_scripted=True) -- read this as qualifying whatever top_archetype says "
              f"(e.g. a 'scripted BATCH_DISTRIBUTION' vs a one-off one), not as its own category.")

    print("\nReminder: these are transparent rule-based scores (Phase 3), not final")
    print("Human/Bot/Miner/Inactive labels. Next steps per the gap-closure plan:")
    print("  Phase 4 -- re-cluster on the combined features as a sanity check (open k, neutral names)")
    print("  Phase 5 -- hand-verify a ground-truth sample per class against a block explorer")
    print("  Phase 6 -- map archetype evidence + Phase 5 ground truth to the final 4 labels")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--features-dir", type=Path, required=True,
                   help="Directory containing features_cell_layer.csv (and, ideally, "
                        "features_full.csv) from preprocess_cell_features.py / preprocess_ckb_wallets.py")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Default: same as --features-dir")
    args = p.parse_args()
    out_dir = args.out_dir or args.features_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_join(args.features_dir)

    if "n_tx_in_window" in df.columns:
        n_before = len(df)
        low_activity = df["n_tx_in_window"].fillna(0) < MIN_TX_FOR_ARCHETYPES
        log.info("%d/%d wallet(s) have fewer than %d transactions -- per-archetype minimums "
                  "(ARCHETYPE_MIN_TX) apply individually, so these wallets may still get valid "
                  "structural scores (BATCH_DISTRIBUTION etc.) even while temporal-pattern "
                  "archetypes (PERIODIC_EXECUTION, IRREGULAR_ACTIVITY) are INSUFFICIENT_EVIDENCE.",
                  int(low_activity.sum()), n_before, MIN_TX_FOR_ARCHETYPES)

    archetypes = compute_all_archetypes(df)

    out_path = out_dir / "wallet_archetypes.csv"
    archetypes.to_csv(out_path, encoding="utf-8")
    log.info("wrote %s (%d rows, %d columns)", out_path, len(archetypes), len(archetypes.columns))

    print_summary(archetypes)


if __name__ == "__main__":
    main()
