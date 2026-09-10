"""Service orchestration for the current CKB-native V2 behaviour pipeline.

This module deliberately contains no feature formulas and no identity
classification.  It loads frozen observations and delegates all feature and
rule computation to ``classifier-service/wallet_intelligence/features_v2``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CKB_DATA = REPO_ROOT / "ckb_data"

from wallet_intelligence.features_v2.pipeline import assess_observation_v2, load_observation_v2  # noqa: E402

V2_VERSION = "wallet-behaviour-v2"
NETWORK = "mainnet"
FAMILIES = ("temporal", "periodicity", "topology", "lifecycle", "templates",
            "scripts", "typed_assets", "capacity", "lineage")


class AnalysisError(Exception):
    """Expected service-level error with a stable status code."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for bit, generator in enumerate(generators):
            if (top >> bit) & 1:
                chk ^= generator
    return chk


def validate_ckb_address(address: str) -> bool:
    """Validate a mainnet CKB bech32 address without network access."""
    if not isinstance(address, str) or not address or address.lower() != address:
        return False
    if not address.startswith("ckb1") or address.count("1") != 1:
        return False
    separator = address.rfind("1")
    data = address[separator + 1:]
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    if len(data) < 7 or any(char not in charset for char in data):
        return False
    values = [charset.index(char) for char in data]
    # CKB full/short addresses use the bech32m checksum constant.
    return _bech32_polymod([ord(char) >> 5 for char in "ckb"] + [0] +
                           [ord(char) & 31 for char in "ckb"] + values) == 0x2BC830A3


def _observation_status(collection_state: str | None) -> str:
    if collection_state == "FAILED_INVALID_ADDRESS":
        return "INVALID_ADDRESS"
    if collection_state and collection_state.startswith("FAILED_"):
        return "COLLECTION_FAILED"
    if collection_state == "PARTIAL":
        return "PARTIAL"
    return "SUPPORTED"


class V2WalletService:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (CKB_DATA / "ckb_data_v2" / "ckb_explorer.sqlite")

    def analyze_frozen(self, address: str) -> dict[str, Any]:
        if not validate_ckb_address(address):
            raise AnalysisError("INVALID_ADDRESS", "invalid mainnet CKB address")
        if not self.db_path.exists():
            raise AnalysisError("COLLECTION_FAILED", f"database not found: {self.db_path}")

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT observation_id FROM wallet_observations WHERE address=? LIMIT 1",
                (address,),
            ).fetchone()
            state_row = conn.execute(
                "SELECT collection_state FROM wallet_collection_state WHERE address=? LIMIT 1",
                (address,),
            ).fetchone()
            collection_state = state_row[0] if state_row else None
            if not row:
                if collection_state and collection_state.startswith("FAILED_"):
                    raise AnalysisError("COLLECTION_FAILED", collection_state)
                raise AnalysisError("NOT_IN_FROZEN_DATASET", "address is not in the frozen observation set")
            observation = load_observation_v2(conn, row[0], collection_state=collection_state)
            result = assess_observation_v2(observation)

        metadata = observation.get("metadata", {})
        transactions = observation.get("transactions", [])
        evidence = {
            "transactions": len(transactions),
            "inputs": sum(len(tx.get("inputs", [])) for tx in transactions),
            "outputs": sum(len(tx.get("outputs", [])) for tx in transactions),
            "cells": len(observation.get("observed_target_cells", [])),
        }
        return {
            "version": V2_VERSION,
            "address": address,
            "network": NETWORK,
            "observation": {
                "source": metadata.get("source_version", "ckb_explorer_api"),
                "mode": "frozen",
                "window_start": metadata.get("window_start_timestamp"),
                "window_end": metadata.get("window_end_timestamp"),
                "status": _observation_status(collection_state),
            },
            "evidence": evidence,
            "feature_support": {
                family: result["features"][family]["support_state"] for family in FAMILIES
            },
            "features": result["features"],
            "behaviors": result["rules"],
            "limitations": [
                "Observable behaviour only; no identity or ownership attribution.",
                "Results are bounded by the frozen cohort and 30-day observation window.",
            ],
        }

    def analyze(self, address: str, *, live: bool = False) -> dict[str, Any]:
        if not validate_ckb_address(address):
            raise AnalysisError("INVALID_ADDRESS", "invalid mainnet CKB address")
        if live:
            raise AnalysisError(
                "V2_LIVE_ANALYSIS_NOT_YET_SUPPORTED",
                "live collection has not yet been wired to a V2-compatible observation",
            )
        return self.analyze_frozen(address)
