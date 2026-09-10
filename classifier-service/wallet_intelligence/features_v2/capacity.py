from __future__ import annotations

import statistics
from collections import Counter

from .config import MINIMUM_SAMPLES
from .stats import cv, normalized_entropy
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = ["input_capacity_mean", "input_capacity_median", "input_capacity_cv",
            "output_capacity_mean", "output_capacity_median", "output_capacity_cv",
            "capacity_repeat_ratio", "capacity_input_entropy", "capacity_output_entropy",
            "target_created_capacity", "target_consumed_capacity", "target_net_capacity_delta",
            "target_occupied_capacity", "target_excess_capacity"]


def extract(observation: dict) -> FeatureResultV2:
    minimum = MINIMUM_SAMPLES["capacity"]
    requirements = {"minimum_transactions": minimum, "requires_input_resolution": True,
                    "occupied_capacity_source": "cached_explorer_raw",
                    "pairwise_value_attribution": "NOT_ESTABLISHED"}
    txs = observation.get("transactions", [])
    if len(txs) < minimum:
        return empty_result("capacity", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(txs), FEATURES)
    inputs, outputs, occupied, impossible = [], [], [], []
    for tx in txs:
        for cell in tx.get("inputs", []):
            if cell.get("target_controls_input") and cell.get("resolved_capacity") is not None:
                inputs.append(cell["resolved_capacity"])
                raw_occupied = (cell.get("raw") or {}).get("occupied_capacity")
                if raw_occupied is not None:
                    occupied.append(int(float(raw_occupied)))
        for cell in tx.get("outputs", []):
            if cell.get("target_controls_output") and cell.get("capacity") is not None:
                outputs.append(cell["capacity"])
                raw_occupied = (cell.get("raw") or {}).get("occupied_capacity")
                if raw_occupied is not None:
                    value = int(float(raw_occupied)); occupied.append(value)
                    if value > cell["capacity"]:
                        impossible.append((tx.get("tx_hash"), cell.get("output_index")))
    if not inputs and not outputs:
        return empty_result("capacity", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(txs), FEATURES)
    all_values = inputs + outputs
    repeated = sum(count for count in Counter(all_values).values() if count > 1) / len(all_values)
    created, consumed = sum(outputs), sum(inputs)
    occupied_total = sum(occupied) if occupied else None
    values = {"input_capacity_mean": statistics.mean(inputs) if inputs else None,
              "input_capacity_median": statistics.median(inputs) if inputs else None,
              "input_capacity_cv": cv(inputs),
              "output_capacity_mean": statistics.mean(outputs) if outputs else None,
              "output_capacity_median": statistics.median(outputs) if outputs else None,
              "output_capacity_cv": cv(outputs), "capacity_repeat_ratio": repeated,
              "capacity_input_entropy": normalized_entropy(inputs),
              "capacity_output_entropy": normalized_entropy(outputs),
              "target_created_capacity": created, "target_consumed_capacity": consumed,
              "target_net_capacity_delta": created - consumed,
              "target_occupied_capacity": occupied_total,
              "target_excess_capacity": sum(all_values) - occupied_total if occupied_total is not None else None}
    complete = not impossible and len(inputs) + len(outputs) > 0 and len(occupied) == len(all_values)
    support = family_support(observation, len(txs), minimum, require_inputs=True,
                             coverage_complete=complete)
    return FeatureResultV2("capacity", support, requirements, len(txs),
                           {"occupied_capacity_cell_ratio": len(occupied) / len(all_values),
                            "impossible_value_count": len(impossible)}, values,
                           {"impossible_cells": impossible})
