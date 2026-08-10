import argparse
import importlib.util
import itertools
import json
import os
import sys

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

BOT_MIN_TX_GRID = [500, 1000, 2000]
HUMAN_MAX_TX_GRID = [20, 50, 100]
CURRENT_BOT_MIN_TX = 1000
CURRENT_HUMAN_MAX_TX = 50


def load_train_eval_module(repo_root):
    """Import train_eval.py's functions/constants directly rather than
    reimplementing model selection -- so retrained metrics under each
    threshold combo are produced by the identical code path that made
    eval_results.json, and are therefore directly comparable to it."""
    path = os.path.join(repo_root, "classifier-service", "train_eval.py")
    spec = importlib.util.spec_from_file_location("train_eval", path)
    mod = importlib.util.module_from_spec(spec)
    # train_eval.py writes files at import-time-adjacent module scope only
    # inside main(), so importing it just defines functions/constants --
    # safe to import without triggering a training run.
    spec.loader.exec_module(mod)
    return mod


def load_lifetime_stats(repo_root, path="data/real/lifetime_stats.jsonl"):
    full_path = os.path.join(repo_root, path)
    if not os.path.exists(full_path):
        raise SystemExit(
            f"ERROR: {full_path} not found. Run fetch_lifetime_stats.py first "
            f"(requires live access to the CKB Explorer API)."
        )
    stats = {}
    with open(full_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("tx_count") is not None:
                stats[rec["address"]] = rec
    return stats


def relabel(tx_count, bot_min_tx, human_max_tx):
    """Mirrors fetch_real_data.py's classify_address bucket logic, minus
    is_special (removed from the labeling rule per §1 of the Committee
    response -- it never determined bot_like and was never observed
    True in retained data)."""
    if tx_count >= bot_min_tx:
        return "bot_like"
    if 1 <= tx_count <= human_max_tx:
        return "human_like"
    return None


def build_rows_for_combo(stats, feature_rows_by_addr, bot_min_tx, human_max_tx):
    """Returns (rows_for_training, per_address_relabel_summary)."""
    rows = []
    summary = []
    for addr, rec in stats.items():
        new_label = relabel(rec["tx_count"], bot_min_tx, human_max_tx)
        original_label = rec["original_label"]
        summary.append({
            "address": addr,
            "tx_count": rec["tx_count"],
            "original_label": original_label,
            "new_label": new_label,
            "changed": new_label != original_label,
        })
        if new_label is None:
            continue
        feat = feature_rows_by_addr.get(addr)
        if feat is None:
            continue  # no extracted-feature row for this address (e.g. <2 tx on disk)
        row = dict(feat)
        row["label_source"] = new_label
        rows.append(row)
    return rows, summary


def run_combo(mod, rows, bot_min_tx, human_max_tx):
    bot_rows = [r for r in rows if r["label_source"] == "bot_like"]
    human_rows = [r for r in rows if r["label_source"] == "human_like"]
    result = {
        "bot_min_tx": bot_min_tx,
        "human_max_tx": human_max_tx,
        "n_bot_like": len(bot_rows),
        "n_human_like": len(human_rows),
        "n_total": len(rows),
    }
    if not bot_rows or not human_rows:
        result["error"] = (
            f"cannot train -- need both classes, got {len(bot_rows)} bot_like, "
            f"{len(human_rows)} human_like at this threshold combo (within the "
            f"existing 264-address pool; see script docstring on scope)"
        )
        return result

    all_rows = bot_rows + human_rows
    X = mod.to_matrix(all_rows)
    y = np.array([1 if r["label_source"] == "bot_like" else 0 for r in all_rows])

    min_class_count = min(len(bot_rows), len(human_rows))
    if min_class_count < 4:
        result["error"] = (
            f"smallest class has only {min_class_count} rows at this threshold "
            f"combo -- too few for a stratified 25% held-out split / 5-fold CV; "
            f"skipping retrain, reporting sample size / balance only"
        )
        return result

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=mod.RANDOM_STATE, stratify=y
    )
    scaler = StandardScaler().fit(X_train)
    X_train_s, X_test_s = scaler.transform(X_train), scaler.transform(X_test)

    try:
        best_name, cv_summary = mod.select_model(X_train_s, y_train)
    except ValueError as e:
        result["error"] = f"model selection failed at this threshold combo: {e}"
        return result

    final_model = mod.CANDIDATE_MODELS[best_name]().fit(X_train_s, y_train)
    held_out_eval = mod.evaluate(final_model, X_test_s, y_test, "held_out_test_split_this_combo")

    result["model_selected"] = best_name
    result["cv_model_comparison"] = cv_summary
    result["held_out_test_eval"] = held_out_eval
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--out", default="classifier-service/sensitivity_results.json")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    mod = load_train_eval_module(repo_root)
    stats = load_lifetime_stats(repo_root)
    print(f"loaded lifetime tx_count for {len(stats)} addresses", file=sys.stderr)

    features_path = os.path.join(repo_root, mod.REAL_FEATURES_PATH)
    feature_rows = json.load(open(features_path))
    feature_rows_by_addr = {r["address"]: r for r in feature_rows}
    print(f"loaded {len(feature_rows_by_addr)} extracted feature rows "
          f"(addresses with <2 tx on disk are absent -- see REPORT.md §2.1)", file=sys.stderr)

    combos = list(itertools.product(BOT_MIN_TX_GRID, HUMAN_MAX_TX_GRID))
    all_results = []
    for bot_min_tx, human_max_tx in combos:
        rows, summary = build_rows_for_combo(stats, feature_rows_by_addr, bot_min_tx, human_max_tx)
        is_current = (bot_min_tx == CURRENT_BOT_MIN_TX and human_max_tx == CURRENT_HUMAN_MAX_TX)

        n_changed = sum(1 for s in summary if s["changed"])
        n_dropped_to_excluded = sum(1 for s in summary if s["changed"] and s["new_label"] is None)
        n_bot_to_human = sum(1 for s in summary if s["original_label"] == "bot_like" and s["new_label"] == "human_like")
        n_human_to_bot = sum(1 for s in summary if s["original_label"] == "human_like" and s["new_label"] == "bot_like")

        print(f"\n=== bot_min_tx={bot_min_tx} human_max_tx={human_max_tx}"
              f"{'  <-- CURRENT SETTING' if is_current else ''} ===", file=sys.stderr)
        combo_result = run_combo(mod, rows, bot_min_tx, human_max_tx)
        combo_result["is_current_setting"] = is_current
        combo_result["address_overlap"] = {
            "n_addresses_considered": len(summary),
            "n_label_unchanged": len(summary) - n_changed,
            "n_label_changed_total": n_changed,
            "n_dropped_to_excluded": n_dropped_to_excluded,
            "n_bot_like_to_human_like": n_bot_to_human,
            "n_human_like_to_bot_like": n_human_to_bot,
        }
        all_results.append(combo_result)

        if "error" in combo_result:
            print(f"  {combo_result['error']}", file=sys.stderr)
        else:
            print(f"  n_bot_like={combo_result['n_bot_like']} n_human_like={combo_result['n_human_like']}  "
                  f"model={combo_result['model_selected']}  "
                  f"held_out_acc={combo_result['held_out_test_eval']['accuracy']*100:.1f}%", file=sys.stderr)
        print(f"  vs current (50/1000) labels: {n_changed} changed "
              f"({n_dropped_to_excluded} -> excluded, "
              f"{n_bot_to_human} bot->human, {n_human_to_bot} human->bot)", file=sys.stderr)

    out_path = os.path.join(repo_root, args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "scope_limitation": (
                "Relabeling was applied only to the existing 264-address committed "
                "pool (addresses already fetched under the current 50/1000 "
                "thresholds). Loosening thresholds may in principle admit "
                "addresses never fetched; those cannot be recovered here -- see "
                "module docstring."
            ),
            "current_setting": {"bot_min_tx": CURRENT_BOT_MIN_TX, "human_max_tx": CURRENT_HUMAN_MAX_TX},
            "results": all_results,
        }, f, indent=2)
    print(f"\nwrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
