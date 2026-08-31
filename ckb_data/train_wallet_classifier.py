from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RESERVED_COLS = {"address", "wallet_status", "segment", "cluster_id", "segment_confidence"}
DORMANT_LABEL = "Dormant / No Activity"
DORMANT_RULE_COL = "n_tx_in_window"
DORMANT_RULE_MAX = 0  


def detect_feature_cols(df: pd.DataFrame) -> list[str]:
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    return [c for c in numeric_cols if c not in RESERVED_COLS]


def train(args):
    from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.preprocessing import LabelEncoder
    import joblib

    df = pd.read_csv(args.data_file)
    if "address" in df.columns:
        df = df.set_index("address")

    if "segment" not in df.columns:
        raise SystemExit("--data-file must have a 'segment' column (the GMM-assigned label)")

    feature_cols = args.feature_cols.split(",") if args.feature_cols else detect_feature_cols(df)
    print(f"Using {len(feature_cols)} feature column(s): {feature_cols}")

    trainable = df[df["segment"] != DORMANT_LABEL].copy()
    n_dropped_dormant = len(df) - len(trainable)
    print(f"Excluded {n_dropped_dormant} Dormant wallet(s) from training (rule-based, not ML).")

    if "segment_confidence" in trainable.columns and args.min_confidence > 0:
        before = len(trainable)
        trainable = trainable[trainable["segment_confidence"].fillna(0) >= args.min_confidence]
        print(f"Filtered to segment_confidence >= {args.min_confidence}: "
              f"{before} -> {len(trainable)} wallet(s).")

    trainable = trainable.dropna(subset=["segment"])
    print(f"\nTraining population: {len(trainable)} wallet(s)")
    print(trainable["segment"].value_counts().to_string())

    from sklearn.impute import SimpleImputer
    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(trainable[feature_cols].values)
    n_imputed_cells = int(trainable[feature_cols].isna().sum().sum())
    if n_imputed_cells:
        print(f"Median-imputed {n_imputed_cells} missing feature value(s) across the training set "
              f"(e.g. gap_mean_s/gap_cv/burstiness are undefined for wallets with <2 timed "
              f"transactions -- consistent with how the original clustering pipeline handled this, "
              f"not dropped as rows).")
    y_raw = trainable["segment"].values
    le = LabelEncoder()
    y = le.fit_transform(y_raw)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, stratify=y
    )

    if args.model == "random_forest":
        clf = RandomForestClassifier(
            n_estimators=args.n_estimators, class_weight="balanced",
            random_state=args.random_state, n_jobs=-1,
        )
    elif args.model == "gradient_boosting":
        clf = GradientBoostingClassifier(n_estimators=args.n_estimators, random_state=args.random_state)
    else:
        clf = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=args.random_state)

    print(f"\nTraining {args.model}...")
    clf.fit(X_train, y_train)

    
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.random_state)
    cv_scores = cross_val_score(clf.__class__(**clf.get_params()), X, y, cv=cv, scoring="balanced_accuracy")

    y_pred = clf.predict(X_test)
    report = classification_report(y_test, y_pred, target_names=le.classes_, zero_division=0)
    cm = confusion_matrix(y_test, y_pred)

    print(f"\n5-fold CV balanced accuracy: {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")
    print(f"\nTest-set classification report:\n{report}")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    bundle = {
        "model": clf,
        "label_encoder": le,
        "feature_cols": feature_cols,
        "imputer": imputer,
        "dormant_rule": {"col": DORMANT_RULE_COL, "max_value": DORMANT_RULE_MAX, "label": DORMANT_LABEL},
        "model_type": args.model,
    }
    joblib.dump(bundle, args.out_dir / "wallet_classifier.joblib")
    print(f"\nWrote {args.out_dir / 'wallet_classifier.joblib'}")

    # Plots
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(le.classes_)))
    ax.set_xticklabels(le.classes_, rotation=45, ha="right")
    ax.set_yticks(range(len(le.classes_)))
    ax.set_yticklabels(le.classes_)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True (GMM label)")
    ax.set_title("Confusion matrix (test set)")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                     color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(args.out_dir / "confusion_matrix.png", dpi=140)
    plt.close(fig)

    if hasattr(clf, "feature_importances_"):
        importances = pd.Series(clf.feature_importances_, index=feature_cols).sort_values()
        fig, ax = plt.subplots(figsize=(7, max(3, 0.35 * len(feature_cols))))
        importances.plot(kind="barh", ax=ax, color="#4C72B0")
        ax.set_title(f"Feature importances ({args.model})")
        fig.tight_layout()
        fig.savefig(args.out_dir / "feature_importances.png", dpi=140)
        plt.close(fig)

    # Report
    lines = []
    lines.append("# Wallet Segment Classifier -- Training Report\n")
    lines.append(f"Model: **{args.model}**\n")
    lines.append("## What this model is (and isn't)\n")
    lines.append("This classifier reproduces the GMM clustering decision boundary from "
                 "CLUSTERING_REPORT.md so new wallets can be labeled quickly without "
                 "re-fitting GMM against the whole population every time. Its \"accuracy\" "
                 "measures agreement with GMM's own (heuristically-named) cluster "
                 "assignments, not ground-truth correctness of the archetype labels "
                 "themselves -- GMM was never validated against known bot/human/miner "
                 "wallets, so neither is this.\n")
    lines.append("Dormant wallets are handled by the same hard rule as the original "
                 f"pipeline (`{DORMANT_RULE_COL} <= {DORMANT_RULE_MAX}` -> "
                 f"`{DORMANT_LABEL}`) and never touch the ML model -- there's no "
                 "behavioral signal in a wallet with zero transactions to learn from.\n")
    lines.append(f"## Training population\n")
    lines.append(f"- {n_dropped_dormant} Dormant wallet(s) excluded (rule-based)")
    if args.min_confidence > 0:
        lines.append(f"- Filtered to segment_confidence >= {args.min_confidence}")
    lines.append(f"- {len(trainable)} wallet(s) used for training/evaluation")
    lines.append("\n" + trainable["segment"].value_counts().to_frame("n_wallets").to_string() + "\n")
    lines.append(f"## Cross-validation (5-fold, balanced accuracy)\n")
    lines.append(f"{cv_scores.mean():.3f} +/- {cv_scores.std():.3f} across folds: "
                 f"{[round(float(s), 3) for s in cv_scores]}\n")
    lines.append(f"## Test-set classification report\n```\n{report}```\n")
    lines.append("## Files\n")
    lines.append("- `wallet_classifier.joblib` -- the trained model bundle (model + label "
                 "encoder + feature list + Dormant rule). Load with `joblib.load()`.")
    lines.append("- `confusion_matrix.png`")
    if hasattr(clf, "feature_importances_"):
        lines.append("- `feature_importances.png`")
    lines.append("\n## Using this model on new wallets\n")
    lines.append("```bash\npython3 train_wallet_classifier.py --predict-file "
                 "new_wallets.csv --model-dir ./wallet_classifier --out-file predictions.csv\n```")
    (args.out_dir / "TRAINING_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.out_dir / 'TRAINING_REPORT.md'}")


def predict(args):
    import joblib

    bundle = joblib.load(args.model_dir / "wallet_classifier.joblib")
    clf, le, feature_cols = bundle["model"], bundle["label_encoder"], bundle["feature_cols"]
    imputer = bundle["imputer"]
    dormant_rule = bundle["dormant_rule"]

    df = pd.read_csv(args.predict_file)
    if "address" in df.columns:
        df = df.set_index("address")

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise SystemExit(f"--predict-file is missing required feature column(s): {missing}")

    is_dormant = df[dormant_rule["col"]].fillna(0) <= dormant_rule["max_value"]
    result = pd.DataFrame(index=df.index)
    result["predicted_segment"] = dormant_rule["label"]
    result["prediction_confidence"] = 1.0  

    to_classify = df.loc[~is_dormant, feature_cols]
    if len(to_classify):
        to_classify_filled = imputer.transform(to_classify.values)
        preds = clf.predict(to_classify_filled)
        probs = clf.predict_proba(to_classify_filled) if hasattr(clf, "predict_proba") else None
        result.loc[~is_dormant, "predicted_segment"] = le.inverse_transform(preds)
        if probs is not None:
            result.loc[~is_dormant, "prediction_confidence"] = probs.max(axis=1)

    result.to_csv(args.out_file)
    print(f"Classified {len(df)} wallet(s) ({is_dormant.sum()} by Dormant rule, "
          f"{(~is_dormant).sum()} by model). Wrote {args.out_file}")
    print(result["predicted_segment"].value_counts().to_string())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-file", type=Path, help="Training data (e.g. wallet_segments.csv)")
    p.add_argument("--out-dir", type=Path, default=Path("./wallet_classifier"))
    p.add_argument("--feature-cols", type=str, default=None,
                   help="Comma-separated feature column override. Default: auto-detect numeric columns.")
    p.add_argument("--min-confidence", type=float, default=0.0,
                   help="Drop training rows with segment_confidence below this. Default: 0.0 (no filtering)")
    p.add_argument("--model", choices=["random_forest", "gradient_boosting", "logistic_regression"],
                   default="random_forest")
    p.add_argument("--n-estimators", type=int, default=300)
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument("--random-state", type=int, default=0)

    p.add_argument("--predict-file", type=Path, help="New wallet feature CSV to classify")
    p.add_argument("--model-dir", type=Path, default=Path("./wallet_classifier"))
    p.add_argument("--out-file", type=Path, default=Path("./wallet_predictions.csv"))

    args = p.parse_args()

    if args.predict_file:
        predict(args)
    elif args.data_file:
        train(args)
    else:
        raise SystemExit("Provide either --data-file (to train) or --predict-file (to classify)")


if __name__ == "__main__":
    main()
