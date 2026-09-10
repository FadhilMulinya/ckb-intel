from __future__ import annotations

import hashlib
import json
from collections import Counter

from .config import MINIMUM_SAMPLES
from .scripts import family_or_hash
from .stats import normalized_entropy, transition_entropy
from .support import FeatureResultV2, SupportState, empty_result, family_support
from .topology import transaction_topology

FEATURES = ["unique_template_count", "dominant_template_ratio", "template_repeat_ratio",
            "template_entropy", "rare_template_ratio", "template_transition_entropy",
            "consecutive_template_repeat_ratio", "template_periodicity_support",
            "dominant_template_coverage", "dominant_template_count", "transition_repeat_ratio"]


def _data_length(value) -> int | None:
    return len(value.removeprefix("0x")) // 2 if isinstance(value, str) else None


def _relative_capacity(cells: list[dict], resolved: bool) -> list[float | None]:
    key = "resolved_capacity" if resolved else "capacity"
    values = [cell.get(key) for cell in cells]
    total = sum(value for value in values if value is not None)
    return sorted(round((value / total) / .05) * .05 if value is not None and total else None
                  for value in values)


def _cell(cell: dict, resolved: bool) -> dict:
    prefix = "resolved_" if resolved else ""
    target = bool(cell.get("target_controls_input" if resolved else "target_controls_output"))
    return {"lock": family_or_hash(cell.get(prefix + "lock_script"),
                                    cell.get(prefix + "lock_script_hash"), target=target),
            "type": family_or_hash(cell.get(prefix + "type_script"),
                                    cell.get(prefix + "type_script_hash")),
            "data_length": _data_length(cell.get(prefix + "output_data"))}


def fingerprint(tx: dict) -> tuple[str, dict]:
    inputs, outputs = tx.get("inputs", []), tx.get("outputs", [])
    topology = transaction_topology(tx)["topology"]
    shape = {"input_cell_count": len(inputs), "output_cell_count": len(outputs),
             "target_input_count": sum(bool(item.get("target_controls_input")) for item in inputs),
             "target_output_count": sum(bool(item.get("target_controls_output")) for item in outputs),
             "inputs": sorted((_cell(item, True) for item in inputs), key=lambda item: json.dumps(item, sort_keys=True)),
             "outputs": sorted((_cell(item, False) for item in outputs), key=lambda item: json.dumps(item, sort_keys=True)),
             "input_capacity_shape": _relative_capacity(inputs, True),
             "output_capacity_shape": _relative_capacity(outputs, False), "topology": topology}
    encoded = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), shape


def extract(observation: dict, periodicity_result=None) -> FeatureResultV2:
    txs = sorted(observation.get("transactions", []),
                 key=lambda tx: (tx.get("block_timestamp") or 0, tx.get("transaction_index") or 0))
    minimum = MINIMUM_SAMPLES["templates"]
    requirements = {"minimum_transactions": minimum, "target_lock_representation": "TARGET",
                    "capacity_shape_rounding": 0.05}
    if len(txs) < minimum:
        return empty_result("templates", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(txs), FEATURES)
    pairs = [fingerprint(tx) for tx in txs]
    hashes, shapes = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
    counts = Counter(hashes)
    transitions = list(zip(hashes, hashes[1:]))
    transition_counts = Counter(transitions)
    dominant_count = counts.most_common(1)[0][1]
    running = 0
    dominant_template_count = 0
    for _, count in counts.most_common():
        running += count; dominant_template_count += 1
        if running / len(hashes) >= .80:
            break
    repeated = sum(count for count in counts.values() if count > 1)
    values = {"unique_template_count": len(counts),
              "dominant_template_ratio": dominant_count / len(hashes),
              "template_repeat_ratio": repeated / len(hashes),
              "template_entropy": normalized_entropy(hashes),
              "rare_template_ratio": sum(count == 1 for count in counts.values()) / len(hashes),
              "template_transition_entropy": transition_entropy(hashes),
              "consecutive_template_repeat_ratio": sum(a == b for a, b in transitions) / len(transitions)
              if transitions else None,
              "template_periodicity_support": ((periodicity_result.values.get("periodicity_strength") or 0) *
                                               (repeated / len(hashes))) if periodicity_result else None,
              "dominant_template_coverage": sum(count for _, count in counts.most_common(3)) / len(hashes),
              "dominant_template_count": dominant_template_count,
              "transition_repeat_ratio": (sum(count for count in transition_counts.values() if count > 1) /
                                           len(transitions)) if transitions else None}
    support = family_support(observation, len(txs), minimum, require_inputs=True)
    return FeatureResultV2("templates", support, requirements, len(txs),
                           {"comparable_transaction_ratio": 1.0}, values,
                           {"transaction_templates": {tx.get("tx_hash"): digest
                                                      for tx, digest in zip(txs, hashes)},
                            "template_shapes": dict(zip(hashes, shapes))})
