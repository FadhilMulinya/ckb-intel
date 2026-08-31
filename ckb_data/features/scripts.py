"""Versioned registry of conservatively recognized CKB script families."""
from __future__ import annotations

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
