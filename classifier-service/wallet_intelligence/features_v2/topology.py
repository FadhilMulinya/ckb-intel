from __future__ import annotations

import statistics
from collections import Counter

from .config import MINIMUM_SAMPLES
from .stats import cv, normalized_entropy, transition_entropy
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = [
    "one_to_one_ratio", "one_to_many_ratio", "many_to_one_ratio", "many_to_many_ratio",
    "other_topology_ratio", "dominant_topology", "dominant_topology_ratio",
    "input_cell_count_mean", "input_cell_count_median", "input_cell_count_cv",
    "output_cell_count_mean", "output_cell_count_median", "output_cell_count_cv",
    "external_input_lock_mean", "external_output_lock_mean", "topology_entropy",
    "topology_repeat_ratio", "topology_transition_entropy", "fragmentation_event_count",
    "fragmentation_event_ratio", "consolidation_event_count", "consolidation_event_ratio",
    "mean_fragmentation_factor", "max_fragmentation_factor",
    "mean_consolidation_factor", "max_consolidation_factor",
]


def transaction_topology(tx: dict) -> dict:
    inputs, outputs = tx.get("inputs", []), tx.get("outputs", [])
    input_locks = {item.get("resolved_lock_script_hash") for item in inputs
                   if item.get("resolved_lock_script_hash")}
    output_locks = {item.get("lock_script_hash") for item in outputs if item.get("lock_script_hash")}
    target_inputs = [item for item in inputs if item.get("target_controls_input")]
    target_outputs = [item for item in outputs if item.get("target_controls_output")]
    input_count, output_count = len(inputs), len(outputs)
    if input_count == 1 and output_count == 1:
        topology = "1_TO_1"
    elif input_count == 1 and output_count > 1:
        topology = "1_TO_N"
    elif input_count > 1 and output_count == 1:
        topology = "N_TO_1"
    elif input_count > 1 and output_count > 1:
        topology = "N_TO_N"
    else:
        topology = "OTHER"
    ti, to = len(target_inputs), len(target_outputs)
    fragmentation = ti > 0 and to > ti
    consolidation = to > 0 and ti > to
    return {
        "tx_hash": tx.get("tx_hash"), "input_cell_count": input_count,
        "output_cell_count": output_count, "unique_input_lock_count": len(input_locks),
        "unique_output_lock_count": len(output_locks), "target_input_cell_count": ti,
        "target_output_cell_count": to,
        "external_input_lock_count": len(input_locks - {item.get("resolved_lock_script_hash")
                                                         for item in target_inputs}),
        "external_output_lock_count": len(output_locks - {item.get("lock_script_hash")
                                                           for item in target_outputs}),
        "topology": topology, "fragmentation": fragmentation,
        "consolidation": consolidation,
        "fragmentation_factor": to / ti if fragmentation else None,
        "consolidation_factor": ti / to if consolidation else None,
    }


def extract(observation: dict) -> FeatureResultV2:
    rows = [transaction_topology(tx) for tx in observation.get("transactions", [])]
    minimum = MINIMUM_SAMPLES["topology"]
    requirements = {"minimum_transactions": minimum, "requires_input_resolution": True,
                    "pairwise_transfer_attribution": "NOT_ESTABLISHED"}
    if len(rows) < minimum:
        return empty_result("topology", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(rows), FEATURES,
                            {"transactions_detail": rows})
    counts = Counter(row["topology"] for row in rows)
    sequence = [row["topology"] for row in rows]
    inputs = [row["input_cell_count"] for row in rows]
    outputs = [row["output_cell_count"] for row in rows]
    fragmentation = [row["fragmentation_factor"] for row in rows
                     if row["fragmentation_factor"] is not None]
    consolidation = [row["consolidation_factor"] for row in rows
                     if row["consolidation_factor"] is not None]
    dominant, dominant_count = counts.most_common(1)[0]
    ratio = lambda name: counts.get(name, 0) / len(rows)
    values = {
        "one_to_one_ratio": ratio("1_TO_1"), "one_to_many_ratio": ratio("1_TO_N"),
        "many_to_one_ratio": ratio("N_TO_1"), "many_to_many_ratio": ratio("N_TO_N"),
        "other_topology_ratio": ratio("OTHER"), "dominant_topology": dominant,
        "dominant_topology_ratio": dominant_count / len(rows),
        "input_cell_count_mean": statistics.mean(inputs),
        "input_cell_count_median": statistics.median(inputs), "input_cell_count_cv": cv(inputs),
        "output_cell_count_mean": statistics.mean(outputs),
        "output_cell_count_median": statistics.median(outputs), "output_cell_count_cv": cv(outputs),
        "external_input_lock_mean": statistics.mean(row["external_input_lock_count"] for row in rows),
        "external_output_lock_mean": statistics.mean(row["external_output_lock_count"] for row in rows),
        "topology_entropy": normalized_entropy(sequence),
        "topology_repeat_ratio": dominant_count / len(rows),
        "topology_transition_entropy": transition_entropy(sequence),
        "fragmentation_event_count": len(fragmentation),
        "fragmentation_event_ratio": len(fragmentation) / len(rows),
        "consolidation_event_count": len(consolidation),
        "consolidation_event_ratio": len(consolidation) / len(rows),
        "mean_fragmentation_factor": statistics.mean(fragmentation) if fragmentation else 0,
        "max_fragmentation_factor": max(fragmentation, default=0),
        "mean_consolidation_factor": statistics.mean(consolidation) if consolidation else 0,
        "max_consolidation_factor": max(consolidation, default=0),
    }
    support = family_support(observation, len(rows), minimum, require_inputs=True)
    return FeatureResultV2("topology", support, requirements, len(rows),
                           {"transaction_coverage": 1.0}, values,
                           {"transactions_detail": rows})

