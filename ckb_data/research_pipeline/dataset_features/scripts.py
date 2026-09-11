"""Versioned registry of conservatively recognized CKB script families."""
from __future__ import annotations

from collections import Counter

from .base import FeatureResult, SupportState, observation_support

REGISTRY_VERSION = "ckb-script-registry-v1"
UNKNOWN = "UNKNOWN"

REGISTRY = {
    ("0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8", "type"):
        "SECP256K1_BLAKE160",
    ("0x5c5069eb0857efc65e1bca0c07df34c31663b3622fd3876c876320fc9634e2a8", "type"):
        "SECP256K1_MULTISIG",
    ("0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e", "type"):
        "NERVOS_DAO",
}


def identify(script: dict | None) -> dict:
    if not script:
        return {"script_family": UNKNOWN, "registry_version": REGISTRY_VERSION,
                "match_method": "no_script", "confidence": 0.0}
    family = REGISTRY.get((script.get("code_hash"), script.get("hash_type")))
    return {"script_family": family or UNKNOWN, "registry_version": REGISTRY_VERSION,
            "match_method": "exact_code_hash_and_hash_type" if family else "no_match",
            "confidence": 1.0 if family else 0.0}


def family_or_hash(script: dict | None, digest: str | None) -> str:
    match = identify(script)
    return match["script_family"] if match["script_family"] != UNKNOWN else (digest or UNKNOWN)


def extract(observation: dict) -> FeatureResult:
    txs = observation.get("transactions", [])
    support = observation_support(observation, minimum_transactions=1,
                                  require_inputs=False)
    scripts = []
    for tx in txs:
        scripts.extend(item.get("resolved_lock_script") for item in tx.get("inputs", []))
        scripts.extend(item.get("lock_script") for item in tx.get("outputs", []))
        scripts.extend(item.get("resolved_type_script") for item in tx.get("inputs", []))
        scripts.extend(item.get("type_script") for item in tx.get("outputs", []))
    known = [identify(item)["script_family"] for item in scripts if item]
    families = Counter(known)
    if not txs:
        state = SupportState.INSUFFICIENT_EVIDENCE
    elif not scripts or not known:
        state = SupportState.PARTIAL
    else:
        state = support
    total_cells = sum(len(tx.get("inputs", [])) + len(tx.get("outputs", [])) for tx in txs)
    values = {
        "script_family_counts": dict(sorted(families.items())),
        "cells_with_full_script": len(known),
        "total_cells": total_cells,
        "full_script_coverage_ratio": len(known) / total_cells if total_cells else None,
    }
    return FeatureResult("scripts", state, values,
                         {"minimum_transactions": 1, "requires_full_scripts": True},
                         {"transactions": len(txs), "registry_version": REGISTRY_VERSION})
