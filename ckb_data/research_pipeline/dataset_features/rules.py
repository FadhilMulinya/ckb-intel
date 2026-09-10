from __future__ import annotations

from .base import SupportState
from .evidence import BehaviourEvidence
from .rule_config import THRESHOLDS


def _support(observation: dict) -> dict:
    metadata = observation.get("metadata", {})
    return {"transactions": len(observation.get("transactions", [])),
            "observation_days": 30,
            "detail_coverage": metadata.get("detail_coverage_ratio"),
            "input_resolution_ratio": metadata.get("input_resolution_ratio")}


def periodic_execution(observation: dict, temporal) -> BehaviourEvidence:
    values, threshold = temporal.values, THRESHOLDS["PERIODIC_EXECUTION"]
    if temporal.support_state == SupportState.INSUFFICIENT_EVIDENCE or \
            values.get("periodicity_strength") is None:
        return BehaviourEvidence("PERIODIC_EXECUTION", None,
            SupportState.INSUFFICIENT_EVIDENCE, ["INSUFFICIENT_TEMPORAL_SUPPORT"],
            values, _support(observation), [])
    checks = [(values["periodicity_strength"] >= threshold["periodicity_strength"], "STRONG_PERIODICITY"),
              (values["phase_stability"] >= threshold["phase_stability"], "STABLE_PHASE"),
              (values["interarrival_cv"] <= threshold["maximum_interarrival_cv"], "LOW_INTERVAL_VARIABILITY")]
    reasons = [reason for passed, reason in checks if passed]
    score = sum(passed for passed, _ in checks) / len(checks)
    state = temporal.support_state if score == 1 else SupportState.PARTIAL
    return BehaviourEvidence("PERIODIC_EXECUTION", score, state, reasons, values,
                             _support(observation),
                             temporal.evidence.get("supporting_transactions", []) if score == 1 else [])


def batch_distribution(observation: dict, topology, templates) -> BehaviourEvidence:
    values = {**topology.values, **templates.values}
    threshold = THRESHOLDS["BATCH_DISTRIBUTION"]
    if topology.support_state == SupportState.INSUFFICIENT_EVIDENCE:
        return BehaviourEvidence("BATCH_DISTRIBUTION", None,
            SupportState.INSUFFICIENT_EVIDENCE, ["INSUFFICIENT_TOPOLOGY_SUPPORT"],
            values, _support(observation), [])
    checks = [(values["fanout_transaction_ratio"] >= threshold["fanout_transaction_ratio"], "REPEATED_FAN_OUT_STRUCTURE"),
              (values["mean_external_output_locks"] >= threshold["minimum_external_output_locks"], "MANY_EXTERNAL_OUTPUT_LOCKS"),
              (values["template_repeat_ratio"] >= threshold["minimum_template_repeat_ratio"], "REPEATED_TRANSACTION_TEMPLATE")]
    reasons = [reason for passed, reason in checks if passed]
    score = sum(passed for passed, _ in checks) / len(checks)
    detail = topology.evidence.get("transactions_detail", [])
    supporting = [row["tx_hash"] for row in detail if row["target_input_cell_count"] and row["unique_output_lock_count"] > 1]
    fully_supported = (score == 1 and topology.support_state == SupportState.SUPPORTED
                       and templates.support_state == SupportState.SUPPORTED)
    return BehaviourEvidence("BATCH_DISTRIBUTION", score,
        SupportState.SUPPORTED if fully_supported else SupportState.PARTIAL,
        reasons, values, _support(observation), supporting if score == 1 else [])


def fan_in_collection(observation: dict, topology, templates) -> BehaviourEvidence:
    values = {**topology.values, **templates.values}
    threshold = THRESHOLDS["FAN_IN_COLLECTION"]
    if topology.support_state == SupportState.INSUFFICIENT_EVIDENCE:
        return BehaviourEvidence("FAN_IN_COLLECTION", None,
            SupportState.INSUFFICIENT_EVIDENCE, ["INSUFFICIENT_TOPOLOGY_SUPPORT"],
            values, _support(observation), [])
    checks = [(values["fanin_transaction_ratio"] >= threshold["fanin_transaction_ratio"], "REPEATED_FAN_IN_STRUCTURE"),
              (values["mean_external_input_locks"] >= threshold["minimum_external_input_locks"], "MANY_EXTERNAL_INPUT_LOCKS"),
              (values["topology_repeat_ratio"] >= threshold["minimum_topology_repeat_ratio"], "REPEATED_TOPOLOGY")]
    reasons = [reason for passed, reason in checks if passed]
    score = sum(passed for passed, _ in checks) / len(checks)
    detail = topology.evidence.get("transactions_detail", [])
    supporting = [row["tx_hash"] for row in detail if row["target_output_cell_count"] and row["unique_input_lock_count"] > 1]
    fully_supported = (score == 1 and topology.support_state == SupportState.SUPPORTED
                       and templates.support_state == SupportState.SUPPORTED)
    return BehaviourEvidence("FAN_IN_COLLECTION", score,
        SupportState.SUPPORTED if fully_supported else SupportState.PARTIAL,
        reasons, values, _support(observation), supporting if score == 1 else [])
