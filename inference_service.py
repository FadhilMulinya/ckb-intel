#!/usr/bin/env python3
"""
CKB Wallet Behavioral Analyzer - Inference Pipeline

This module provides the complete inference pipeline for analyzing CKB wallet behavior.
Input: CKB wallet address (or lock hash)
Output: Behavioral analysis with feature descriptions and structural grouping

No identity classification is performed; analysis is descriptive only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SupportState(str, Enum):
    """Feature evidence support classification."""
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class BehavioralStructure(str, Enum):
    """Discovered behavioral structures from exploratory analysis."""
    LOW_TARGET_CONSUMED_CAPACITY = "LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE"
    SCRIPT_TYPE_DIVERSE = "SCRIPT_TYPE_DIVERSE_STRUCTURE"
    UNINTERPRETED = "UNINTERPRETED"
    UNKNOWN = "UNKNOWN"


@dataclass
class FeatureResult:
    """Individual feature extraction result."""
    name: str
    family: str
    value: Optional[float | str | dict] = None
    support_state: SupportState = SupportState.UNRESOLVED
    evidence_count: int = 0
    description: str = ""
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "family": self.family,
            "value": self.value,
            "support_state": self.support_state.value,
            "evidence_count": self.evidence_count,
            "description": self.description
        }


@dataclass
class BehavioralProfile:
    """Complete behavioral analysis profile for a wallet."""
    wallet_address: str
    lock_hash: Optional[str] = None
    analysis_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observation_period_start: Optional[str] = None
    observation_period_end: Optional[str] = None
    
    # Observation counts
    total_transactions: int = 0
    total_inputs: int = 0
    total_outputs: int = 0
    observed_cells: int = 0
    spent_cells: int = 0
    
    # Feature results
    features: dict[str, FeatureResult] = field(default_factory=dict)
    
    # Behavioral assessment
    behavioral_structure: BehavioralStructure = BehavioralStructure.UNKNOWN
    behavioral_confidence: float = 0.0  # 0-1 scale
    structure_description: str = ""
    
    # Support summary
    supported_features: int = 0
    partial_features: int = 0
    insufficient_features: int = 0
    missing_features: int = 0
    
    # Metadata
    data_quality_notes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "wallet_address": self.wallet_address,
            "lock_hash": self.lock_hash,
            "analysis_timestamp": self.analysis_timestamp,
            "observation_period": {
                "start": self.observation_period_start,
                "end": self.observation_period_end
            },
            "observation_counts": {
                "total_transactions": self.total_transactions,
                "total_inputs": self.total_inputs,
                "total_outputs": self.total_outputs,
                "observed_cells": self.observed_cells,
                "spent_cells": self.spent_cells
            },
            "features": {name: feat.to_dict() for name, feat in self.features.items()},
            "behavioral_assessment": {
                "structure": self.behavioral_structure.value,
                "confidence": self.behavioral_confidence,
                "description": self.structure_description
            },
            "support_summary": {
                "supported": self.supported_features,
                "partial": self.partial_features,
                "insufficient": self.insufficient_features,
                "missing": self.missing_features
            },
            "quality_assessment": {
                "notes": self.data_quality_notes,
                "limitations": self.limitations
            }
        }


class CKBDataCollector:
    """Collects real-time transaction data from CKB blockchain."""
    
    def __init__(self, db_path: Path, api_endpoint: str = "https://mainnet-api.explorer.nervos.org"):
        """
        Initialize data collector.
        
        Args:
            db_path: Path to frozen dataset database
            api_endpoint: CKB Explorer API endpoint
        """
        self.db_path = db_path
        self.api_endpoint = api_endpoint
        self.conn = None
    
    def connect(self) -> None:
        """Connect to CKB database."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def disconnect(self) -> None:
        """Disconnect from database."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    async def fetch_wallet_transactions(self, address: str, limit: int = 300) -> list[dict]:
        """
        Fetch wallet transactions live from the CKB Explorer API and normalize
        them into the same shape produced by fetch_wallet_transactions_cached():
        a list of tx dicts with 'tx_hash', 'block_timestamp' (seconds), and
        enriched 'inputs'/'outputs' lists.

        Uses GET /api/v1/address_transactions/{address}, which returns
        display_inputs/display_outputs inline per transaction (JSON:API
        format) -- no separate per-transaction detail calls needed.

        Note: display_inputs/display_outputs do not carry lock-script data
        (this is a limitation of the CKB Explorer API itself, not of this
        collector), so unique_lock_types will be unavailable in live mode
        for the same reason it's unavailable against the cached dataset.

        Args:
            address: CKB wallet address
            limit: Maximum transactions to fetch across all pages

        Returns:
            List of normalized transaction dicts (empty list on failure or
            if the address has no transactions).
        """
        import aiohttp

        page_size = 50
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        normalized: list[dict] = []

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                page = 1
                total = None

                while len(normalized) < limit:
                    url = f"{self.api_endpoint}/api/v1/address_transactions/{address}"
                    params = {
                        "page": page,
                        "page_size": page_size,
                        "sort": "time.desc",
                    }

                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            logger.error(
                                f"CKB Explorer API error {resp.status} for {address} "
                                f"(page {page})"
                            )
                            break

                        payload = await resp.json()

                    rows = payload.get("data") or []
                    if not rows:
                        break

                    if total is None:
                        total = payload.get("meta", {}).get("total", len(rows))

                    for row in rows:
                        tx = self._normalize_live_transaction(row)
                        if tx:
                            normalized.append(tx)

                    if page * page_size >= (total or 0):
                        break
                    page += 1

        except Exception as e:
            logger.error(f"Error fetching live transactions for {address}: {e}")
            return normalized

        return normalized[:limit]

    @staticmethod
    def _normalize_live_transaction(row: dict) -> Optional[dict]:
        """
        Convert one JSON:API address_transactions row into the internal
        tx dict shape (matching fetch_wallet_transactions_cached output).
        """
        attrs = row.get("attributes", {})
        tx_hash = attrs.get("transaction_hash")
        if not tx_hash:
            return None

        raw_ts = attrs.get("block_timestamp")
        try:
            # CKB Explorer returns block_timestamp in milliseconds
            block_timestamp = int(raw_ts) // 1000 if raw_ts is not None else None
        except (TypeError, ValueError):
            block_timestamp = None

        inputs = []
        for inp in attrs.get("display_inputs") or []:
            try:
                capacity = float(inp["capacity"]) if inp.get("capacity") else None
            except (TypeError, ValueError):
                capacity = None
            inputs.append({
                "previous_tx_hash": inp.get("generated_tx_hash"),
                "previous_output_index": inp.get("cell_index"),
                "resolved_capacity_shannon": capacity,
                "resolved_lock_script_hash": None,  # not exposed by this endpoint
                "resolved_type_script_hash": None,  # not exposed by this endpoint
                "from_cellbase": inp.get("from_cellbase", False),
            })

        outputs = []
        for out in attrs.get("display_outputs") or []:
            try:
                capacity = float(out["capacity"]) if out.get("capacity") else None
            except (TypeError, ValueError):
                capacity = None
            outputs.append({
                "capacity_shannon": capacity,
                "status": out.get("status"),
                "consumed_tx_hash": out.get("consumed_tx_hash"),
                "cell_type": out.get("cell_type"),
                "address_hash": out.get("address_hash"),
                "lock_script_hash": None,  # not exposed by this endpoint
                "type_script_hash": None,  # not exposed by this endpoint
            })

        return {
            "tx_hash": tx_hash,
            "block_timestamp": block_timestamp,
            "inputs": inputs,
            "outputs": outputs,
        }
    
    def query_database(self, query: str, params: tuple = ()) -> list[dict]:
        """Query the frozen dataset database."""
        if not self.conn:
            raise RuntimeError("Not connected to database")
        
        cursor = self.conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_observation_window(self, address: str) -> Optional[dict]:
        """
        Fetch the wallet_observations window metadata for an address.

        Args:
            address: CKB wallet address

        Returns:
            Dict with observation_id, window_start_timestamp, window_end_timestamp
            (as ISO-8601 strings) plus raw epoch seconds, or None if not found.
        """
        if not self.conn:
            raise RuntimeError("Not connected to database")

        query = """
        SELECT observation_id, window_start_timestamp, window_end_timestamp
        FROM wallet_observations
        WHERE address = ?
        LIMIT 1
        """
        rows = self.query_database(query, (address,))
        if not rows:
            return None

        row = rows[0]
        start_ts = row.get("window_start_timestamp")
        end_ts = row.get("window_end_timestamp")

        return {
            "observation_id": row.get("observation_id"),
            "window_start_timestamp": start_ts,
            "window_end_timestamp": end_ts,
            "window_start_iso": (
                datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
                if start_ts is not None else None
            ),
            "window_end_iso": (
                datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
                if end_ts is not None else None
            ),
        }

    def fetch_wallet_transactions_cached(self, address: str) -> list[dict]:
        """
        Fetch cached transactions for a wallet from the frozen dataset.
        
        Args:
            address: CKB wallet address
        
        Returns:
            List of enriched transaction records with inputs, outputs, and scripts
        """
        if not self.conn:
            raise RuntimeError("Not connected to database")
        
        try:
            # Step 1: Get observation_id for the address
            obs_query = "SELECT observation_id FROM wallet_observations WHERE address = ? LIMIT 1"
            cursor = self.conn.execute(obs_query, (address,))
            obs_result = cursor.fetchone()
            
            if not obs_result:
                logger.warning(f"No observations found for address: {address}")
                return []
            
            observation_id = obs_result[0]
            logger.info(f"Found observation_id: {observation_id}")
            
            # Step 2: Query transactions that involve this observation/wallet
            query = """
            SELECT DISTINCT t.* 
            FROM transactions t
            JOIN wallet_transaction_participation wtp ON t.tx_hash = wtp.tx_hash
            WHERE wtp.observation_id = ?
            ORDER BY t.block_timestamp DESC
            LIMIT 500
            """
            
            tx_results = self.query_database(query, (observation_id,))
            logger.info(f"Found {len(tx_results)} cached transactions for {address}")
            
            # Step 3: Enrich transactions with inputs, outputs, and scripts
            enriched_txs = []
            for tx in tx_results:
                tx_hash = tx['tx_hash']
                
                # Get inputs for this transaction
                inputs_query = """
                SELECT * FROM transaction_inputs 
                WHERE tx_hash = ?
                ORDER BY input_index
                """
                tx['inputs'] = self.query_database(inputs_query, (tx_hash,))
                
                # Get outputs (cells) created by this transaction
                outputs_query = """
                SELECT * FROM cells 
                WHERE creating_tx_hash = ?
                ORDER BY output_index
                """
                tx['outputs'] = self.query_database(outputs_query, (tx_hash,))
                
                # Enrich inputs with lock/type script details
                for inp in tx['inputs']:
                    if inp.get('resolved_lock_script_hash'):
                        lock_script_query = "SELECT * FROM lock_scripts WHERE script_hash = ?"
                        lock_scripts = self.query_database(lock_script_query, (inp['resolved_lock_script_hash'],))
                        inp['lock_script'] = lock_scripts[0] if lock_scripts else None
                    
                    if inp.get('resolved_type_script_hash'):
                        type_script_query = "SELECT * FROM type_scripts WHERE script_hash = ?"
                        type_scripts = self.query_database(type_script_query, (inp['resolved_type_script_hash'],))
                        inp['type_script'] = type_scripts[0] if type_scripts else None
                
                # Enrich outputs with lock/type script details
                for out in tx['outputs']:
                    if out.get('lock_script_hash'):
                        lock_script_query = "SELECT * FROM lock_scripts WHERE script_hash = ?"
                        lock_scripts = self.query_database(lock_script_query, (out['lock_script_hash'],))
                        out['lock_script'] = lock_scripts[0] if lock_scripts else None
                    
                    if out.get('type_script_hash'):
                        type_script_query = "SELECT * FROM type_scripts WHERE script_hash = ?"
                        type_scripts = self.query_database(type_script_query, (out['type_script_hash'],))
                        out['type_script'] = type_scripts[0] if type_scripts else None
                
                enriched_txs.append(tx)
            
            logger.info(f"Enriched {len(enriched_txs)} transactions with inputs/outputs/scripts")
            return enriched_txs
            
        except Exception as e:
            logger.error(f"Error querying cached transactions: {e}")
            return []


class FeatureExtractor:
    """Extracts CKB-native behavioral features from transaction data."""
    
    # Minimum samples required per feature family
    MINIMUM_SAMPLES = {
        "temporal": 2,
        "periodicity": 10,
        "topology": 2,
        "lifecycle": 2,
        "templates": 5,
        "scripts": 1,
        "typed_assets": 1,
        "capacity": 2,
        "lineage": 2
    }
    
    def __init__(self):
        """Initialize feature extractor."""
        pass
    
    def extract_temporal_features(self, transactions: list[dict]) -> dict[str, FeatureResult]:
        """Extract temporal structure features."""
        results = {}
        
        if len(transactions) < self.MINIMUM_SAMPLES["temporal"]:
            results["insufficient_data"] = FeatureResult(
                name="temporal_insufficient",
                family="temporal",
                support_state=SupportState.INSUFFICIENT_EVIDENCE,
                description="Fewer than 2 transactions; temporal analysis not supported"
            )
            return results
        
        timestamps = sorted([tx.get("block_timestamp") or tx.get("timestamp") for tx in transactions if tx.get("block_timestamp") or tx.get("timestamp")])
        
        if len(timestamps) < 2:
            results["no_timestamps"] = FeatureResult(
                name="no_timestamps",
                family="temporal",
                support_state=SupportState.INSUFFICIENT_EVIDENCE,
                description="Missing timestamp data"
            )
            return results
        
        # Inter-transaction gaps
        gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        
        results["gap_mean_seconds"] = FeatureResult(
            name="gap_mean_seconds",
            family="temporal",
            value=float(np.mean(gaps)) if gaps else None,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(gaps),
            description="Mean time between consecutive transactions (seconds)"
        )
        
        results["gap_std_seconds"] = FeatureResult(
            name="gap_std_seconds",
            family="temporal",
            value=float(np.std(gaps)) if len(gaps) > 1 else 0.0,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(gaps),
            description="Standard deviation of inter-transaction gaps"
        )
        
        results["gap_min_seconds"] = FeatureResult(
            name="gap_min_seconds",
            family="temporal",
            value=float(min(gaps)) if gaps else None,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(gaps),
            description="Minimum time between consecutive transactions"
        )
        
        results["gap_max_seconds"] = FeatureResult(
            name="gap_max_seconds",
            family="temporal",
            value=float(max(gaps)) if gaps else None,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(gaps),
            description="Maximum time between consecutive transactions"
        )
        
        return results
    
    def extract_topology_features(self, transactions: list[dict]) -> dict[str, FeatureResult]:
        """Extract transaction topology features (input/output structure)."""
        results = {}
        
        if len(transactions) < self.MINIMUM_SAMPLES["topology"]:
            results["insufficient_data"] = FeatureResult(
                name="topology_insufficient",
                family="topology",
                support_state=SupportState.INSUFFICIENT_EVIDENCE,
                description="Fewer than 2 transactions; topology analysis not supported"
            )
            return results
        
        input_counts = [len(tx.get("inputs", [])) for tx in transactions]
        output_counts = [len(tx.get("outputs", [])) for tx in transactions]
        
        results["avg_inputs_per_tx"] = FeatureResult(
            name="avg_inputs_per_tx",
            family="topology",
            value=float(np.mean(input_counts)),
            support_state=SupportState.SUPPORTED,
            evidence_count=len(transactions),
            description="Average number of inputs per transaction"
        )
        
        results["avg_outputs_per_tx"] = FeatureResult(
            name="avg_outputs_per_tx",
            family="topology",
            value=float(np.mean(output_counts)),
            support_state=SupportState.SUPPORTED,
            evidence_count=len(transactions),
            description="Average number of outputs per transaction"
        )
        
        results["max_inputs"] = FeatureResult(
            name="max_inputs",
            family="topology",
            value=float(max(input_counts)) if input_counts else 0,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(transactions),
            description="Maximum inputs in a single transaction"
        )
        
        results["consolidation_ratio"] = FeatureResult(
            name="consolidation_ratio",
            family="topology",
            value=float(sum(1 for ic in input_counts if ic > 1)) / len(input_counts) if input_counts else 0.0,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(transactions),
            description="Ratio of consolidating transactions (multiple inputs)"
        )
        
        return results
    
    def extract_capacity_features(self, transactions: list[dict]) -> dict[str, FeatureResult]:
        """Extract capacity (value) features."""
        results = {}
        
        if len(transactions) < self.MINIMUM_SAMPLES["capacity"]:
            results["insufficient_data"] = FeatureResult(
                name="capacity_insufficient",
                family="capacity",
                support_state=SupportState.INSUFFICIENT_EVIDENCE,
                description="Fewer than 2 transactions; capacity analysis not supported"
            )
            return results
        
        # Extract capacity from outputs (in shannon, 1 CKB = 1e8 shannon)
        # Cached DB rows use 'capacity_shannon' (see cells table schema);
        # live CKB Explorer API responses use 'capacity'. Support both.
        output_capacities = []
        for tx in transactions:
            for output in tx.get("outputs", []):
                raw_capacity = output.get("capacity_shannon")
                if raw_capacity is None:
                    raw_capacity = output.get("capacity")
                if raw_capacity:
                    output_capacities.append(float(raw_capacity))
        
        if not output_capacities:
            results["no_capacity_data"] = FeatureResult(
                name="no_capacity_data",
                family="capacity",
                support_state=SupportState.INSUFFICIENT_EVIDENCE,
                description="No capacity data in outputs"
            )
            return results
        
        # Convert shannon to CKB for readability
        capacities_ckb = [c / 1e8 for c in output_capacities]
        
        results["avg_output_capacity_ckb"] = FeatureResult(
            name="avg_output_capacity_ckb",
            family="capacity",
            value=float(np.mean(capacities_ckb)),
            support_state=SupportState.SUPPORTED,
            evidence_count=len(output_capacities),
            description="Average output capacity in CKB"
        )
        
        results["total_output_capacity_ckb"] = FeatureResult(
            name="total_output_capacity_ckb",
            family="capacity",
            value=float(np.sum(capacities_ckb)),
            support_state=SupportState.SUPPORTED,
            evidence_count=len(output_capacities),
            description="Total output capacity in CKB across all transactions"
        )
        
        results["capacity_volatility"] = FeatureResult(
            name="capacity_volatility",
            family="capacity",
            value=float(np.std(capacities_ckb)) if len(capacities_ckb) > 1 else 0.0,
            support_state=SupportState.SUPPORTED,
            evidence_count=len(output_capacities),
            description="Standard deviation of output capacities (capacity spread)"
        )
        
        return results
    
    def extract_script_features(self, transactions: list[dict]) -> dict[str, FeatureResult]:
        """Extract script type and diversity features."""
        results = {}
        
        if len(transactions) < self.MINIMUM_SAMPLES["scripts"]:
            results["insufficient_data"] = FeatureResult(
                name="scripts_insufficient",
                family="scripts",
                support_state=SupportState.INSUFFICIENT_EVIDENCE,
                description="Insufficient transaction data for script analysis"
            )
            return results
        
        lock_types = set()
        type_types = set()
        output_count = 0
        
        for tx in transactions:
            for output in tx.get("outputs", []):
                output_count += 1
                
                # Check enriched lock_script data
                if output.get("lock_script"):
                    lock_script = output["lock_script"]
                    if lock_script.get("code_hash"):
                        lock_types.add(lock_script["code_hash"][:16])
                elif output.get("lock", {}).get("code_hash"):
                    # Fallback for alternative data structure
                    lock_types.add(output["lock"]["code_hash"][:16])
                
                # Check enriched type_script data
                if output.get("type_script"):
                    type_script = output["type_script"]
                    if type_script.get("code_hash"):
                        type_types.add(type_script["code_hash"][:16])
                elif output.get("type", {}).get("code_hash"):
                    # Fallback for alternative data structure
                    type_types.add(output["type"]["code_hash"][:16])

                # Also check inputs for lock scripts
                for tx in transactions:
                    for inp in tx.get("inputs", []):
                        if inp.get("lock_script"):
                            lock_script = inp["lock_script"]
                            if lock_script.get("code_hash"):
                                lock_types.add(lock_script["code_hash"][:16])
        
        results["unique_lock_types"] = FeatureResult(
            name="unique_lock_types",
            family="scripts",
            value=len(lock_types),
            support_state=SupportState.SUPPORTED,
            evidence_count=output_count,
            description="Number of unique lock script types"
        )
        
        results["unique_type_scripts"] = FeatureResult(
            name="unique_type_scripts",
            family="scripts",
            value=len(type_types),
            support_state=SupportState.SUPPORTED,
            evidence_count=output_count,
            description="Number of unique type script families"
        )
        
        return results
    
    def extract_all_features(self, transactions: list[dict]) -> dict[str, FeatureResult]:
        """Extract all available features from transaction data."""
        results = {}
        
        results.update(self.extract_temporal_features(transactions))
        results.update(self.extract_topology_features(transactions))
        results.update(self.extract_capacity_features(transactions))
        results.update(self.extract_script_features(transactions))
        
        return results


class BehavioralClassifier:
    """Classifies wallets into behavioral structures using trained model."""
    
    # PCA component loadings from Phase 1 analysis
    PC1_LOADINGS = {
        "capacity__target_consumed_capacity": -0.5966,
        "lineage__lineage_depth": -0.5466,
        "lineage__continuation_count": -0.4110,
        "scripts__type_family_count": -0.0063
    }
    
    PC2_LOADINGS = {
        "lineage__lineage_depth": -0.4000,
        "lineage__continuation_count": -0.3962,
        "capacity__target_consumed_capacity": 0.6814,
        "capacity__capacity_repeat_ratio": 0.2406
    }
    
    PC4_LOADINGS = {
        "scripts__type_family_count": 0.7351,
        "lineage__lineage_repetition": 0.3282,
        "lineage__merge_count": 0.3083
    }
    
    def __init__(self):
        """Initialize classifier."""
        pass
    
    def classify_structure(self, features: dict[str, FeatureResult]) -> tuple[BehavioralStructure, float]:
        """
        Classify wallet into behavioral structure.
        
        Args:
            features: Extracted features
        
        Returns:
            Tuple of (structure, confidence)
        """
        # Calculate PCA-like score for script diversity
        type_scripts = next((f.value for f in features.values() if f.name == "unique_type_scripts"), 0)
        unique_locks = next((f.value for f in features.values() if f.name == "unique_lock_types"), 0)
        
        # Calculate proxy for consumed capacity (use avg_output_capacity as proxy)
        avg_capacity = next((f.value for f in features.values() if f.name == "avg_output_capacity_ckb"), 0)
        
        # Heuristic classification based on observable patterns
        confidence = 0.0
        structure = BehavioralStructure.UNKNOWN
        
        # HIGH script diversity suggests dApp interaction
        if type_scripts and type_scripts > 1:
            structure = BehavioralStructure.SCRIPT_TYPE_DIVERSE
            confidence = min(0.7, (type_scripts / 5.0))  # Normalize by typical max
        # LOW capacity suggests simpler wallet usage
        elif avg_capacity and avg_capacity < 0.1:  # Less than 0.1 CKB average
            structure = BehavioralStructure.LOW_TARGET_CONSUMED_CAPACITY
            confidence = 0.5
        else:
            structure = BehavioralStructure.UNINTERPRETED
            confidence = 0.3
        
        return structure, confidence


class InferencePipeline:
    """Complete inference pipeline for wallet behavioral analysis."""
    
    def __init__(self, db_path: Path, use_live_data: bool = True):
        """
        Initialize inference pipeline.
        
        Args:
            db_path: Path to frozen dataset database
            use_live_data: Whether to fetch live data from CKB Explorer
        """
        self.db_path = db_path
        self.use_live_data = use_live_data
        self.collector = CKBDataCollector(db_path)
        self.extractor = FeatureExtractor()
        self.classifier = BehavioralClassifier()
    
    async def analyze_wallet(
        self,
        wallet_address: str,
        use_live_data: Optional[bool] = None,
    ) -> BehavioralProfile:
        """
        Analyze a CKB wallet address and return behavioral profile.
        
        Args:
            wallet_address: CKB wallet address or lock hash
            use_live_data: Per-request override for data source. If None,
                falls back to the instance default (self.use_live_data).
                Passing this explicitly lets a single long-lived pipeline
                (e.g. the FastAPI global instance) serve both cached and
                live requests based on what each caller asks for.
        
        Returns:
            BehavioralProfile with complete analysis
        """
        effective_use_live = self.use_live_data if use_live_data is None else use_live_data
        logger.info(f"Analyzing wallet: {wallet_address} (live={effective_use_live})")
        
        profile = BehavioralProfile(wallet_address=wallet_address)
        
        try:
            # Only the cached path needs the SQLite file to exist; live mode
            # talks to the CKB Explorer API directly and shouldn't fail if
            # the frozen dataset isn't present.
            if not effective_use_live:
                self.collector.connect()

            # Fetch transaction data
            if effective_use_live:
                logger.info("Fetching live data from CKB Explorer...")
                transactions = await self.collector.fetch_wallet_transactions(wallet_address)
            else:
                logger.info("Using cached data from database...")
                transactions = self.collector.fetch_wallet_transactions_cached(wallet_address)
            
            if not transactions:
                logger.warning("No transactions found for wallet")
                profile.data_quality_notes.append("No transaction data available")
                profile.limitations.append("Cannot perform behavioral analysis without transaction history")
                return profile
            
            # Update observation counts
            profile.total_transactions = len(transactions)
            profile.total_inputs = sum(len(tx.get("inputs", [])) for tx in transactions)
            profile.total_outputs = sum(len(tx.get("outputs", [])) for tx in transactions)

            logger.info(f"Found {profile.total_transactions} transactions")

            # Observation window.
            # Cached mode: wallet_observations tracks a fixed 30-day window.
            # Live mode: no fixed window exists -- derive start/end from the
            # actual fetched transaction timestamps, and note that this
            # reflects however much history the API returned, not a fixed
            # collection period.
            if not effective_use_live:
                window = self.collector.get_observation_window(wallet_address)
                if window:
                    profile.observation_period_start = window["window_start_iso"]
                    profile.observation_period_end = window["window_end_iso"]
                else:
                    logger.warning(
                        f"No wallet_observations window found for {wallet_address}"
                    )
            else:
                live_timestamps = [
                    tx["block_timestamp"] for tx in transactions
                    if tx.get("block_timestamp") is not None
                ]
                if live_timestamps:
                    profile.observation_period_start = datetime.fromtimestamp(
                        min(live_timestamps), tz=timezone.utc
                    ).isoformat()
                    profile.observation_period_end = datetime.fromtimestamp(
                        max(live_timestamps), tz=timezone.utc
                    ).isoformat()
                profile.data_quality_notes.append(
                    "Live mode: observation period reflects the span of transactions "
                    "returned by the CKB Explorer API (up to the fetch limit), not a "
                    "fixed 30-day collection window"
                )
                profile.limitations.append(
                    "Live mode does not expose per-cell lock script data (a limitation "
                    "of the CKB Explorer address_transactions endpoint itself); "
                    "unique_lock_types will be unavailable the same way it is in "
                    "cached mode"
                )

            # Observed/spent cell counts, derived from the enriched output cells.
            # Cached DB rows carry the original CKB Explorer raw_json, which
            # includes a 'status' field ('live' = unspent, 'dead' = spent).
            observed_cells = 0
            spent_cells = 0
            for tx in transactions:
                for output in tx.get("outputs", []):
                    observed_cells += 1
                    status = output.get("status")
                    if status is None and output.get("raw_json"):
                        try:
                            status = json.loads(output["raw_json"]).get("status")
                        except (json.JSONDecodeError, TypeError):
                            status = None
                    if status == "dead":
                        spent_cells += 1

            profile.observed_cells = observed_cells
            profile.spent_cells = spent_cells
            
            # Extract features
            logger.info("Extracting features...")
            features = self.extractor.extract_all_features(transactions)
            profile.features = features
            
            # Summarize support
            support_counts = {}
            for feat in features.values():
                state = feat.support_state.value
                support_counts[state] = support_counts.get(state, 0) + 1
            
            profile.supported_features = support_counts.get("SUPPORTED", 0)
            profile.partial_features = support_counts.get("PARTIAL", 0)
            profile.insufficient_features = support_counts.get("INSUFFICIENT_EVIDENCE", 0)
            profile.missing_features = support_counts.get("UNRESOLVED", 0)
            
            # Classify behavioral structure
            logger.info("Classifying behavioral structure...")
            structure, confidence = self.classifier.classify_structure(features)
            profile.behavioral_structure = structure
            profile.behavioral_confidence = confidence
            
            # Add structure description
            if structure == BehavioralStructure.SCRIPT_TYPE_DIVERSE:
                profile.structure_description = (
                    "Wallet exhibits diverse script type interactions, suggesting usage across multiple "
                    "dApps or token protocols (xUDT, etc.). This pattern indicates more complex on-chain behavior."
                )
            elif structure == BehavioralStructure.LOW_TARGET_CONSUMED_CAPACITY:
                profile.structure_description = (
                    "Wallet exhibits lower capacity consumption patterns, suggesting simpler transaction "
                    "structure or careful cell management strategies."
                )
            else:
                profile.structure_description = (
                    "Wallet exhibits mixed or uninterpreted behavioral patterns. Further analysis or "
                    "extended observation period may reveal clearer structures."
                )
            
            # Add quality notes
            if profile.total_transactions < 10:
                profile.data_quality_notes.append(
                    f"Limited transaction history ({profile.total_transactions} tx). Patterns may not be stable."
                )
                profile.limitations.append("Minimum 10 transactions recommended for reliable analysis")
            
            profile.data_quality_notes.append(
                f"Analysis based on {profile.total_transactions} transactions with "
                f"{profile.supported_features} supported features"
            )

            # Flag known data collection gap: lock_script_hash is not populated
            # for cells/inputs in this dataset, so unique_lock_types will read
            # 0 even when the wallet interacts with multiple lock script types.
            lock_feature = features.get("unique_lock_types")
            if lock_feature is not None and lock_feature.value == 0:
                profile.limitations.append(
                    "Lock script hash was not captured during data collection for this "
                    "dataset; unique_lock_types reads 0 by data-collection limitation, "
                    "not necessarily by observed behavior — do not interpret as verified "
                    "single-lock-type usage"
                )

            # Add standard limitations
            profile.limitations.append("No identity classification performed; analysis is behavioral description only")
            profile.limitations.append("Single observation period; temporal generalization not supported")
            profile.limitations.append("Cell/script patterns observed but not linked to owner identity")
            profile.limitations.append("Results represent exploratory behavioral structures, not definitive taxonomy")
            
            logger.info(f"Analysis complete. Classified as: {structure.value}")
            
        except Exception as e:
            logger.error(f"Error during analysis: {e}", exc_info=True)
            profile.data_quality_notes.append(f"Error during analysis: {str(e)}")
        finally:
            self.collector.disconnect()
        
        return profile


# Main execution
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example usage
    async def main():
        db_path = Path("ckb_data/ckb-behaviour-dataset-v1.sqlite")
        pipeline = InferencePipeline(db_path, use_live_data=False)
        
        # Analyze a wallet (example address)
        result = await pipeline.analyze_wallet("ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf")
        
        # Output results
        print(json.dumps(result.to_dict(), indent=2))
    
    asyncio.run(main())