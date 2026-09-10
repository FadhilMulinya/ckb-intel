from __future__ import annotations

from collections import Counter

from .config import MINIMUM_SAMPLES, SCRIPT_REGISTRY_VERSION
from .stats import normalized_entropy, transition_entropy
from .support import FeatureResultV2, SupportState, empty_result, family_support

UNKNOWN = "UNKNOWN"
XUDT_CODE_HASH = "0x50bd8d6680b8b9cf98b73f3c08faf8b2a21914311954118ad6609be6e78a1b95"
TYPE_ID_CODE_HASH = "0x00000000000000000000000000000000000000000000000000545950455f4944"

REGISTRY = {
    ("0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8", "type"):
        "SECP256K1_BLAKE160",
    ("0x5c5069eb0857efc65e1bca0c07df34c31663b3622fd3876c876320fc9634e2a8", "type"):
        "SECP256K1_MULTISIG",
    ("0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e", "type"):
        "NERVOS_DAO",
    (TYPE_ID_CODE_HASH, "type"): "TYPE_ID",
    (XUDT_CODE_HASH, "data1"): "XUDT",
}

REGISTRY_SOURCES = {
    "TYPE_ID": "https://github.com/nervosnetwork/rfcs/blob/master/rfcs/0024-ckb-genesis-script-list/0024-ckb-genesis-script-list.md",
    "XUDT": "https://github.com/nervosnetwork/rfcs/blob/master/rfcs/0052-extensible-udt/0052-extensible-udt.md",
}

FEATURES = [
    "unique_lock_script_count", "unique_type_script_count", "lock_family_count",
    "type_family_count", "lock_family_entropy", "type_family_entropy",
    "dominant_lock_family_ratio", "dominant_type_family_ratio",
    "unknown_lock_script_ratio", "unknown_type_script_ratio",
    "lock_script_repeat_ratio", "type_script_repeat_ratio", "script_transition_entropy",
]


def identify(script: dict | None) -> str:
    if not script:
        return UNKNOWN
    return REGISTRY.get((script.get("code_hash"), script.get("hash_type")), UNKNOWN)


def family_or_hash(script: dict | None, digest: str | None, *, target: bool = False) -> str:
    if target:
        return "TARGET"
    family = identify(script)
    return family if family != UNKNOWN else (digest or UNKNOWN)


def extract(observation: dict) -> FeatureResultV2:
    txs = observation.get("transactions", [])
    minimum = MINIMUM_SAMPLES["scripts"]
    requirements = {"minimum_transactions": minimum, "requires_full_scripts": True,
                    "registry_version": SCRIPT_REGISTRY_VERSION,
                    "registry_sources": REGISTRY_SOURCES}
    if len(txs) < minimum:
        return empty_result("scripts", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(txs), FEATURES)
    locks, types, sequence = [], [], []
    lock_hashes, type_hashes, cells = [], [], 0
    for tx in txs:
        tx_sequence = []
        for item, resolved in [(item, True) for item in tx.get("inputs", [])] + \
                              [(item, False) for item in tx.get("outputs", [])]:
            cells += 1
            prefix = "resolved_" if resolved else ""
            lock, lock_hash = item.get(prefix + "lock_script"), item.get(prefix + "lock_script_hash")
            type_script, type_hash = item.get(prefix + "type_script"), item.get(prefix + "type_script_hash")
            if lock_hash:
                lock_hashes.append(lock_hash); locks.append(identify(lock)); tx_sequence.append(f"L:{identify(lock)}")
            if type_hash:
                type_hashes.append(type_hash); types.append(identify(type_script)); tx_sequence.append(f"T:{identify(type_script)}")
        sequence.append(tuple(tx_sequence))
    lock_counts, type_counts = Counter(locks), Counter(types)
    dominant = lambda counts, total: counts.most_common(1)[0][1] / total if total else None
    repeat = lambda hashes: 1 - len(set(hashes)) / len(hashes) if hashes else None
    values = {
        "unique_lock_script_count": len(set(lock_hashes)),
        "unique_type_script_count": len(set(type_hashes)),
        "lock_family_count": len(set(locks) - {UNKNOWN}),
        "type_family_count": len(set(types) - {UNKNOWN}),
        "lock_family_entropy": normalized_entropy(locks), "type_family_entropy": normalized_entropy(types),
        "dominant_lock_family_ratio": dominant(lock_counts, len(locks)),
        "dominant_type_family_ratio": dominant(type_counts, len(types)),
        "unknown_lock_script_ratio": locks.count(UNKNOWN) / len(locks) if locks else None,
        "unknown_type_script_ratio": types.count(UNKNOWN) / len(types) if types else None,
        "lock_script_repeat_ratio": repeat(lock_hashes), "type_script_repeat_ratio": repeat(type_hashes),
        "script_transition_entropy": transition_entropy(sequence),
    }
    full = len(lock_hashes) + len(type_hashes)
    expected_lock_slots = sum(len(tx.get("inputs", [])) + len(tx.get("outputs", [])) for tx in txs)
    expected_type_slots = sum(bool(item.get("resolved_type_script_hash"))
                              for tx in txs for item in tx.get("inputs", [])) + \
                          sum(bool(item.get("type_script_hash"))
                              for tx in txs for item in tx.get("outputs", []))
    expected = expected_lock_slots + expected_type_slots
    coverage = full / expected if expected else None
    support = family_support(observation, len(txs), minimum, coverage_complete=coverage == 1)
    return FeatureResultV2("scripts", support, requirements, len(txs),
                           {"full_script_slot_coverage": coverage}, values,
                           {"lock_family_counts": dict(lock_counts),
                            "type_family_counts": dict(type_counts)})
