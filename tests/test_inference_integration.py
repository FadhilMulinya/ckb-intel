#!/usr/bin/env python3
"""
Integration Tests for Inference Pipeline

Tests the complete data flow: address → collection → feature extraction → classification
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import pytest

from inference_service import (
    InferencePipeline,
    BehavioralProfile,
    SupportState,
    BehavioralStructure
)
from model_trainer import ModelTrainer

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def db_path() -> Path:
    """Get frozen database path."""
    return Path("ckb_data/ckb_data_v2/ckb_explorer.sqlite")


@pytest.fixture
def pipeline(db_path) -> InferencePipeline:
    """Create inference pipeline instance."""
    if not db_path.exists():
        pytest.skip("Database not available")
    return InferencePipeline(db_path, use_live_data=False)


@pytest.fixture
def model_trainer(db_path) -> ModelTrainer:
    """Create model trainer instance."""
    if not db_path.exists():
        pytest.skip("Database not available")
    output_dir = Path("models/test_outputs")
    return ModelTrainer(db_path, output_dir)


@pytest.fixture
async def sample_profiles(pipeline) -> dict[str, BehavioralProfile]:
    """Generate sample profiles for testing."""
    # Use diverse addresses from frozen dataset
    test_addresses = [
        "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf",
        "ckt1qyqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsn4ewu",
        "ckt1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqsk0gzd",
    ]
    
    profiles = {}
    for addr in test_addresses:
        try:
            profile = await pipeline.analyze_wallet(addr)
            profiles[addr] = profile
        except Exception as e:
            logger.warning(f"Failed to analyze {addr}: {e}")
    
    return profiles


# ============================================================================
# PIPELINE INITIALIZATION TESTS
# ============================================================================

class TestPipelineInitialization:
    """Test pipeline initialization."""
    
    def test_pipeline_creation(self, pipeline):
        """Test that pipeline initializes correctly."""
        assert pipeline is not None
        assert pipeline.collector is not None
        assert pipeline.extractor is not None
        assert pipeline.classifier is not None
    
    def test_database_validation(self, db_path):
        """Test that database exists and is valid."""
        assert db_path.exists(), f"Database not found at {db_path}"
        assert db_path.stat().st_size > 0, "Database is empty"


# ============================================================================
# DATA COLLECTION TESTS
# ============================================================================

class TestDataCollection:
    """Test transaction data collection."""
    
    @pytest.mark.asyncio
    async def test_collect_valid_address(self, pipeline):
        """Test collecting data for valid wallet address."""
        address = "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
        
        transactions = await pipeline.collector.fetch_wallet_transactions(address)
        
        assert transactions is not None
        assert len(transactions) > 0
        assert all("hash" in tx for tx in transactions)
        assert all("inputs" in tx for tx in transactions)
        assert all("outputs" in tx for tx in transactions)
    
    @pytest.mark.asyncio
    async def test_invalid_address_handling(self, pipeline):
        """Test handling of invalid addresses."""
        invalid_address = "invalid_address_xyz"
        
        # Should handle gracefully (return empty or raise)
        with pytest.raises((ValueError, Exception)):
            await pipeline.collector.fetch_wallet_transactions(invalid_address)
    
    @pytest.mark.asyncio
    async def test_address_normalization(self, pipeline):
        """Test that addresses are normalized correctly."""
        # Test both formats
        short_address = "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
        
        tx1 = await pipeline.collector.fetch_wallet_transactions(short_address)
        assert len(tx1) > 0


# ============================================================================
# FEATURE EXTRACTION TESTS
# ============================================================================

class TestFeatureExtraction:
    """Test feature extraction pipeline."""
    
    @pytest.mark.asyncio
    async def test_feature_extraction_completeness(self, pipeline, sample_profiles):
        """Test that features are extracted for wallets."""
        for addr, profile in sample_profiles.items():
            assert profile.features is not None
            assert len(profile.features) > 0
            
            # Check for key feature families
            family_counts = {}
            for feat in profile.features.values():
                family = feat.family
                family_counts[family] = family_counts.get(family, 0) + 1
            
            logger.info(f"{addr}: {family_counts}")
            assert len(family_counts) > 0, f"No features extracted for {addr}"
    
    def test_feature_value_types(self, pipeline):
        """Test that feature values are appropriate types."""
        # Create sample features
        from inference_service import FeatureResult
        
        # Numeric feature
        feat_numeric = FeatureResult(
            name="test_numeric",
            family="temporal",
            value=123.45,
            support_state=SupportState.SUPPORTED,
            evidence_count=10,
            description="Test numeric feature"
        )
        assert isinstance(feat_numeric.value, (int, float))
        
        # Dict feature
        feat_dict = FeatureResult(
            name="test_dict",
            family="topology",
            value={"key": "value"},
            support_state=SupportState.SUPPORTED,
            evidence_count=5,
            description="Test dict feature"
        )
        assert isinstance(feat_dict.value, dict)
    
    @pytest.mark.asyncio
    async def test_temporal_features(self, pipeline, sample_profiles):
        """Test temporal feature extraction."""
        for profile in sample_profiles.values():
            temporal_features = [
                f for f in profile.features.values()
                if f.family == "temporal"
            ]
            
            assert len(temporal_features) > 0, "No temporal features extracted"
            
            for feat in temporal_features:
                if feat.value is not None:
                    assert isinstance(feat.value, (int, float))
                    assert feat.value >= 0, f"Negative temporal value: {feat.value}"
    
    @pytest.mark.asyncio
    async def test_topology_features(self, pipeline, sample_profiles):
        """Test topology feature extraction."""
        for profile in sample_profiles.values():
            topology_features = [
                f for f in profile.features.values()
                if f.family == "topology"
            ]
            
            assert len(topology_features) > 0, "No topology features extracted"
            
            for feat in topology_features:
                if feat.value is not None:
                    assert isinstance(feat.value, (int, float))
    
    @pytest.mark.asyncio
    async def test_capacity_features(self, pipeline, sample_profiles):
        """Test capacity feature extraction."""
        for profile in sample_profiles.values():
            capacity_features = [
                f for f in profile.features.values()
                if f.family == "capacity"
            ]
            
            for feat in capacity_features:
                if feat.value is not None:
                    assert isinstance(feat.value, (int, float))
                    # Capacity should be non-negative
                    assert feat.value >= 0
    
    @pytest.mark.asyncio
    async def test_script_features(self, pipeline, sample_profiles):
        """Test script feature extraction."""
        for profile in sample_profiles.values():
            script_features = [
                f for f in profile.features.values()
                if f.family == "scripts"
            ]
            
            for feat in script_features:
                if feat.value is not None:
                    # Script counts should be positive integers
                    assert isinstance(feat.value, (int, float))
                    assert feat.value >= 0


# ============================================================================
# SUPPORT CLASSIFICATION TESTS
# ============================================================================

class TestSupportClassification:
    """Test feature support state classification."""
    
    @pytest.mark.asyncio
    async def test_support_states_assigned(self, pipeline, sample_profiles):
        """Test that support states are assigned to features."""
        for profile in sample_profiles.values():
            for feat in profile.features.values():
                assert feat.support_state in SupportState
                assert isinstance(feat.evidence_count, int)
                assert feat.evidence_count >= 0
    
    @pytest.mark.asyncio
    async def test_support_summary(self, pipeline, sample_profiles):
        """Test support summary counts."""
        for profile in sample_profiles.values():
            total_features = len(profile.features)
            
            total_summary = (
                profile.supported_features +
                profile.partial_features +
                profile.insufficient_features +
                profile.missing_features
            )
            
            assert total_summary == total_features, (
                f"Support summary mismatch: {total_summary} vs {total_features}"
            )


# ============================================================================
# BEHAVIORAL CLASSIFICATION TESTS
# ============================================================================

class TestBehavioralClassification:
    """Test behavioral structure classification."""
    
    @pytest.mark.asyncio
    async def test_structure_assignment(self, pipeline, sample_profiles):
        """Test that behavioral structures are assigned."""
        for profile in sample_profiles.values():
            assert profile.behavioral_structure in BehavioralStructure
            assert isinstance(profile.behavioral_confidence, float)
            assert 0 <= profile.behavioral_confidence <= 1
    
    @pytest.mark.asyncio
    async def test_structure_description(self, pipeline, sample_profiles):
        """Test that structure descriptions are provided."""
        for profile in sample_profiles.values():
            assert profile.structure_description is not None
            assert len(profile.structure_description) > 0
    
    @pytest.mark.asyncio
    async def test_confidence_scores(self, pipeline, sample_profiles):
        """Test confidence score validity."""
        for profile in sample_profiles.values():
            confidence = profile.behavioral_confidence
            
            # Confidence should be between 0 and 1
            assert 0 <= confidence <= 1
            
            # If confidence is high, structure should be well-defined
            if confidence > 0.7:
                assert profile.behavioral_structure != BehavioralStructure.UNKNOWN


# ============================================================================
# DATA QUALITY TESTS
# ============================================================================

class TestDataQuality:
    """Test data quality and validity."""
    
    @pytest.mark.asyncio
    async def test_quality_notes_present(self, pipeline, sample_profiles):
        """Test that quality notes are provided."""
        for profile in sample_profiles.values():
            assert profile.data_quality_notes is not None
            assert isinstance(profile.data_quality_notes, list)
    
    @pytest.mark.asyncio
    async def test_limitations_present(self, pipeline, sample_profiles):
        """Test that limitations are documented."""
        for profile in sample_profiles.values():
            assert profile.limitations is not None
            assert isinstance(profile.limitations, list)
    
    @pytest.mark.asyncio
    async def test_observation_counts_valid(self, pipeline, sample_profiles):
        """Test that observation counts are valid."""
        for profile in sample_profiles.values():
            assert profile.total_transactions >= 0
            assert profile.total_inputs >= 0
            assert profile.total_outputs >= 0
            assert profile.observed_cells >= 0
            assert profile.spent_cells >= 0
            
            # Sanity checks
            if profile.total_transactions > 0:
                # Should have inputs and outputs
                assert profile.total_inputs > 0
                assert profile.total_outputs > 0


# ============================================================================
# SERIALIZATION TESTS
# ============================================================================

class TestSerialization:
    """Test profile serialization and JSON export."""
    
    @pytest.mark.asyncio
    async def test_to_dict_conversion(self, pipeline, sample_profiles):
        """Test conversion to dictionary."""
        for profile in sample_profiles.values():
            profile_dict = profile.to_dict()
            
            assert isinstance(profile_dict, dict)
            assert "wallet_address" in profile_dict
            assert "behavioral_structure" in profile_dict
            assert "features" in profile_dict
    
    @pytest.mark.asyncio
    async def test_json_serialization(self, pipeline, sample_profiles):
        """Test JSON serialization."""
        for addr, profile in sample_profiles.items():
            # Should not raise
            json_str = json.dumps(profile.to_dict())
            
            # Should be parseable
            parsed = json.loads(json_str)
            assert parsed["wallet_address"] == addr


# ============================================================================
# MODEL TRAINING TESTS
# ============================================================================

class TestModelTraining:
    """Test model training pipeline."""
    
    def test_dataset_loading(self, model_trainer):
        """Test frozen dataset loading."""
        data = model_trainer.load_frozen_dataset()
        
        assert data is not None
        assert len(data) > 0
        logger.info(f"Loaded {len(data)} wallets")
    
    def test_high_confidence_matrix_preparation(self, model_trainer):
        """Test high-confidence matrix preparation."""
        model_trainer.load_frozen_dataset()
        X = model_trainer.prepare_high_confidence_matrix()
        
        assert X is not None
        assert X.shape[0] > 0
        assert X.shape[1] == 10  # 10 high-confidence features
        logger.info(f"High-confidence matrix: {X.shape}")
    
    def test_feature_scaling(self, model_trainer):
        """Test feature scaling."""
        model_trainer.load_frozen_dataset()
        model_trainer.prepare_high_confidence_matrix()
        X_scaled = model_trainer.scale_features()
        
        assert X_scaled is not None
        # Scaled features should have mean ~0 and std ~1
        assert abs(X_scaled.mean()) < 0.1
        assert abs(X_scaled.std() - 1.0) < 0.1
    
    def test_pca_application(self, model_trainer):
        """Test PCA dimensionality reduction."""
        model_trainer.load_frozen_dataset()
        model_trainer.prepare_high_confidence_matrix()
        model_trainer.scale_features()
        X_pca, pca_info = model_trainer.apply_pca(n_components=4)
        
        assert X_pca is not None
        assert X_pca.shape[1] == 4
        assert "explained_variance" in pca_info
        
        # Check variance explained
        total_var = sum(pca_info["explained_variance"])
        logger.info(f"PCA explained variance: {total_var:.2%}")
        assert total_var > 0.5  # Should explain at least 50%
    
    def test_training_output_artifacts(self, model_trainer):
        """Test that training creates expected artifacts."""
        model_trainer.load_frozen_dataset()
        model_trainer.prepare_high_confidence_matrix()
        model_trainer.scale_features()
        model_trainer.apply_pca(n_components=4)
        
        # Should create pickle files
        scaler_path = model_trainer.output_dir / "scaler.pkl"
        pca_path = model_trainer.output_dir / "pca_model.pkl"
        
        assert scaler_path.exists()
        assert pca_path.exists()


# ============================================================================
# END-TO-END TESTS
# ============================================================================

class TestEndToEnd:
    """Test complete pipeline from address to profile."""
    
    @pytest.mark.asyncio
    async def test_complete_analysis_flow(self, pipeline):
        """Test complete analysis workflow."""
        address = "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
        
        # Run complete analysis
        profile = await pipeline.analyze_wallet(address)
        
        # Verify all components present
        assert profile.wallet_address == address
        assert len(profile.features) > 0
        assert profile.behavioral_structure is not None
        assert 0 <= profile.behavioral_confidence <= 1
        
        logger.info(f"Complete analysis successful for {address}")
        logger.info(f"  Transactions: {profile.total_transactions}")
        logger.info(f"  Features: {len(profile.features)}")
        logger.info(f"  Structure: {profile.behavioral_structure.value}")
        logger.info(f"  Confidence: {profile.behavioral_confidence:.1%}")
    
    @pytest.mark.asyncio
    async def test_consistency_across_runs(self, pipeline):
        """Test that analysis is consistent across runs."""
        address = "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
        
        # Run analysis twice
        profile1 = await pipeline.analyze_wallet(address)
        profile2 = await pipeline.analyze_wallet(address)
        
        # Should be identical
        assert profile1.total_transactions == profile2.total_transactions
        assert profile1.behavioral_structure == profile2.behavioral_structure
        assert profile1.behavioral_confidence == profile2.behavioral_confidence


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

class TestPerformance:
    """Test pipeline performance."""
    
    @pytest.mark.asyncio
    async def test_analysis_latency(self, pipeline):
        """Test analysis latency."""
        import time
        
        address = "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
        
        start = time.time()
        profile = await pipeline.analyze_wallet(address)
        elapsed = time.time() - start
        
        logger.info(f"Analysis completed in {elapsed:.3f}s")
        
        # Should complete within reasonable time
        assert elapsed < 60  # Less than 60 seconds


# ============================================================================
# INTEGRATION TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    # Run with: pytest tests/test_inference_integration.py -v -s
    pytest.main([__file__, "-v", "-s"])
