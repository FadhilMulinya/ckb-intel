from __future__ import annotations

"""
Adds the structured manual-verification fields (see VERIFICATION_FIELD_GUIDE.md)
onto an existing ground_truth_candidates.csv from select_ground_truth_candidates.py
(Phase 5). Extends the file in place rather than being a separate sheet you'd
have to merge by hand -- every pipeline column (source_signal, top_archetype,
cluster_label, etc.) stays right next to what you find manually, so you can
see at a glance whether your read agrees with the automated score.

Usage:
    python3 expand_verification_template.py \
        --candidates ./ground_truth_candidates.csv \
        --out ./ground_truth_candidates_template.csv
"""

import argparse
from pathlib import Path

import pandas as pd

# One column per checklist item from the manual-verification walkthrough.
# Order matches the order you'd naturally check things on an address page:
# overview facts first, then the archetype-specific checks, then the verdict.
VERIFICATION_COLUMNS = [
    "checked_tx_count",              # from the explorer's address overview
    "checked_first_tx_date",
    "checked_last_tx_date",
    "checked_lock_family",           # secp256k1_sighash / multisig / omnilock / other -- observed, not inferred
    "checked_has_type_script",       # Y / N -- and what asset/UDT if Y
    "checked_timestamp_regularity",  # Regular / Irregular / Unclear
    "checked_tx_shape_pattern",      # e.g. "always 1-in-1-out", "N-to-1", "mixed"
    "checked_since_repeated",        # Y / N / NA -- same since value across multiple tx?
    "checked_counterparty_pattern",  # e.g. "many small deposits swept", "one repeated counterparty",
                                      # "many distinct ordinary counterparties", "single exchange/pool"
    "checked_block_miner_match",     # Y / N / NA -- found as a block's "Miner" field directly
    "checked_external_reference",    # known exchange/pool name if identified via web search, else blank
    "confidence",                    # High / Medium / Low -- your confidence in verified_label
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", type=Path, required=True,
                     help="ground_truth_candidates.csv from select_ground_truth_candidates.py")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not args.candidates.exists():
        raise SystemExit(f"no such file: {args.candidates} -- run select_ground_truth_candidates.py first.")

    df = pd.read_csv(args.candidates, dtype=str, keep_default_na=False)

    # Insert the new fields right before verified_label if it exists, so the
    # verdict columns stay last (natural fill-in-order: facts, then verdict).
    insert_at = df.columns.get_loc("verified_label") if "verified_label" in df.columns else len(df.columns)
    n_added = 0
    for i, col in enumerate(VERIFICATION_COLUMNS):
        if col not in df.columns:
            df.insert(insert_at + i, col, "")
            n_added += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({len(df)} row(s), {n_added} verification field(s) added)")
    print("See VERIFICATION_FIELD_GUIDE.md for what each field means and valid values.")


if __name__ == "__main__":
    main()
