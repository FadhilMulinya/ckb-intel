from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

from .base import FeatureResult, SupportState, observation_support
from .scripts import family_or_hash

MIN_TEMPLATE_TRANSACTIONS = 3


def _capacity_shape(cells: list[dict]) -> list[float | None]:
    capacities = [cell.get("capacity") or cell.get("resolved_capacity") for cell in cells]
    total = sum(value for value in capacities if value is not None)
    if not total or any(value is None for value in capacities):
        return [None for _ in capacities]
    return sorted(round(value / total, 2) for value in capacities)


def _cell_shape(cell: dict, *, resolved: bool) -> dict:
    prefix = "resolved_" if resolved else ""
    lock_script = cell.get(prefix + "lock_script")
    lock_hash = cell.get(prefix + "lock_script_hash")
    type_script = cell.get(prefix + "type_script")
    type_hash = cell.get(prefix + "type_script_hash")
    data = cell.get(prefix + "output_data")
    return {"lock": family_or_hash(lock_script, lock_hash),
            "type": family_or_hash(type_script, type_hash),
            "data_bytes": max(0, (len(data.removeprefix("0x")) // 2)) if isinstance(data, str) else None}


def transaction_template(tx: dict) -> dict:
    inputs, outputs = tx.get("inputs", []), tx.get("outputs", [])
    return {
        "input_count": len(inputs), "output_count": len(outputs),
        "target_input": any(item.get("target_controls_input") for item in inputs),
        "target_output": any(item.get("target_controls_output") for item in outputs),
        "input_shapes": sorted((_cell_shape(item, resolved=True) for item in inputs),
                               key=lambda value: json.dumps(value, sort_keys=True)),
        "output_shapes": sorted((_cell_shape(item, resolved=False) for item in outputs),
                                key=lambda value: json.dumps(value, sort_keys=True)),
        "input_capacity_shape": _capacity_shape(inputs),
        "output_capacity_shape": _capacity_shape(outputs),
    }


def transaction_template_hash(tx: dict) -> str:
    encoded = json.dumps(transaction_template(tx), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _entropy(counts: list[int]) -> float:
    total = sum(counts)
    return -sum((n / total) * math.log2(n / total) for n in counts) if total else 0.0


def extract(observation: dict) -> FeatureResult:
    txs = observation.get("transactions", [])
    support = observation_support(observation, minimum_transactions=MIN_TEMPLATE_TRANSACTIONS,
                                  require_inputs=True)
    requirements = {"minimum_transactions": MIN_TEMPLATE_TRANSACTIONS,
                    "excludes": ["tx_hash", "block_number", "timestamp", "witnesses"]}
    if len(txs) < MIN_TEMPLATE_TRANSACTIONS:
        return FeatureResult("templates", SupportState.INSUFFICIENT_EVIDENCE,
                             {name: None for name in TEMPLATE_FEATURES}, requirements,
                             {"transactions": len(txs)})
    hashes = [transaction_template_hash(tx) for tx in txs]
    counts = Counter(hashes)
    transitions = Counter(zip(hashes, hashes[1:]))
    transition_entropy = _entropy(list(transitions.values())) if transitions else 0.0
    values = {"unique_template_count": len(counts),
              "dominant_template_ratio": counts.most_common(1)[0][1] / len(hashes),
              "template_entropy": _entropy(list(counts.values())),
              "template_repeat_ratio": sum(n for n in counts.values() if n > 1) / len(hashes),
              "template_transition_entropy": transition_entropy}
    return FeatureResult("templates", support, values, requirements,
                         {"transactions": len(txs),
                          "transaction_templates": dict(zip((tx["tx_hash"] for tx in txs), hashes))})


TEMPLATE_FEATURES = ["unique_template_count", "dominant_template_ratio",
                     "template_entropy", "template_repeat_ratio",
                     "template_transition_entropy"]
