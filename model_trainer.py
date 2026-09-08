#!/usr/bin/env python3
"""
Model Trainer - Trains behavioral clustering models on frozen dataset

This module trains unsupervised clustering models (HDBSCAN, GMM) on the frozen
CKB wallet dataset using the High-Confidence feature matrix (10 features, 513 wallets).

Models are trained without labels and represent observable behavioral structures only.
"""
from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

try:
    import hdbscan
    HAS_HDBSCAN = True
except ImportError:
    HAS_HDBSCAN = False

try:
    from sklearn.mixture import GaussianMixture
    HAS_GMM = True
except ImportError:
    HAS_GMM = False

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Trains clustering models on frozen CKB wallet dataset."""
    
    # High-Confidence features used for training (from Feature Engineering V2)
    HIGH_CONFIDENCE_FEATURES = [
        "capacity__target_consumed_capacity",
        "capacity__target_net_capacity_delta",
        "capacity__capacity_repeat_ratio",
        "lineage__lineage_depth",
        "lineage__continuation_count",
        "lineage__lineage_repetition",
        "lineage__merge_count",
        "scripts__type_family_count",
        "scripts__unique_lock_script_count",
        "scripts__unique_type_script_count",
    ]
    
    def __init__(self, frozen_csv_path: Path, output_dir: Path):
        """
        Initialize model trainer.
        
        Args:
            frozen_csv_path: Path to frozen dataset feature CSV
            output_dir: Directory to save trained models
        """
        self.frozen_csv_path = frozen_csv_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.data = None
        self.X_raw = None
        self.X_scaled = None
        self.X_pca = None
        self.scaler = None
        self.pca = None
        self.models = {}
    
    def load_frozen_dataset(self) -> pd.DataFrame:
        """Load frozen dataset features."""
        logger.info(f"Loading frozen dataset from {self.frozen_csv_path}")
        
        if not self.frozen_csv_path.exists():
            raise FileNotFoundError(f"Frozen dataset not found: {self.frozen_csv_path}")
        
        self.data = pd.read_csv(self.frozen_csv_path)
        logger.info(f"Loaded {len(self.data)} wallets with {len(self.data.columns)} columns")
        
        return self.data
    
    def prepare_high_confidence_matrix(self) -> np.ndarray:
        """Prepare High-Confidence feature matrix (10 features, complete cases only)."""
        if self.data is None:
            raise RuntimeError("Must load dataset first")
        
        logger.info(f"Preparing High-Confidence matrix with {len(self.HIGH_CONFIDENCE_FEATURES)} features")
        
        # Select only High-Confidence features
        X = self.data[self.HIGH_CONFIDENCE_FEATURES].copy()
        
        # Remove rows with any missing values (complete cases only)
        X_complete = X.dropna()
        
        logger.info(f"Complete cases: {len(X_complete)}/{len(X)} ({100*len(X_complete)/len(X):.1f}%)")
        logger.info(f"Selected features: {len(X_complete.columns)}")
        logger.info(f"Feature summary:\n{X_complete.describe()}")
        
        self.X_raw = X_complete.values
        return self.X_raw
    
    def scale_features(self) -> np.ndarray:
        """Scale features using StandardScaler."""
        if self.X_raw is None:
            raise RuntimeError("Must prepare feature matrix first")
        
        logger.info("Scaling features with StandardScaler")
        self.scaler = StandardScaler()
        self.X_scaled = self.scaler.fit_transform(self.X_raw)
        
        logger.info(f"Scaled matrix shape: {self.X_scaled.shape}")
        logger.info(f"Mean: {self.X_scaled.mean(axis=0)}")
        logger.info(f"Std: {self.X_scaled.std(axis=0)}")
        
        # Save scaler
        scaler_path = self.output_dir / "scaler.pkl"
        with open(scaler_path, "wb") as f:
            pickle.dump(self.scaler, f)
        logger.info(f"Saved scaler to {scaler_path}")
        
        return self.X_scaled
    
    def apply_pca(self, n_components: int = 4) -> tuple[np.ndarray, dict]:
        """Apply PCA dimensionality reduction."""
        if self.X_scaled is None:
            raise RuntimeError("Must scale features first")
        
        logger.info(f"Applying PCA with {n_components} components")
        self.pca = PCA(n_components=n_components)
        self.X_pca = self.pca.fit_transform(self.X_scaled)
        
        # Log variance explained
        cumsum_var = np.cumsum(self.pca.explained_variance_ratio_)
        logger.info(f"Variance explained: {self.pca.explained_variance_ratio_}")
        logger.info(f"Cumulative variance: {cumsum_var}")
        
        # Save PCA model
        pca_path = self.output_dir / "pca_model.pkl"
        with open(pca_path, "wb") as f:
            pickle.dump(self.pca, f)
        logger.info(f"Saved PCA model to {pca_path}")
        
        # Save PCA analysis
        pca_info = {
            "n_components": n_components,
            "explained_variance": self.pca.explained_variance_ratio_.tolist(),
            "cumulative_variance": cumsum_var.tolist(),
            "components_shape": self.X_pca.shape,
            "loadings": {
                f"PC{i+1}": self.pca.components_[i].tolist()
                for i in range(n_components)
            }
        }
        
        pca_info_path = self.output_dir / "pca_analysis.json"
        with open(pca_info_path, "w") as f:
            json.dump(pca_info, f, indent=2)
        logger.info(f"Saved PCA analysis to {pca_info_path}")
        
        return self.X_pca, pca_info
    
    def train_hdbscan(self) -> dict:
        """Train HDBSCAN clustering model."""
        if not HAS_HDBSCAN:
            logger.warning("HDBSCAN not installed; skipping")
            return {}
        
        if self.X_pca is None:
            raise RuntimeError("Must apply PCA first")
        
        logger.info("Training HDBSCAN model")
        
        # Reference parameters from Phase 2 analysis
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=20,
            min_samples=10,
            metric='euclidean',
            cluster_selection_epsilon=0.5,
            allow_single_cluster=False
        )
        
        labels = clusterer.fit_predict(self.X_pca)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_noise = list(labels).count(-1)
        
        logger.info(f"Found {n_clusters} clusters with {n_noise} noise points")
        logger.info(f"Cluster distribution: {np.bincount(labels[labels >= 0])}")
        
        # Save model
        model_path = self.output_dir / "hdbscan_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(clusterer, f)
        logger.info(f"Saved HDBSCAN model to {model_path}")
        
        # Save clustering results
        clustering_info = {
            "model": "HDBSCAN",
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "cluster_sizes": np.bincount(labels[labels >= 0]).tolist(),
            "labels": labels.tolist(),
            "parameters": {
                "min_cluster_size": 20,
                "min_samples": 10,
                "metric": "euclidean",
                "cluster_selection_epsilon": 0.5
            }
        }
        
        clustering_path = self.output_dir / "hdbscan_clustering.json"
        with open(clustering_path, "w") as f:
            json.dump(clustering_info, f, indent=2)
        logger.info(f"Saved HDBSCAN results to {clustering_path}")
        
        self.models["hdbscan"] = {
            "model": clusterer,
            "labels": labels,
            "info": clustering_info
        }
        
        return clustering_info
    
    def train_gmm(self) -> dict:
        """Train Gaussian Mixture Model."""
        if not HAS_GMM:
            logger.warning("GaussianMixture not installed; skipping")
            return {}
        
        if self.X_pca is None:
            raise RuntimeError("Must apply PCA first")
        
        logger.info("Training Gaussian Mixture Model")
        
        # Test multiple components
        best_model = None
        best_n = 3
        best_bic = float('inf')
        
        for n_components in [1, 2, 3, 4, 5]:
            gmm = GaussianMixture(
                n_components=n_components,
                covariance_type="diag",
                random_state=42,
                n_init=10
            )
            gmm.fit(self.X_pca)
            bic = gmm.bic(self.X_pca)
            
            logger.info(f"n_components={n_components}: BIC={bic:.2f}")
            
            if bic < best_bic:
                best_bic = bic
                best_model = gmm
                best_n = n_components
        
        logger.info(f"Best model: {best_n} components (BIC={best_bic:.2f})")
        
        labels = best_model.predict(self.X_pca)
        
        # Save model
        model_path = self.output_dir / "gmm_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(best_model, f)
        logger.info(f"Saved GMM model to {model_path}")
        
        # Save clustering results
        clustering_info = {
            "model": "GaussianMixture",
            "n_components": best_n,
            "bic": best_bic,
            "aic": best_model.aic(self.X_pca),
            "cluster_sizes": np.bincount(labels).tolist(),
            "labels": labels.tolist(),
            "parameters": {
                "covariance_type": "diag",
                "random_state": 42
            }
        }
        
        clustering_path = self.output_dir / "gmm_clustering.json"
        with open(clustering_path, "w") as f:
            json.dump(clustering_info, f, indent=2)
        logger.info(f"Saved GMM results to {clustering_path}")
        
        self.models["gmm"] = {
            "model": best_model,
            "labels": labels,
            "info": clustering_info
        }
        
        return clustering_info
    
    def generate_training_summary(self) -> dict:
        """Generate comprehensive training summary."""
        summary = {
            "dataset": {
                "total_rows": len(self.data) if self.data is not None else 0,
                "complete_cases": len(self.X_raw) if self.X_raw is not None else 0,
                "features_used": self.HIGH_CONFIDENCE_FEATURES,
                "n_features": len(self.HIGH_CONFIDENCE_FEATURES)
            },
            "preprocessing": {
                "scaler": "StandardScaler",
                "scaler_saved": (self.output_dir / "scaler.pkl").exists()
            },
            "dimensionality_reduction": {
                "method": "PCA",
                "n_components": len(self.pca.explained_variance_ratio_) if self.pca else 0,
                "variance_explained": (
                    self.pca.explained_variance_ratio_.tolist() if self.pca else []
                )
            },
            "models_trained": []
        }
        
        for model_name, model_info in self.models.items():
            summary["models_trained"].append({
                "name": model_name,
                "info": model_info["info"]
            })
        
        return summary


def train_models(
    frozen_csv: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> dict:
    """
    Train all models on frozen dataset.
    
    Args:
        frozen_csv: Path to frozen dataset CSV
        output_dir: Output directory for models
    
    Returns:
        Training summary
    """
    if frozen_csv is None:
        frozen_csv = Path("ckb_data/feature_engineering_v2/wallet_behaviour_features_v2_ml.csv")
    
    if output_dir is None:
        output_dir = Path("models/trained_models")
    
    logging.basicConfig(level=logging.INFO)
    
    trainer = ModelTrainer(frozen_csv, output_dir)
    
    try:
        # Load and prepare data
        trainer.load_frozen_dataset()
        trainer.prepare_high_confidence_matrix()
        trainer.scale_features()
        trainer.apply_pca(n_components=4)
        
        # Train models
        trainer.train_hdbscan()
        trainer.train_gmm()
        
        # Generate summary
        summary = trainer.generate_training_summary()
        
        summary_path = output_dir / "training_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Saved training summary to {summary_path}")
        
        return summary
        
    except Exception as e:
        logger.error(f"Error during training: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    summary = train_models()
    print(json.dumps(summary, indent=2))
