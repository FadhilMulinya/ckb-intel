import argparse
import itertools
import json
import os
import sys

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

import fetch_real_data as frd  # same-directory import

FEATURE_COLS = [
    "interval_cv", "interval_mean_log", "capacity_cv", "fee_cv",
    "n_unique_counterparties", "counterparty_entropy_norm",
    "mean_outputs_per_tx", "interval_max_over_mean",
]

BASELINE = (1000, 50)  # must match fetch_real_data.py's defaults -- the setting your committed dataset actually used


def to_matrix(rows):
    return np.array([[r[c] for c in FEATURE_COLS] for r in rows], dtype=float)


def load_candidate_pool(real_data_dir):
    """Every discovered address's tx_count, straight from checkpoint.json --
    no API calls. Addresses classified under the OLD checkpoint format
    (plain string, no tx_count recorded) are dropped with a warning, since
    there's no way to re-bucket them without re-querying."""
    ckpt_path = frd.checkpoint_path(real_data_dir)
    if not os.path.exists(ckpt_path):
        print(f"ERROR: no checkpoint.json found at {ckpt_path!r}. "
              f"--real-data-dir must point at the SAME --out-dir you passed to "
              f"fetch_real_data.py (the folder containing checkpoint.json, "
              f"bot_like/, and human_like/ directly) -- not a parent folder.",
              file=sys.stderr)
        sys.exit(1)
    state = frd.load_checkpoint(real_data_dir)
    pool = {}
    dropped_no_txcount = 0
    for addr, entry in state["classified"].items():
        if not isinstance(entry, dict) or entry.get("tx_count") is None:
            dropped_no_txcount += 1
            continue
        pool[addr] = entry["tx_count"]
    if dropped_no_txcount:
        print(f"NOTE: {dropped_no_txcount} addresses have no recorded tx_count "
              f"(classified under an old checkpoint format) -- excluded from "
              f"this analysis. Re-run reconcile_bot_like_labels.py or "
              f"fetch_real_data.py to backfill them if this number is large.",
              file=sys.stderr)
    return pool


def bucket_under(pool, bot_min_tx, human_max_tx):
    bot_like, human_like = set(), set()
    for addr, tx_count in pool.items():
        if tx_count >= bot_min_tx:
            bot_like.add(addr)
        elif 1 <= tx_count <= human_max_tx:
            human_like.add(addr)
    return bot_like, human_like


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def build_address_index(real_data_dir, tx_cache_dir):
    """Maps address -> filepath for every address we've already fetched
    history for, across bot_like/, human_like/, and the sensitivity cache --
    so we never re-fetch an address just because it changed bucket."""
    index = {}
    for sub in ("bot_like", "human_like"):
        bucket_dir = os.path.join(real_data_dir, sub)
        manifest_path = os.path.join(bucket_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        for entry in json.load(open(manifest_path)):
            path = os.path.join(bucket_dir, f"addr_{entry['index']}.json")
            if os.path.exists(path):
                index[entry["address"]] = path
    if os.path.isdir(tx_cache_dir):
        for fname in os.listdir(tx_cache_dir):
            if fname.endswith(".json"):
                addr = fname[:-5]
                index[addr] = os.path.join(tx_cache_dir, fname)
    return index


def ensure_fetched(addrs, index, tx_cache_dir, max_tx):
    """Fetches history (live API call) for any address not already in the
    index, writes it into tx_cache_dir, and updates the index in place."""
    os.makedirs(tx_cache_dir, exist_ok=True)
    newly_fetched = 0
    for addr in addrs:
        if addr in index:
            continue
        try:
            txs = frd.fetch_address_transactions(addr, max_tx=max_tx)
        except frd.ApiError as e:
            print(f"  WARN: could not fetch {addr}, excluding from analysis: {e}", file=sys.stderr)
            continue
        if not txs:
            continue
        path = os.path.join(tx_cache_dir, f"{addr}.json")
        frd.write_address_file(path, addr, txs)
        index[addr] = path
        newly_fetched += 1
    return newly_fetched


def load_txs(path):
    lines = list(open(path))
    header = json.loads(lines[0])
    txs = [json.loads(l) for l in lines[1:]]
    return header["address"], txs


def extract_rows(addrs, index, ef_module, label):
    rows = []
    for addr in addrs:
        path = index.get(addr)
        if not path:
            continue
        _, txs = load_txs(path)
        if len(txs) < 2:
            continue
        feats = ef_module.extract_features({"address": addr, "archetype": label}, txs)
        rows.append(feats)
    return rows


def accuracy_block(model, X_bot_s, X_human_s):
    y_true = np.concatenate([np.ones(len(X_bot_s)), -np.ones(len(X_human_s))])
    X_eval = np.vstack([X_bot_s, X_human_s])
    y_pred = model.predict(X_eval)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[-1, 1]).ravel()
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision_bot": round(float(precision_score(y_true, y_pred, pos_label=1, zero_division=0)), 4),
        "recall_bot": round(float(recall_score(y_true, y_pred, pos_label=1, zero_division=0)), 4),
        "f1_bot": round(float(f1_score(y_true, y_pred, pos_label=1, zero_division=0)), 4),
        "confusion_matrix": {
            "true_bot_pred_bot": int(tp), "true_bot_pred_human": int(fn),
            "true_human_pred_bot": int(fp), "true_human_pred_human": int(tn),
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real-data-dir", default="data/real")
    ap.add_argument("--extract-features-dir", default="../bot_oneclass",
                     help="directory containing extract_features.py")
    ap.add_argument("--synthetic-features-path", default=None,
                     help="OPTIONAL. Path to a synthetic bot features.json WITH an 'archetype' field "
                          "(from bot_oneclass/extract_features.py, not extract_features_real.py -- real "
                          "data has 'label_source', not 'archetype', and is never valid here). "
                          "If omitted, each cell trains on ONLY that cell's real bot_like data -- this "
                          "is the more direct way to isolate the effect of the threshold rule itself, "
                          "without synthetic data diluting the result.")
    ap.add_argument("--bot-min-tx-grid", type=int, nargs="+", default=[500, 1000, 2000])
    ap.add_argument("--human-max-tx-grid", type=int, nargs="+", default=[20, 50, 100])
    ap.add_argument("--max-tx-per-address", type=int, default=300)
    ap.add_argument("--tx-cache-dir", default=None, help="default: <real-data-dir>/sensitivity_tx_cache")
    ap.add_argument("--out", default="sensitivity_report.json")
    args = ap.parse_args()

    if not os.path.isdir(args.extract_features_dir):
        print(f"ERROR: --extract-features-dir {args.extract_features_dir!r} not found. "
              f"Pass the correct path to the folder containing extract_features.py.", file=sys.stderr)
        sys.exit(1)
    sys.path.insert(0, os.path.abspath(args.extract_features_dir))
    import extract_features as ef

    if args.synthetic_features_path and not os.path.exists(args.synthetic_features_path):
        print(f"ERROR: --synthetic-features-path {args.synthetic_features_path!r} not found.", file=sys.stderr)
        sys.exit(1)

    tx_cache_dir = args.tx_cache_dir or os.path.join(args.real_data_dir, "sensitivity_tx_cache")

    pool = load_candidate_pool(args.real_data_dir)
    print(f"candidate pool: {len(pool)} addresses with known tx_count", file=sys.stderr)

    if args.synthetic_features_path:
        synth_rows = json.load(open(args.synthetic_features_path))
        if not synth_rows or "archetype" not in synth_rows[0]:
            print(f"ERROR: {args.synthetic_features_path!r} has no 'archetype' field -- this looks like "
                  f"a REAL-data features file (from extract_features_real.py, which uses 'label_source'), "
                  f"not synthetic bot features (from extract_features.py). Either point this at the "
                  f"correct synthetic features.json, or omit --synthetic-features-path entirely to run "
                  f"a real-data-only analysis.", file=sys.stderr)
            sys.exit(1)
        X_synth = to_matrix(synth_rows)
        archetypes = [r["archetype"] for r in synth_rows]
        X_synth_train, X_synth_test = train_test_split(
            X_synth, test_size=0.25, random_state=42, stratify=archetypes
        )  # FIXED across all cells -- only the real-data side varies per cell
        print(f"using {len(X_synth_train)} synthetic bot rows in training (fixed across all cells)", file=sys.stderr)
    else:
        X_synth_train = np.empty((0, len(FEATURE_COLS)))
        print("no --synthetic-features-path given -- each cell trains on real bot_like data only", file=sys.stderr)

    baseline_bot, baseline_human = bucket_under(pool, *BASELINE)
    print(f"baseline (bot_min_tx={BASELINE[0]}, human_max_tx={BASELINE[1]}): "
          f"{len(baseline_bot)} bot_like, {len(baseline_human)} human_like", file=sys.stderr)

    address_index = build_address_index(args.real_data_dir, tx_cache_dir)

    grid = list(itertools.product(args.bot_min_tx_grid, args.human_max_tx_grid))
    results = []

    for bot_min_tx, human_max_tx in grid:
        label = f"bot_min_tx={bot_min_tx}, human_max_tx={human_max_tx}"
        print(f"\n--- {label} ---", file=sys.stderr)
        bot_addrs, human_addrs = bucket_under(pool, bot_min_tx, human_max_tx)

        n_new = ensure_fetched(bot_addrs | human_addrs, address_index, tx_cache_dir, args.max_tx_per_address)
        if n_new:
            print(f"  fetched {n_new} newly-needed address histories", file=sys.stderr)

        bot_rows = extract_rows(bot_addrs, address_index, ef, "bot_like")
        human_rows = extract_rows(human_addrs, address_index, ef, "human_like")
        n_bot, n_human = len(bot_rows), len(human_rows)

        overlap_bot = jaccard(bot_addrs, baseline_bot)
        overlap_human = jaccard(human_addrs, baseline_human)
        # label changes: any address whose category (bot/human/excluded)
        # differs from the baseline setting
        all_addrs_touched = bot_addrs | human_addrs | baseline_bot | baseline_human
        n_label_changes = sum(
            1 for a in all_addrs_touched
            if (a in bot_addrs) != (a in baseline_bot) or (a in human_addrs) != (a in baseline_human)
        )

        cell_result = {
            "bot_min_tx": bot_min_tx, "human_max_tx": human_max_tx,
            "n_bot_like": n_bot, "n_human_like": n_human,
            "class_balance_bot_fraction": round(n_bot / (n_bot + n_human), 4) if (n_bot + n_human) else None,
            "jaccard_overlap_bot_like_vs_baseline": round(overlap_bot, 4),
            "jaccard_overlap_human_like_vs_baseline": round(overlap_human, 4),
            "n_label_changes_vs_baseline": n_label_changes,
        }

        if n_bot < 4 or n_human < 1:
            cell_result["models"] = None
            cell_result["skip_reason"] = f"too few examples to train/eval meaningfully (n_bot={n_bot}, n_human={n_human})"
            results.append(cell_result)
            print(f"  SKIPPED: {cell_result['skip_reason']}", file=sys.stderr)
            continue

        X_bot = to_matrix(bot_rows)
        X_human = to_matrix(human_rows)
        if n_bot >= 8:
            X_bot_train, X_bot_test = train_test_split(X_bot, test_size=0.25, random_state=42)
        else:
            X_bot_train, X_bot_test = X_bot, X_bot  # too few to hold out -- eval on train (optimistic, flagged below)
            cell_result["note"] = "n_bot too small for a real holdout -- eval reuses training bots (optimistic estimate)"

        X_train_all = np.vstack([X_synth_train, X_bot_train])
        scaler = StandardScaler().fit(X_train_all)
        X_train_s = scaler.transform(X_train_all)
        X_bot_test_s = scaler.transform(X_bot_test)
        X_human_s = scaler.transform(X_human)

        iso = IsolationForest(n_estimators=300, contamination=0.05, random_state=42).fit(X_train_s)
        ocsvm = OneClassSVM(kernel="rbf", nu=0.05, gamma="scale").fit(X_train_s)

        cell_result["models"] = {
            "IsolationForest": accuracy_block(iso, X_bot_test_s, X_human_s),
            "OneClassSVM": accuracy_block(ocsvm, X_bot_test_s, X_human_s),
        }
        print(f"  n_bot={n_bot} n_human={n_human} "
              f"IsoForest_acc={cell_result['models']['IsolationForest']['accuracy']} "
              f"OCSVM_acc={cell_result['models']['OneClassSVM']['accuracy']}", file=sys.stderr)
        results.append(cell_result)

    report = {"baseline": {"bot_min_tx": BASELINE[0], "human_max_tx": BASELINE[1]}, "cells": results}
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
