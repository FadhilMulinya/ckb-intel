"""Target-lock capacity projections without pairwise attribution or change inference."""
from __future__ import annotations

import statistics

from .base import FeatureResult, SupportState, observation_support


CAPACITY_FEATURES = [
    "target_input_capacity_shannon", "target_output_capacity_shannon",
    "target_net_capacity_delta_shannon", "mean_target_input_capacity_shannon",
    "mean_target_output_capacity_shannon", "median_abs_target_delta_shannon",
]


def extract(observation: dict) -> FeatureResult:
    txs = observation.get("transactions", [])
    support = observation_support(observation, minimum_transactions=1,
                                  require_inputs=True)
    rows = []
    for tx in txs:
        inputs = [item.get("resolved_capacity") for item in tx.get("inputs", [])
                  if item.get("target_controls_input")]
        outputs = [item.get("capacity") for item in tx.get("outputs", [])
                   if item.get("target_controls_output")]
        if any(value is None for value in inputs + outputs):
            continue
        input_total, output_total = sum(inputs), sum(outputs)
        rows.append((input_total, output_total, output_total - input_total))
    requirements = {"minimum_transactions": 1, "requires_input_resolution": True,
                    "pairwise_value_attribution": "NOT_ESTABLISHED"}
    if not txs:
        return FeatureResult("capacity", SupportState.INSUFFICIENT_EVIDENCE,
                             {name: None for name in CAPACITY_FEATURES}, requirements,
                             {"transactions": 0, "resolved_transactions": 0})
    if len(rows) != len(txs):
        support = SupportState.PARTIAL
    values = {
        "target_input_capacity_shannon": sum(row[0] for row in rows),
        "target_output_capacity_shannon": sum(row[1] for row in rows),
        "target_net_capacity_delta_shannon": sum(row[2] for row in rows),
        "mean_target_input_capacity_shannon": statistics.mean(row[0] for row in rows) if rows else None,
        "mean_target_output_capacity_shannon": statistics.mean(row[1] for row in rows) if rows else None,
        "median_abs_target_delta_shannon": statistics.median(abs(row[2]) for row in rows) if rows else None,
    }
    return FeatureResult("capacity", support, values, requirements,
                         {"transactions": len(txs), "resolved_transactions": len(rows)})
