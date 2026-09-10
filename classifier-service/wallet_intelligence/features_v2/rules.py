from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import RULE_THRESHOLDS, RULE_VERSION
from .support import SupportState

RULE_NAMES = (
    "PERIODIC_EXECUTION", "BATCH_DISTRIBUTION", "FAN_IN_COLLECTION",
    "BURST_EXECUTION", "CELL_FRAGMENTATION", "CELL_CONSOLIDATION",
    "SCRIPT_TEMPLATE_REPETITION", "RAPID_CELL_TURNOVER",
    "PASS_THROUGH_CANDIDATE", "STATE_MACHINE_ACTIVITY",
    "IRREGULAR_ACTIVITY", "MIXED",
)


@dataclass
class BehaviourRuleV2:
    rule: str
    support_state: str
    score: float | None
    reason_codes: list[str]
    supporting_features: dict
    supporting_transaction_hashes: list[str]
    supporting_transaction_count: int
    rule_version: str = RULE_VERSION

    def as_dict(self):
        return asdict(self)


def _state(*families) -> str:
    states = {family.support_state for family in families}
    if SupportState.UNRESOLVED in states:
        return SupportState.UNRESOLVED.value
    if SupportState.INSUFFICIENT_EVIDENCE in states:
        return SupportState.INSUFFICIENT_EVIDENCE.value
    if SupportState.PARTIAL in states:
        return SupportState.PARTIAL.value
    return SupportState.SUPPORTED.value


def _hashes(observation: dict, predicate=None) -> list[str]:
    txs = observation.get("transactions", [])
    hashes = [tx.get("tx_hash") for tx in txs if tx.get("tx_hash") and
              (predicate(tx) if predicate else True)]
    return sorted(set(hashes))


def _rule(name, state, score, reasons, features, hashes):
    return BehaviourRuleV2(name, state, score, reasons, features, hashes[:100], len(hashes))


def evaluate(observation: dict, features: dict[str, object]) -> list[BehaviourRuleV2]:
    temporal, periodicity = features["temporal"], features["periodicity"]
    topology, templates = features["topology"], features["templates"]
    lifecycle, scripts = features["lifecycle"], features["scripts"]
    capacity, lineage = features["capacity"], features["lineage"]
    results, positive = [], []

    def add(name, families, components, passed, reasons, hashes=None):
        state = _state(*families)
        component_values = [value for value in components.values()
                            if isinstance(value, (int, float))]
        score = (sum(component_values) / len(component_values)
                 if component_values and state not in {SupportState.UNRESOLVED.value,
                                                        SupportState.INSUFFICIENT_EVIDENCE.value}
                 else None)
        codes = reasons + (["THRESHOLDS_MET"] if passed else ["THRESHOLDS_NOT_MET"])
        result = _rule(name, state, score, codes,
                       dict(components),
                       hashes or _hashes(observation))
        results.append(result)
        if passed and state in {SupportState.SUPPORTED.value, SupportState.PARTIAL.value}:
            positive.append(name)

    pv, pt = periodicity.values, RULE_THRESHOLDS["PERIODIC_EXECUTION"]
    periodic_components = {"periodicity_strength": pv.get("periodicity_strength"),
                           "phase_stability": pv.get("phase_stability"),
                           "inverse_interarrival_cv": 1 - min(1, temporal.values.get("interarrival_cv") or 1)}
    interarrival_cv = temporal.values.get("interarrival_cv")
    add("PERIODIC_EXECUTION", [temporal, periodicity], periodic_components,
        (pv.get("periodicity_strength") or 0) >= pt["periodicity_strength"] and
        (pv.get("phase_stability") or 0) >= pt["phase_stability"] and
        interarrival_cv is not None and interarrival_cv <= pt["maximum_interarrival_cv"],
        ["TRANSPARENT_V1_BASELINE_RETAINED"])

    tv, xv = topology.values, templates.values
    bt = RULE_THRESHOLDS["BATCH_DISTRIBUTION"]
    batch_components = {"one_to_many_ratio": tv.get("one_to_many_ratio"),
                        "external_output_lock_score": min(1, (tv.get("external_output_lock_mean") or 0) /
                                                          bt["external_output_lock_mean"]),
                        "template_repeat_ratio": xv.get("template_repeat_ratio")}
    add("BATCH_DISTRIBUTION", [topology, templates], batch_components,
        (tv.get("one_to_many_ratio") or 0) >= bt["one_to_many_ratio"] and
        (tv.get("external_output_lock_mean") or 0) >= bt["external_output_lock_mean"] and
        (xv.get("template_repeat_ratio") or 0) >= bt["template_repeat_ratio"],
        ["STRUCTURAL_ONLY", "NO_PAIRWISE_TRANSFER_INFERENCE"])

    ft = RULE_THRESHOLDS["FAN_IN_COLLECTION"]
    fan_components = {"many_to_one_ratio": tv.get("many_to_one_ratio"),
                      "external_input_lock_score": min(1, (tv.get("external_input_lock_mean") or 0) /
                                                        ft["external_input_lock_mean"]),
                      "topology_repeat_ratio": tv.get("topology_repeat_ratio")}
    add("FAN_IN_COLLECTION", [topology, templates], fan_components,
        (tv.get("many_to_one_ratio") or 0) >= ft["many_to_one_ratio"] and
        (tv.get("external_input_lock_mean") or 0) >= ft["external_input_lock_mean"] and
        (tv.get("topology_repeat_ratio") or 0) >= ft["topology_repeat_ratio"],
        ["STRUCTURAL_ONLY", "NO_SENDER_ATTRIBUTION"])

    bv, threshold = temporal.values, RULE_THRESHOLDS["BURST_EXECUTION"]
    burst_components = {"burst_count_score": min(1, (bv.get("burst_count") or 0) / threshold["burst_count"]),
                        "transactions_in_bursts_ratio": bv.get("transactions_in_bursts_ratio")}
    add("BURST_EXECUTION", [temporal], burst_components,
        (bv.get("burst_count") or 0) >= threshold["burst_count"] and
        (bv.get("transactions_in_bursts_ratio") or 0) >= threshold["transactions_in_bursts_ratio"], [])

    for name, ratio_key, factor_key in [
            ("CELL_FRAGMENTATION", "fragmentation_event_ratio", "mean_fragmentation_factor"),
            ("CELL_CONSOLIDATION", "consolidation_event_ratio", "mean_consolidation_factor")]:
        threshold = RULE_THRESHOLDS[name]
        components = {ratio_key: tv.get(ratio_key),
                      "factor_score": min(1, (tv.get(factor_key) or 0) / threshold["mean_factor"])}
        add(name, [topology], components,
            (tv.get(ratio_key) or 0) >= threshold["event_ratio"] and
            (tv.get(factor_key) or 0) >= threshold["mean_factor"], ["TARGET_CELL_COUNTS_ONLY"])

    threshold = RULE_THRESHOLDS["SCRIPT_TEMPLATE_REPETITION"]
    template_components = {"template_repeat_ratio": xv.get("template_repeat_ratio"),
                           "dominant_template_ratio": xv.get("dominant_template_ratio")}
    add("SCRIPT_TEMPLATE_REPETITION", [templates, scripts], template_components,
        (xv.get("template_repeat_ratio") or 0) >= threshold["template_repeat_ratio"] and
        (xv.get("dominant_template_ratio") or 0) >= threshold["dominant_template_ratio"], [])

    lv = lifecycle.values
    threshold = RULE_THRESHOLDS["RAPID_CELL_TURNOVER"]
    rapid_components = {"rapid_consumption_ratio": lv.get("rapid_consumption_ratio")}
    add("RAPID_CELL_TURNOVER", [lifecycle], rapid_components,
        (lv.get("rapid_consumption_ratio") or 0) >= threshold["rapid_consumption_ratio"], [])

    threshold = RULE_THRESHOLDS["PASS_THROUGH_CANDIDATE"]
    gross = (capacity.values.get("target_created_capacity") or 0) + (capacity.values.get("target_consumed_capacity") or 0)
    delta_ratio = abs(capacity.values.get("target_net_capacity_delta") or 0) / gross if gross else None
    pass_components = {"rapid_consumption_ratio": lv.get("rapid_consumption_ratio"),
                       "continuation_ratio": lineage.values.get("continuation_ratio"),
                       "inverse_capacity_delta_ratio": 1 - min(1, delta_ratio) if delta_ratio is not None else None}
    add("PASS_THROUGH_CANDIDATE", [lifecycle, lineage, capacity], pass_components,
        (lv.get("rapid_consumption_ratio") or 0) >= threshold["rapid_consumption_ratio"] and
        (lineage.values.get("continuation_ratio") or 0) >= threshold["continuation_ratio"] and
        delta_ratio is not None and delta_ratio <= threshold["maximum_capacity_delta_ratio"],
        ["CANDIDATE_ONLY", "NO_ECONOMIC_ROUTE_INFERENCE"])

    threshold = RULE_THRESHOLDS["STATE_MACHINE_ACTIVITY"]
    state_components = {"dominant_template_coverage": xv.get("dominant_template_coverage"),
                        "transition_repeat_ratio": xv.get("transition_repeat_ratio"),
                        "inverse_transition_entropy": 1 - (xv.get("template_transition_entropy") or 1)}
    add("STATE_MACHINE_ACTIVITY", [templates], state_components,
        len(observation.get("transactions", [])) >= threshold["minimum_transactions"] and
        (xv.get("dominant_template_count") or 999) <= threshold["maximum_dominant_templates"] and
        (xv.get("dominant_template_coverage") or 0) >= threshold["dominant_template_coverage"] and
        (xv.get("transition_repeat_ratio") or 0) >= threshold["transition_repeat_ratio"] and
        xv.get("template_transition_entropy") is not None and
        xv["template_transition_entropy"] <= threshold["maximum_transition_entropy"], [])

    threshold = RULE_THRESHOLDS["IRREGULAR_ACTIVITY"]
    irregular_components = {"inverse_periodicity_strength": 1 - (pv.get("periodicity_strength") or 0),
                            "gap_entropy": temporal.values.get("gap_entropy"),
                            "inverse_template_repeat_ratio": 1 - (xv.get("template_repeat_ratio") or 0)}
    add("IRREGULAR_ACTIVITY", [temporal, periodicity, templates], irregular_components,
        len(observation.get("transactions", [])) >= threshold["minimum_transactions"] and
        (pv.get("periodicity_strength") or 0) < threshold["maximum_periodicity_strength"] and
        (temporal.values.get("gap_entropy") or 0) >= threshold["gap_entropy"] and
        (xv.get("template_repeat_ratio") or 0) < threshold["maximum_template_repeat_ratio"], [])

    mixed_state = SupportState.SUPPORTED.value if len(positive) >= 2 else SupportState.INSUFFICIENT_EVIDENCE.value
    results.append(_rule("MIXED", mixed_state, min(1, len(positive) / 3) if positive else None,
                         ["MULTIPLE_INDEPENDENT_PATTERNS"] if len(positive) >= 2 else
                         ["FEWER_THAN_TWO_POSITIVE_PATTERNS"],
                         {"positive_pattern_count": len(positive), "positive_patterns": positive},
                         _hashes(observation)))
    return results
