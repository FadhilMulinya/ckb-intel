from typing import Dict, Tuple, List

import config

LABELS = [
    "INACTIVE", "MINER_POOL", "BOT_AUTOMATION", "BATCH_DISTRIBUTOR",
    "FAN_IN_COLLECTOR", "DAO_PARTICIPANT", "NORMAL_HUMAN", "INSUFFICIENT_EVIDENCE",
]


def heuristic_label(feat: Dict[str, float], meta: Dict) -> Tuple[str, float, List[str]]:
    """Returns (label, confidence in [0,1], reason_codes)."""
    reasons = []

    if meta["transactions_observed"] == 0:
        return "INACTIVE", 1.0, ["ZERO_TRANSACTIONS_IN_WINDOW"]

    if meta["evidence_state"] == "INSUFFICIENT_EVIDENCE":
        return "INSUFFICIENT_EVIDENCE", 1.0, [f"ONLY_{meta['transactions_observed']}_TX_OBSERVED"]

    
    if feat["is_known_miner_address"] >= 1.0 or feat["cellbase_reward_ratio"] >= 0.3:
        if feat["is_known_miner_address"] >= 1.0:
            reasons.append("ADDRESS_IS_BLOCK_MINER_HASH")
        if feat["cellbase_reward_ratio"] >= 0.3:
            reasons.append("HIGH_CELLBASE_INPUT_RATIO")
        confidence = min(1.0, 0.6 + feat["cellbase_reward_ratio"])
        return "MINER_POOL", confidence, reasons

    if feat["dao_capacity_share"] >= 0.4 and feat["dao_interaction_count"] >= 2:
        reasons = ["HIGH_DAO_CELL_SHARE", "REPEATED_DAO_INTERACTION"]
        return "DAO_PARTICIPANT", min(1.0, feat["dao_capacity_share"]), reasons

    
    if feat["fanout_tx_ratio"] >= 0.3 and feat["fanout_dest_count"] >= 5:
        reasons = ["REPEATED_FANOUT", f"FANOUT_TX_RATIO_{feat['fanout_tx_ratio']:.2f}"]
        if feat["topology_repetition"] >= 0.4:
            reasons.append("RECIPIENT_STRUCTURE_RECURRENCE")
        if meta["periodicity_evidence"] and feat["periodicity_strength"] >= 0.35:
            reasons.append("REGULAR_DISTRIBUTION_INTERVAL")
        return "BATCH_DISTRIBUTOR", min(1.0, 0.5 + feat["fanout_tx_ratio"]), reasons

    
    if feat["fanin_tx_ratio"] >= 0.3 and feat["fanin_source_count"] >= 5:
        reasons = ["REPEATED_FANIN", f"FANIN_TX_RATIO_{feat['fanin_tx_ratio']:.2f}", "SOURCE_RECURRENCE"]
        if meta["periodicity_evidence"] and feat["periodicity_strength"] >= 0.35:
            reasons.append("REGULAR_COLLECTION_INTERVAL")
        return "FAN_IN_COLLECTOR", min(1.0, 0.5 + feat["fanin_tx_ratio"]), reasons

    
    if meta["periodicity_evidence"]:
        periodic_signal = (
            feat["periodicity_strength"] >= 0.35 and feat["interarrival_cv"] <= 0.6
        ) or feat["repeated_since_value_ratio"] >= 0.6
        template_signal = feat["topology_repetition"] >= 0.6 and feat["interval_repeat_ratio"] >= 0.3
        if periodic_signal or template_signal:
            if periodic_signal:
                reasons.append("STABLE_INTERARRIVAL_PERIOD")
            if feat["repeated_since_value_ratio"] >= 0.6:
                reasons.append("REPEATED_SINCE_LOCK_VALUE")
            if template_signal:
                reasons.append("REPEATED_TRANSACTION_TEMPLATE")
            confidence = min(1.0, 0.5 + feat["periodicity_strength"] + 0.2 * template_signal)
            return "BOT_AUTOMATION", confidence, reasons

    
    reasons = ["NO_STRONG_AUTOMATION_OR_STRUCTURAL_SIGNAL", "SUFFICIENT_EVIDENCE"]
    near_miss = max(feat["fanout_tx_ratio"], feat["fanin_tx_ratio"], feat["periodicity_strength"])
    confidence = max(0.4, 1.0 - near_miss)
    return "NORMAL_HUMAN", confidence, reasons


def label_dataframe_row(feat: Dict[str, float], meta: Dict) -> Dict:
    label, confidence, reasons = heuristic_label(feat, meta)
    return {"label": label, "label_confidence": confidence, "reason_codes": ";".join(reasons)}
