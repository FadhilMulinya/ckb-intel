<<<<<<< HEAD
# CKB Wallet Behavioral Analysis - Inference Pipeline

Complete production-ready ML inference system for analyzing CKB wallet on-chain behavioral patterns.

**Input:** CKB wallet address  
**Output:** Behavioral profile with feature analysis and structural classification  
**Important:** This is **BEHAVIORAL ANALYSIS ONLY** - NOT identity classification

## Overview

This inference pipeline implements the complete data flow:

```
CKB Wallet Address
        ↓
   [Live/Cached Data Collection]
        ↓
    [Transaction Normalization]
        ↓
   [Feature Extraction (V2)]
        ↓
  [Support Classification]
        ↓
 [Behavioral Classification]
        ↓
  Behavioral Profile
  (Features + Structure)
```

### Key Features

✅ **CKB-Native Model** - Proper cell transformation model, not account transfers  
✅ **Evidence-Driven** - 12 transparent feature extraction rules  
✅ **Support-Aware** - Features classified by evidence availability  
✅ **No Identity Claims** - Describes patterns only  
✅ **Reproducible** - Same features as frozen dataset analysis  
✅ **Multiple Interfaces** - CLI, REST API, Python library  

## Installation

### Prerequisites

- Python 3.8+
- CKB Explorer API access (optional, for live data)
- Frozen dataset database (required for inference)

### Setup

```bash
# 1. Clone repository
git clone https://github.com/FadhilMulinya/ckb-intel.git
cd ckb-intel

# 2. Install dependencies
pip install -r requirements-research.txt
pip install -e .  # Install inference modules

# 3. Download frozen dataset
# From: https://github.com/FadhilMulinya/ckb-intel/releases/tag/ckb-behaviour-dataset-v1
# Download: ckb-behaviour-dataset-v1.sqlite
# Place at: ckb_data/ckb_data_v2/ckb_explorer.sqlite

# 4. (Optional) Install additional dependencies for API and async
pip install fastapi uvicorn aiohttp

# 5. (Optional) Install clustering dependencies
pip install scikit-learn hdbscan
```

## Usage

### 1. Command Line Interface (CLI)

Simple wallet analysis from terminal:

```bash
# Basic analysis (offline, cached data)
python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf

# With live CKB Explorer data
python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf --live

# JSON output (for scripting/integration)
python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf --json

# Custom database path
python inference_cli.py <address> --db /path/to/ckb_explorer.sqlite

# Verbose logging
python inference_cli.py <address> --verbose
```

#### CLI Output Example

```
================================================================================
CKB WALLET BEHAVIORAL ANALYSIS REPORT
================================================================================

WALLET INFORMATION
--------------------------------------------------------------------------------
Address: ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf
Analysis Timestamp: 2026-09-07T12:00:00+00:00

TRANSACTION HISTORY
--------------------------------------------------------------------------------
Total Transactions: 42
Total Inputs: 87
Total Outputs: 95
Observed Cells: 85
Spent Cells: 42

FEATURE ANALYSIS
--------------------------------------------------------------------------------
Supported Features: 8
Partial Features: 0
Insufficient Evidence: 2
Missing Features: 0

EXTRACTED FEATURES
--------------------------------------------------------------------------------

TEMPORAL:
  • gap_mean_seconds: 86400.5000 [SUPPORTED] (41 samples)
    → Mean time between consecutive transactions (seconds)
  • gap_std_seconds: 43200.0000 [SUPPORTED] (41 samples)
    → Standard deviation of inter-transaction gaps

TOPOLOGY:
  • avg_inputs_per_tx: 2.0714 [SUPPORTED] (42 samples)
    → Average number of inputs per transaction

CAPACITY:
  • avg_output_capacity_ckb: 0.5234 [SUPPORTED] (95 samples)
    → Average output capacity in CKB

SCRIPTS:
  • unique_lock_types: 1 [SUPPORTED] (95 samples)
    → Number of unique lock script types
  • unique_type_scripts: 2 [SUPPORTED] (95 samples)
    → Number of unique type script families

BEHAVIORAL CLASSIFICATION
--------------------------------------------------------------------------------
Structure: SCRIPT_TYPE_DIVERSE_STRUCTURE
Confidence: 65.0%

Description:
  Wallet exhibits diverse script type interactions, suggesting usage across
  multiple dApps or token protocols (xUDT, etc.). This pattern indicates more
  complex on-chain behavior.

QUALITY ASSESSMENT
--------------------------------------------------------------------------------
Quality Notes:
  ✓ Analysis based on 42 transactions with 8 supported features

Limitations:
  ⚠ No identity classification performed; analysis is behavioral description only
  ⚠ Single observation period; temporal generalization not supported
  ⚠ Cell/script patterns observed but not linked to owner identity
  ⚠ Results represent exploratory behavioral structures, not definitive taxonomy
```

### 2. REST API

FastAPI-based web service for integration:

```bash
# Start API server
uvicorn inference_api:app --host 0.0.0.0 --port 8000

# Open docs at http://localhost:8000/docs
```

#### API Endpoints

**POST /analyze** - Analyze wallet behavior

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_address": "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf",
    "use_live_data": false
  }'
```

**GET /health** - Check API health

```bash
curl "http://localhost:8000/health"
```

**GET /features-reference** - Get feature documentation

```bash
curl "http://localhost:8000/features-reference"
```

**GET /docs** - Interactive API documentation

Open browser to: http://localhost:8000/docs

### 3. Python Library

Use as Python module:

```python
import asyncio
from pathlib import Path
from inference_service import InferencePipeline

async def main():
    # Initialize pipeline
    db_path = Path("ckb_data/ckb_data_v2/ckb_explorer.sqlite")
    pipeline = InferencePipeline(db_path, use_live_data=False)
    
    # Analyze wallet
    profile = await pipeline.analyze_wallet(
        "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf"
    )
    
    # Access results
    print(f"Transactions: {profile.total_transactions}")
    print(f"Structure: {profile.behavioral_structure.value}")
    print(f"Confidence: {profile.behavioral_confidence:.1%}")
    
    # Iterate features
    for feat_name, feat in profile.features.items():
        if feat.value is not None:
            print(f"{feat_name}: {feat.value:.4f} [{feat.support_state.value}]")
    
    # Export to JSON
    import json
    with open("analysis.json", "w") as f:
        json.dump(profile.to_dict(), f, indent=2)

asyncio.run(main())
```

## Feature Categories

### Temporal Features
Describes timing patterns in transaction sequence:
- `gap_mean_seconds` - Average time between transactions
- `gap_std_seconds` - Timing variability
- `gap_min_seconds` - Fastest transaction succession
- `gap_max_seconds` - Longest gap between transactions

### Topology Features
Describes input/output structure:
- `avg_inputs_per_tx` - Average inputs per transaction
- `avg_outputs_per_tx` - Average outputs per transaction
- `max_inputs` - Maximum inputs in single transaction
- `consolidation_ratio` - Frequency of consolidating transactions

### Capacity Features
Describes value (capacity) characteristics:
- `avg_output_capacity_ckb` - Average output value
- `total_output_capacity_ckb` - Total value transferred
- `capacity_volatility` - Variation in output values

### Script Features
Describes script type usage:
- `unique_lock_types` - Number of different lock script types
- `unique_type_scripts` - Number of different type script families

## Behavioral Structures

Exploratory patterns discovered in frozen dataset analysis:

### 1. LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE
Wallets with lower cell consumption patterns. Suggests simpler transaction structure or careful cell management strategies.

### 2. SCRIPT_TYPE_DIVERSE_STRUCTURE
Wallets using diverse type-script families. Suggests usage across multiple dApps or token protocols.

### 3. UNINTERPRETED
Observable separation but lacks clear distinguishing characteristic. Requires further analysis.

**Note:** All structures have LOW activity dependence (not just proxies for transaction volume).

## Model Training

Train clustering models on frozen dataset:

```bash
python model_trainer.py
```

This generates:
- `models/trained_models/scaler.pkl` - Feature scaling
- `models/trained_models/pca_model.pkl` - PCA dimensionality reduction
- `models/trained_models/hdbscan_model.pkl` - HDBSCAN clustering
- `models/trained_models/gmm_model.pkl` - Gaussian Mixture Model
- `models/trained_models/training_summary.json` - Training metrics

## Data Quality & Limitations

### Data Quality ✅

- **1,172 wallets** with complete provenance tracking
- **100% input resolution** - all 56,407 applicable inputs resolved
- **51,816 transactions** fully normalized and validated
- **80 passing tests** verify artifact integrity

### Limitations ⚠️

- **Single time period** - August 2026 only; no temporal generalization
- **Non-random sample** - sourced from historical discovery, not global CKB population
- **Sparse features** - 99 of 121 features sparse; complete cases only 43.8%
- **No ground truth** - legacy labels abandoned; no verified identities
- **Representation-dependent** - clustering requires careful dimensionality reduction
- **CKB `since` semantics** - cannot distinguish protocol-enforced from discretionary behavior

## Architecture

```
InferencePipeline (main orchestrator)
├── CKBDataCollector (transaction fetching)
│   ├── Live data (CKB Explorer API)
│   └── Cached data (frozen database)
├── FeatureExtractor (feature computation)
│   ├── temporal_features()
│   ├── topology_features()
│   ├── capacity_features()
│   └── script_features()
└── BehavioralClassifier (structure assignment)
    ├── PCA-based scoring
    └── Heuristic classification

Interfaces:
├── CLI (inference_cli.py)
├── REST API (inference_api.py)
└── Python Library (inference_service.py)
```

## Important Disclaimers

⚠️ **This analysis describes OBSERVABLE ON-CHAIN BEHAVIORAL PATTERNS ONLY**

- NOT a human/bot identity classifier
- Makes NO identity claims or ownership attribution
- Cannot link addresses to individuals
- Results represent exploratory structures, not verified taxonomy
- Single 30-day observation period limits temporal generality
- Cell/script patterns observed but not linked to owner behavior intent

## Integration Examples

### Example 1: Batch Analysis Script

```python
import asyncio
import json
from pathlib import Path
from inference_service import InferencePipeline

async def analyze_batch(addresses: list[str]) -> dict:
    """Analyze multiple wallets."""
    db_path = Path("ckb_data/ckb_data_v2/ckb_explorer.sqlite")
    pipeline = InferencePipeline(db_path)
    
    results = {}
    for addr in addresses:
        profile = await pipeline.analyze_wallet(addr)
        results[addr] = {
            "structure": profile.behavioral_structure.value,
            "confidence": profile.behavioral_confidence,
            "tx_count": profile.total_transactions,
            "features_supported": profile.supported_features
        }
    
    return results

# Run
addresses = [
    "ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf",
    # Add more addresses...
]

results = asyncio.run(analyze_batch(addresses))
print(json.dumps(results, indent=2))
```

### Example 2: Web Service Integration

```python
import requests

API_URL = "http://localhost:8000"

def analyze_wallet(address: str) -> dict:
    """Call API to analyze wallet."""
    response = requests.post(
        f"{API_URL}/analyze",
        json={"wallet_address": address, "use_live_data": False}
    )
    return response.json()

# Use
result = analyze_wallet("ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf")
print(f"Structure: {result['behavioral_assessment']['structure']}")
print(f"Confidence: {result['behavioral_assessment']['confidence']:.1%}")
```

### Example 3: dApp Analysis

```python
# Find wallets with high dApp interaction
async def find_active_dapps() -> list[str]:
    pipeline = InferencePipeline(Path("ckb_data/ckb_data_v2/ckb_explorer.sqlite"))
    
    active_dapp_wallets = []
    for address in your_address_list:
        profile = await pipeline.analyze_wallet(address)
        
        # Check script diversity
        unique_types = profile.features.get("unique_type_scripts")
        if unique_types and unique_types.value and unique_types.value > 2:
            active_dapp_wallets.append(address)
    
    return active_dapp_wallets
```

## Testing

Run integration tests:

```bash
# Unit tests
pytest tests/ -v

# Integration tests (requires database)
pytest tests/test_inference_integration.py -v

# Performance tests
pytest tests/test_inference_performance.py -v
```

## Performance

- **Feature extraction:** ~100-500ms per wallet (depends on transaction count)
- **Inference:** ~50ms per wallet
- **Total latency:** ~150-600ms per wallet
- **API throughput:** ~5-10 requests/second (single worker)

For high-throughput: Deploy multiple API workers with load balancing.

## Troubleshooting

**Error: Database not found**
```
Solution: Download frozen dataset from releases and place at:
ckb_data/ckb_data_v2/ckb_explorer.sqlite
```

**Error: aiohttp not found**
```bash
pip install aiohttp
```

**Live data requests fail**
```
Ensure CKB Explorer API is accessible:
curl https://mainnet-api.explorer.nervos.org/api/v1/addresses/ckt1.../transactions
```

**Memory issues with large batches**
```
Process in smaller batches and use --db connection pooling
```

## References

- [Final Research Report](reports/final-research-report.md) - Complete methodology
- [Feature Engineering V2](docs/feature-engineering-v2.md) - Feature definitions
- [Exploratory ML](docs/exploratory-ml.md) - Clustering analysis
- [Limitations](docs/limitations.md) - Explicit constraints
- [Frozen Dataset](docs/dataset.md) - Data specification

## License

See [LICENSE](LICENSE)

## Citation

If you use this inference pipeline in research:

```bibtex
@misc{ckbintel2026,
  title={CKB Wallet Behaviour Intelligence},
  author={Mulinya, Fadhil},
  year={2026},
  url={https://github.com/FadhilMulinya/ckb-intel}
}
```

---

**Last Updated:** September 7, 2026  
**Status:** Production Ready  
**Version:** 1.0.0
=======
# CKB Wallet Behaviour Intelligence Service

This directory is the service layer for the current CKB-native V2 behaviour
pipeline. It exposes observable features, support/evidence states, and
descriptive behaviour rules. It does not classify human/bot identity, infer
ownership, or assign a definitive wallet type.

## Runtime flow

```text
CKB address → frozen observation OR live Explorer collection
           → common V2 observation → Feature V2 → V2 behaviour rules
           → structured wallet behaviour profile
```

`classifier-service/` is the authoritative Python implementation of CKB Wallet
Behaviour Intelligence. `v2_service.py` imports the authoritative
`wallet_intelligence.features_v2.pipeline.load_observation_v2`
and `assess_observation_v2`; feature formulas remain in the authoritative V2
modules and are not duplicated here.

## Modes

Frozen/offline mode is operational for addresses represented in
`ckb_data/ckb_data_v2/ckb_explorer.sqlite`. It performs no network requests.

Live mode collects a deterministic UTC rolling 30-day window from the CKB
Explorer mainnet API, resolves available previous outputs, and feeds the same
V2 observation/feature/rule pipeline. Incomplete Explorer evidence is exposed
through support states and limitations; the frozen SQLite is never modified.

## API and CLI

Run the API from the repository root:

```bash
cd classifier-service && uvicorn app:app --host 0.0.0.0 --port 8000
```

The `POST /analyze` request is:

```json
{"address": "ckb1...", "mode": "frozen"}
```

Use `"mode": "live"` for an arbitrary valid mainnet address.

The response is versioned as `wallet-behaviour-v2` and contains observation
metadata, evidence counts, one support state per V2 family, all V2 feature
results, rule results, and limitations. Invalid addresses return
`INVALID_ADDRESS`; valid addresses absent from the frozen database return
`NOT_IN_FROZEN_DATASET`; failed collection states return `COLLECTION_FAILED`.

```bash
python classifier-service/inference_cli.py ckb1... --json
```

## Scientific boundaries

HDBSCAN, PCA, GMM, and reference-cohort comparisons remain research artifacts
under `ckb_data/`. They are not converted into wallet identities or definitive
classifications by this service. Behaviour names such as
`CELL_CONSOLIDATION`, `FAN_IN_COLLECTION`, and `PERIODIC_EXECUTION` are
descriptive patterns whose support depends on the evidence available for the
observation.

The superseded V1 proxy-label implementation was removed from the repository;
Git history is the archive and is not imported by the active runtime.
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6
