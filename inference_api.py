from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from inference_service import (
    InferencePipeline,
    BehavioralProfile,
    SupportState,
    BehavioralStructure
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="CKB Wallet Behavioral Analysis API",
    description="Analyze CKB wallet on-chain behavioral patterns",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global pipeline instance
pipeline: Optional[InferencePipeline] = None


class WalletAnalysisRequest(BaseModel):
    """Request model for wallet analysis."""
    wallet_address: str = Field(
        ...,
        description="CKB wallet address or lock hash",
        example="ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
    )
    use_live_data: bool = Field(
        False,
        description="Fetch live data from CKB Explorer (slower but more current)"
    )


class FeatureDTO(BaseModel):
    """Data transfer object for features."""
    name: str
    family: str
    value: Optional[float | str | dict] = None
    support_state: str
    evidence_count: int
    description: str


class BehavioralAssessmentDTO(BaseModel):
    """Data transfer object for behavioral assessment."""
    structure: str
    confidence: float
    description: str


class SupportSummaryDTO(BaseModel):
    """Data transfer object for support summary."""
    supported: int
    partial: int
    insufficient: int
    missing: int


class WalletAnalysisResponse(BaseModel):
    """Response model for wallet analysis."""
    wallet_address: str
    lock_hash: Optional[str]
    analysis_timestamp: str
    observation_period: dict
    observation_counts: dict
    features: dict[str, FeatureDTO]
    behavioral_assessment: BehavioralAssessmentDTO
    support_summary: SupportSummaryDTO
    quality_assessment: dict
    
    class Config:
        schema_extra = {
            "example": {
                "wallet_address": "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf",
                "lock_hash": None,
                "analysis_timestamp": "2026-09-07T12:00:00+00:00",
                "observation_period": {
                    "start": "2026-08-01T00:00:00",
                    "end": "2026-08-31T00:00:00"
                },
                "observation_counts": {
                    "total_transactions": 42,
                    "total_inputs": 87,
                    "total_outputs": 95,
                    "observed_cells": 85,
                    "spent_cells": 42
                },
                "features": {
                    "gap_mean_seconds": {
                        "name": "gap_mean_seconds",
                        "family": "temporal",
                        "value": 86400.5,
                        "support_state": "SUPPORTED",
                        "evidence_count": 41,
                        "description": "Mean time between consecutive transactions (seconds)"
                    }
                },
                "behavioral_assessment": {
                    "structure": "SCRIPT_TYPE_DIVERSE_STRUCTURE",
                    "confidence": 0.65,
                    "description": "Wallet exhibits diverse script type interactions..."
                },
                "support_summary": {
                    "supported": 8,
                    "partial": 0,
                    "insufficient": 2,
                    "missing": 0
                },
                "quality_assessment": {
                    "notes": ["Analysis based on 42 transactions..."],
                    "limitations": ["No identity classification performed..."]
                }
            }
        }


class HealthCheckResponse(BaseModel):
    """Response model for health check."""
    status: str
    pipeline_ready: bool
    database_path: Optional[str] = None
    timestamp: str


class ErrorResponse(BaseModel):
    """Response model for errors."""
    error: str
    detail: Optional[str] = None
    timestamp: str


@app.on_event("startup")
async def startup_event():
    """Initialize pipeline on startup."""
    global pipeline
    
    logger.info("Initializing inference pipeline...")
    
    try:
        db_path = Path("ckb_data/ckb-behaviour-dataset-v1.sqlite")
        pipeline = InferencePipeline(db_path, use_live_data=False)
        logger.info("Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        logger.warning("Pipeline will be unavailable until fixed")


@app.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health Check",
    tags=["System"]
)
async def health_check():
    """Check API health and readiness."""
    return HealthCheckResponse(
        status="healthy" if pipeline else "degraded",
        pipeline_ready=pipeline is not None,
        database_path="ckb_data/ckb-behaviour-dataset-v1.sqlite",
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@app.post(
    "/analyze",
    response_model=WalletAnalysisResponse,
    summary="Analyze Wallet Behavior",
    tags=["Analysis"]
)
async def analyze_wallet(request: WalletAnalysisRequest):
    """
    Analyze a CKB wallet's on-chain behavioral patterns.
    
    Takes only a wallet address and returns:
    - Extracted behavioral features (temporal, topology, capacity, scripts)
    - Behavioral structure classification
    - Feature support and quality metrics
    - Limitations and disclaimers
    
    **Important:** This analysis describes OBSERVABLE PATTERNS ONLY.
    It is NOT a human/bot identity classifier.
    """
    if not pipeline:
        raise HTTPException(
            status_code=503,
            detail="Analysis service not available. Database not loaded."
        )
    
    logger.info(f"Analyzing wallet: {request.wallet_address}")
    
    try:
        # Run analysis (per-request use_live_data overrides the pipeline's
        # startup default, so a single global pipeline can serve both
        # cached and live requests)
        profile = await pipeline.analyze_wallet(
            request.wallet_address,
            use_live_data=request.use_live_data,
        )
        
        # Convert to response model
        response = WalletAnalysisResponse(
            wallet_address=profile.wallet_address,
            lock_hash=profile.lock_hash,
            analysis_timestamp=profile.analysis_timestamp,
            observation_period={
                "start": profile.observation_period_start,
                "end": profile.observation_period_end
            },
            observation_counts={
                "total_transactions": profile.total_transactions,
                "total_inputs": profile.total_inputs,
                "total_outputs": profile.total_outputs,
                "observed_cells": profile.observed_cells,
                "spent_cells": profile.spent_cells
            },
            features={
                name: FeatureDTO(
                    name=feat.name,
                    family=feat.family,
                    value=feat.value,
                    support_state=feat.support_state.value,
                    evidence_count=feat.evidence_count,
                    description=feat.description
                )
                for name, feat in profile.features.items()
            },
            behavioral_assessment=BehavioralAssessmentDTO(
                structure=profile.behavioral_structure.value,
                confidence=profile.behavioral_confidence,
                description=profile.structure_description
            ),
            support_summary=SupportSummaryDTO(
                supported=profile.supported_features,
                partial=profile.partial_features,
                insufficient=profile.insufficient_features,
                missing=profile.missing_features
            ),
            quality_assessment={
                "notes": profile.data_quality_notes,
                "limitations": profile.limitations
            }
        )
        
        logger.info(f"Analysis completed for {request.wallet_address}")
        return response
        
    except Exception as e:
        logger.error(f"Error analyzing wallet: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


@app.get(
    "/docs-overview",
    summary="API Overview",
    tags=["Documentation"]
)
async def docs_overview():
    """Get API documentation overview."""
    return {
        "title": "CKB Wallet Behavioral Analysis API",
        "version": "1.0.0",
        "endpoints": [
            {
                "path": "/health",
                "method": "GET",
                "description": "Check API health and readiness"
            },
            {
                "path": "/analyze",
                "method": "POST",
                "description": "Analyze wallet behavioral patterns"
            }
        ],
        "important_disclaimers": [
            "This API analyzes OBSERVABLE ON-CHAIN BEHAVIORAL PATTERNS ONLY",
            "It is NOT a human/bot identity classifier",
            "Results represent exploratory structural patterns, not verified identities",
            "Analysis is based on fixed historical dataset (August 2026)",
            "Temporal generalization not supported with single 30-day window"
        ],
        "data_sources": [
            "Frozen CKB mainnet transaction data (August 1-31, 2026)",
            "Live CKB Explorer API (optional, if use_live_data=true)",
            "Feature extraction from V2 pipeline (CKB-native cell model)"
        ]
    }


@app.get(
    "/features-reference",
    summary="Features Reference",
    tags=["Documentation"]
)
async def features_reference():
    """Get reference information about extracted features."""
    return {
        "features_overview": {
            "temporal": {
                "description": "Time-based patterns in transaction sequence",
                "features": [
                    "gap_mean_seconds - average time between transactions",
                    "gap_std_seconds - variability in transaction timing",
                    "gap_min_seconds - minimum gap between transactions",
                    "gap_max_seconds - maximum gap between transactions"
                ]
            },
            "topology": {
                "description": "Input/output structure and consolidation patterns",
                "features": [
                    "avg_inputs_per_tx - average inputs per transaction",
                    "avg_outputs_per_tx - average outputs per transaction",
                    "max_inputs - maximum inputs in single transaction",
                    "consolidation_ratio - fraction of consolidating transactions"
                ]
            },
            "capacity": {
                "description": "Cell value (capacity) characteristics",
                "features": [
                    "avg_output_capacity_ckb - average output value",
                    "total_output_capacity_ckb - total value transferred",
                    "capacity_volatility - variability in output values"
                ]
            },
            "scripts": {
                "description": "Script type diversity and usage patterns",
                "features": [
                    "unique_lock_types - number of different lock script types",
                    "unique_type_scripts - number of different type script families"
                ]
            }
        },
        "support_states": {
            "SUPPORTED": "Feature has sufficient evidence (recommended for analysis)",
            "PARTIAL": "Feature has limited evidence (use with caution)",
            "INSUFFICIENT_EVIDENCE": "Feature lacks adequate evidence (unreliable)",
            "UNRESOLVED": "Feature could not be computed from available data",
            "NOT_APPLICABLE": "Feature not applicable to this wallet"
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )