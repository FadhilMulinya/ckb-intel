import json
import logging
import argparse

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder

import config
from features import FEATURE_COLUMNS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("ckb_wallet_intel.train_model")

DATASET_PATH = f"{config.PROCESSED_DIR}/wallet_dataset.csv"
MODEL_PATH = f"{config.MODELS_DIR}/wallet_classifier.joblib"
ENCODER_PATH = f"{config.MODELS_DIR}/label_encoder.joblib"
FEATURE_COLUMNS_PATH = f"{config.MODELS_DIR}/feature_columns.json"
METRICS_PATH = f"{config.MODELS_DIR}/metrics.json"


def load_training_frame(path=DATASET_PATH, drop_insufficient_evidence=True):
    df = pd.read_csv(path)
    if drop_insufficient_evidence:
        # INSUFFICIENT_EVIDENCE wallets teach the model "low tx count -> label",
        # which is exactly the leakage the doc warns about (Section 26). We report
        # them separately at inference time via metadata.evidence_state instead.
        before = len(df)
        df = df[df["label"] != "INSUFFICIENT_EVIDENCE"].copy()
        logger.info("Dropped %d INSUFFICIENT_EVIDENCE rows (%d remain)", before - len(df), len(df))
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing expected feature columns: {missing}")
    return df


def train(df: pd.DataFrame, test_size: float = 0.25, random_state: int = 42):
    X = df[FEATURE_COLUMNS].fillna(0.0).values
    y_raw = df["label"].values

    encoder = LabelEncoder()
    y = encoder.fit_transform(y_raw)

    class_counts = pd.Series(y_raw).value_counts()
    stratify = y if class_counts.min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=stratify
    )

    clf = RandomForestClassifier(
        n_estimators=400,
        max_depth=None,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    all_label_ids = np.arange(len(encoder.classes_))
    report = classification_report(
        y_test, y_pred, labels=all_label_ids, target_names=encoder.classes_,
        output_dict=True, zero_division=0,
    )
    cm = confusion_matrix(y_test, y_pred, labels=all_label_ids).tolist()

    cv_scores = None
    min_class = class_counts.min()
    if min_class >= 3:
        skf = StratifiedKFold(n_splits=min(5, int(min_class)), shuffle=True, random_state=random_state)
        cv_scores = cross_val_score(clf, X, y, cv=skf, scoring="f1_macro").tolist()

    importances = sorted(
        zip(FEATURE_COLUMNS, clf.feature_importances_.tolist()), key=lambda kv: -kv[1]
    )

    metrics = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "classes": encoder.classes_.tolist(),
        "classification_report": report,
        "confusion_matrix": cm,
        "cv_f1_macro_scores": cv_scores,
        "top_20_feature_importances": importances[:20],
    }

    joblib.dump(clf, MODEL_PATH)
    joblib.dump(encoder, ENCODER_PATH)
    with open(FEATURE_COLUMNS_PATH, "w") as f:
        json.dump(FEATURE_COLUMNS, f)
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    logger.info("Saved model -> %s", MODEL_PATH)
    logger.info("Held-out macro F1: %.3f", report["macro avg"]["f1-score"])
    if cv_scores:
        logger.info("5-fold CV F1 macro: mean=%.3f std=%.3f", float(np.mean(cv_scores)), float(np.std(cv_scores)))
    logger.info("Top features:\n%s", "\n".join(f"  {k}: {v:.4f}" for k, v in importances[:10]))
    return clf, encoder, metrics


def explore_clusters(df: pd.DataFrame, k: int = 6):
    """Phase B (Section 28): unsupervised view for manual cluster review, independent
    of the heuristic labels. Not used at inference time -- purely diagnostic."""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    X = df[FEATURE_COLUMNS].fillna(0.0).values
    Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(Xs)
    df = df.copy()
    df["cluster"] = km.labels_
    crosstab = pd.crosstab(df["cluster"], df["label"])
    logger.info("Cluster x heuristic-label crosstab (Phase B review target):\n%s", crosstab.to_string())
    return df, crosstab


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Train the CKB wallet behaviour classifier.")
    p.add_argument("--dataset", default=DATASET_PATH)
    p.add_argument("--explore", action="store_true", help="Also run unsupervised cluster review.")
    args = p.parse_args()

    frame = load_training_frame(args.dataset)
    train(frame)
    if args.explore:
        explore_clusters(frame)
