#!/usr/bin/env python3
"""
CLI Interface for CKB Wallet Behavioral Analysis

Usage:
    python inference_cli.py <wallet_address> [--db <path>] [--live] [--json] [--verbose]

Example:
    python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf --live --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from inference_service import InferencePipeline, BehavioralProfile

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def format_profile_text(profile: BehavioralProfile) -> str:
    """Format behavioral profile as human-readable text."""
    output = []
    output.append("=" * 80)
    output.append("CKB WALLET BEHAVIORAL ANALYSIS REPORT")
    output.append("=" * 80)
    output.append("")
    
    # Wallet info
    output.append("WALLET INFORMATION")
    output.append("-" * 80)
    output.append(f"Address: {profile.wallet_address}")
    if profile.lock_hash:
        output.append(f"Lock Hash: {profile.lock_hash}")
    output.append(f"Analysis Timestamp: {profile.analysis_timestamp}")
    output.append("")
    
    # Observation counts
    output.append("TRANSACTION HISTORY")
    output.append("-" * 80)
    output.append(f"Total Transactions: {profile.total_transactions}")
    output.append(f"Total Inputs: {profile.total_inputs}")
    output.append(f"Total Outputs: {profile.total_outputs}")
    output.append(f"Observed Cells: {profile.observed_cells}")
    output.append(f"Spent Cells: {profile.spent_cells}")
    output.append("")
    
    # Feature summary
    output.append("FEATURE ANALYSIS")
    output.append("-" * 80)
    output.append(f"Supported Features: {profile.supported_features}")
    output.append(f"Partial Features: {profile.partial_features}")
    output.append(f"Insufficient Evidence: {profile.insufficient_features}")
    output.append(f"Missing Features: {profile.missing_features}")
    output.append("")
    
    # Feature details
    if profile.features:
        output.append("EXTRACTED FEATURES")
        output.append("-" * 80)
        for family in ["temporal", "topology", "capacity", "scripts"]:
            family_features = [f for f in profile.features.values() if f.family == family]
            if family_features:
                output.append(f"\n{family.upper()}:")
                for feat in family_features:
                    if feat.value is not None:
                        output.append(
                            f"  • {feat.name}: {feat.value:.4f} "
                            f"[{feat.support_state.value}] ({feat.evidence_count} samples)"
                        )
                    else:
                        output.append(
                            f"  • {feat.name}: N/A [{feat.support_state.value}]"
                        )
                    if feat.description:
                        output.append(f"    → {feat.description}")
        output.append("")
    
    # Behavioral classification
    output.append("BEHAVIORAL CLASSIFICATION")
    output.append("-" * 80)
    output.append(f"Structure: {profile.behavioral_structure.value}")
    output.append(f"Confidence: {profile.behavioral_confidence:.1%}")
    output.append(f"\nDescription:")
    for line in profile.structure_description.split("\n"):
        if line.strip():
            output.append(f"  {line}")
    output.append("")
    
    # Quality assessment
    if profile.data_quality_notes or profile.limitations:
        output.append("QUALITY ASSESSMENT")
        output.append("-" * 80)
        
        if profile.data_quality_notes:
            output.append("Quality Notes:")
            for note in profile.data_quality_notes:
                output.append(f"  ✓ {note}")
        
        if profile.limitations:
            output.append("\nLimitations:")
            for limit in profile.limitations:
                output.append(f"  ⚠ {limit}")
        output.append("")
    
    # Footer
    output.append("=" * 80)
    output.append("IMPORTANT DISCLAIMER")
    output.append("=" * 80)
    output.append(
        "This analysis describes OBSERVABLE ON-CHAIN BEHAVIOR PATTERNS ONLY.\n"
        "It is NOT a human/bot identity classifier and makes NO identity claims.\n"
        "Results are exploratory and representation-dependent (see limitations above)."
    )
    output.append("=" * 80)
    
    return "\n".join(output)


async def analyze_wallet_cli(
    wallet_address: str,
    db_path: Optional[Path] = None,
    use_live: bool = False,
    output_json: bool = False,
    verbose: bool = False
) -> int:
    """
    Analyze a wallet and output results.
    
    Args:
        wallet_address: CKB wallet address or lock hash
        db_path: Path to frozen dataset database
        use_live: Whether to fetch live data from CKB Explorer
        output_json: Whether to output JSON format
        verbose: Whether to enable verbose logging
    
    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Set up logging
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Set default database path
    if db_path is None:
        db_path = Path("ckb_data/ckb_data_v2/ckb_explorer.sqlite")
    
    logger.info(f"Initializing inference pipeline")
    logger.info(f"Database: {db_path}")
    logger.info(f"Use live data: {use_live}")
    
    try:
        # Initialize pipeline
        pipeline = InferencePipeline(db_path, use_live_data=use_live)
        
        # Run analysis
        logger.info(f"Analyzing wallet: {wallet_address}")
        profile = await pipeline.analyze_wallet(wallet_address)
        
        # Output results
        if output_json:
            # JSON output
            print(json.dumps(profile.to_dict(), indent=2))
        else:
            # Human-readable output
            print(format_profile_text(profile))
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(f"Database not found: {e}")
        print("Error: Database file not found", file=sys.stderr)
        print(f"Expected at: {db_path}", file=sys.stderr)
        print("Download from: https://github.com/FadhilMulinya/ckb-intel/releases/tag/ckb-behaviour-dataset-v1", file=sys.stderr)
        return 1
        
    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=verbose)
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CKB Wallet Behavioral Analysis - Inference Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Analyze wallet (offline with cached data)
  python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf
  
  # Analyze wallet with live CKB Explorer data
  python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf --live
  
  # Output JSON format
  python inference_cli.py ckt1qqxv4yfrg69j4zhu007f0u4fs5hnwyx408d837e91cf8923b59044aecfffd9mf --json
  
  # Custom database path
  python inference_cli.py <address> --db /path/to/ckb_explorer.sqlite

IMPORTANT:
  This tool analyzes OBSERVABLE BEHAVIORAL PATTERNS ONLY.
  It makes NO identity classification and is NOT a human/bot detector.
  Results are exploratory and require careful interpretation.
        """
    )
    
    parser.add_argument(
        "wallet_address",
        help="CKB wallet address or lock hash"
    )
    
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to frozen dataset database (default: ckb_data/ckb_data_v2/ckb_explorer.sqlite)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Fetch live data from CKB Explorer API"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results in JSON format"
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Run analysis
    exit_code = asyncio.run(
        analyze_wallet_cli(
            wallet_address=args.wallet_address,
            db_path=args.db,
            use_live=args.live,
            output_json=args.output_json,
            verbose=args.verbose
        )
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
