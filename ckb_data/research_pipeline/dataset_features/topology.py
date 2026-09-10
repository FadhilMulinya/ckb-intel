from __future__ import annotations

import math
import statistics
from collections import Counter

from .base import FeatureResult, SupportState, observation_support

MIN_TOPOLOGY_TRANSACTIONS = 3


def transaction_topology(tx: dict) -> dict:
    inputs, outputs = tx.get("inputs", []), tx.get("outputs", [])
    target_inputs = sum(bool(item.get("target_controls_input")) for item in inputs)
    target_outputs = sum(bool(item.get("target_controls_output")) for item in outputs)
    input_locks = {item.get("resolved_lock_script_hash") for item in inputs
                   if item.get("resolved_lock_script_hash")}
    output_locks = {item.get("lock_script_hash") for item in outputs if item.get("lock_script_hash")}
    target_input_locks = {item.get("resolved_lock_script_hash") for item in inputs
                          if item.get("target_controls_input")}
    target_output_locks = {item.get("lock_script_hash") for item in outputs
                           if item.get("target_controls_output")}
    return {
        "tx_hash": tx.get("tx_hash"), "target_input_cell_count": target_inputs,
        "target_output_cell_count": target_outputs,
        "external_input_lock_count": len(input_locks - target_input_locks),
        "external_output_lock_count": len(output_locks - target_output_locks),
        "total_input_cell_count": len(inputs), "total_output_cell_count": len(outputs),
        "unique_input_lock_count": len(input_locks), "unique_output_lock_count": len(output_locks),
    }


def _entropy(signatures: list[tuple]) -> float:
    counts = Counter(signatures)
    if len(counts) <= 1:
        return 0.0
    raw = -sum((n / len(signatures)) * math.log2(n / len(signatures)) for n in counts.values())
    return raw / math.log2(len(counts))


def extract(observation: dict) -> FeatureResult:
    rows = [transaction_topology(tx) for tx in observation.get("transactions", [])]
    support = observation_support(observation, minimum_transactions=MIN_TOPOLOGY_TRANSACTIONS,
                                  require_inputs=True)
    requirements = {"minimum_transactions": MIN_TOPOLOGY_TRANSACTIONS,
                    "requires_input_resolution": True}
    if len(rows) < MIN_TOPOLOGY_TRANSACTIONS:
        return FeatureResult("topology", SupportState.INSUFFICIENT_EVIDENCE,
                             {name: None for name in TOPOLOGY_FEATURES}, requirements,
                             {"transactions": len(rows), "transactions_detail": rows})
    signatures = [(r["total_input_cell_count"], r["total_output_cell_count"],
                   r["unique_input_lock_count"], r["unique_output_lock_count"],
                   bool(r["target_input_cell_count"]), bool(r["target_output_cell_count"])) for r in rows]
    dominant = Counter(signatures).most_common(1)[0][1] / len(rows)
    mean = lambda key: statistics.mean(row[key] for row in rows)
    values = {
        "mean_input_cells_per_tx": mean("total_input_cell_count"),
        "mean_output_cells_per_tx": mean("total_output_cell_count"),
        "max_input_cells_per_tx": max(r["total_input_cell_count"] for r in rows),
        "max_output_cells_per_tx": max(r["total_output_cell_count"] for r in rows),
        "fanin_transaction_ratio": sum(r["target_output_cell_count"] > 0 and r["unique_input_lock_count"] > 1 for r in rows) / len(rows),
        "fanout_transaction_ratio": sum(r["target_input_cell_count"] > 0 and r["unique_output_lock_count"] > 1 for r in rows) / len(rows),
        "many_to_many_ratio": sum(r["unique_input_lock_count"] > 1 and r["unique_output_lock_count"] > 1 for r in rows) / len(rows),
        "cell_fragmentation_ratio": sum(r["target_input_cell_count"] > 0 and r["total_output_cell_count"] > r["total_input_cell_count"] for r in rows) / len(rows),
        "cell_consolidation_ratio": sum(r["target_output_cell_count"] > 0 and r["total_input_cell_count"] > r["total_output_cell_count"] for r in rows) / len(rows),
        "mean_external_input_locks": mean("external_input_lock_count"),
        "mean_external_output_locks": mean("external_output_lock_count"),
        "topology_entropy": _entropy(signatures),
        "topology_repeat_ratio": dominant,
    }
    return FeatureResult("topology", support, values, requirements,
                         {"transactions": len(rows), "transactions_detail": rows})


TOPOLOGY_FEATURES = ["mean_input_cells_per_tx", "mean_output_cells_per_tx",
    "max_input_cells_per_tx", "max_output_cells_per_tx", "fanin_transaction_ratio",
    "fanout_transaction_ratio", "many_to_many_ratio", "cell_fragmentation_ratio",
    "cell_consolidation_ratio", "mean_external_input_locks",
    "mean_external_output_locks", "topology_entropy", "topology_repeat_ratio"]
