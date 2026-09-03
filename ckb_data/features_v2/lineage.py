from __future__ import annotations

from collections import Counter, defaultdict, deque

from .config import MINIMUM_SAMPLES
from .stats import normalized_entropy
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = ["lineage_depth", "branch_count", "merge_count", "split_count",
            "continuation_count", "continuation_ratio", "lineage_repetition"]


def extract(observation: dict) -> FeatureResultV2:
    txs = observation.get("transactions", [])
    minimum = MINIMUM_SAMPLES["lineage"]
    requirements = {"minimum_observable_transitions": minimum,
                    "representation": "CELL_TRANSACTION_HYPERGRAPH",
                    "pairwise_route_attribution": "NOT_ESTABLISHED"}
    tx_by_hash = {tx.get("tx_hash"): tx for tx in txs}
    spend_by_outpoint = {}
    for tx in txs:
        for cell in tx.get("inputs", []):
            point = (cell.get("previous_tx_hash"), cell.get("previous_output_index"))
            if all(value is not None for value in point):
                spend_by_outpoint[point] = tx.get("tx_hash")
    edges, signatures, continuation = [], [], 0
    adjacency = defaultdict(set)
    merge_count = split_count = branch_count = 0
    for tx in txs:
        inputs, outputs = tx.get("inputs", []), tx.get("outputs", [])
        input_points = [(cell.get("previous_tx_hash"), cell.get("previous_output_index"))
                        for cell in inputs if cell.get("previous_tx_hash") is not None]
        output_points = [(tx.get("tx_hash"), cell.get("output_index")) for cell in outputs]
        if len(input_points) > 1:
            merge_count += 1
        if len(output_points) > 1:
            split_count += 1; branch_count += len(output_points) - 1
        tx_node = ("TX", tx.get("tx_hash"))
        for source in input_points:
            edges.append({"from_cell": source, "consuming_tx": tx.get("tx_hash")})
            adjacency[("CELL",) + source].add(tx_node)
        for target in output_points:
            edges.append({"creating_tx": tx.get("tx_hash"), "to_cell": target})
            adjacency[tx_node].add(("CELL",) + target)
        input_types = {(cell.get("resolved_type_script_hash"),
                        cell.get("resolved_lock_script_hash")) for cell in inputs
                       if cell.get("target_controls_input")}
        output_types = {(cell.get("type_script_hash"), cell.get("lock_script_hash")) for cell in outputs
                        if cell.get("target_controls_output")}
        is_continuation = bool(input_types & output_types)
        continuation += is_continuation
        signatures.append((len(input_points), len(output_points), is_continuation))
    if len(edges) < minimum:
        return empty_result("lineage", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(edges), FEATURES,
                            {"observable_edges": len(edges)})
    memo = {}
    def depth(node, visiting=frozenset()):
        if node in memo: return memo[node]
        if node in visiting: return 0
        value = max(((1 if child[0] == "TX" else 0) + depth(child, visiting | {node})
                     for child in adjacency.get(node, ())), default=0)
        memo[node] = value; return value
    lineage_depth = max((depth(node) for node in adjacency), default=0)
    counts = Counter(signatures)
    values = {"lineage_depth": lineage_depth, "branch_count": branch_count,
              "merge_count": merge_count, "split_count": split_count,
              "continuation_count": continuation,
              "continuation_ratio": continuation / len(txs) if txs else None,
              "lineage_repetition": sum(count for count in counts.values() if count > 1) /
                                    len(signatures) if signatures else None}
    complete = all(cell.get("previous_tx_hash") is not None
                   for tx in txs for cell in tx.get("inputs", [])
                   if cell.get("resolution_status") != "not_applicable")
    support = family_support(observation, len(edges), minimum, require_inputs=True,
                             coverage_complete=complete)
    return FeatureResultV2("lineage", support, requirements, len(edges),
                           {"observable_input_outpoint_ratio":
                            sum(cell.get("previous_tx_hash") is not None for tx in txs
                                for cell in tx.get("inputs", [])) /
                            max(1, sum(len(tx.get("inputs", [])) for tx in txs))}, values,
                           {"lineage_edges": edges[:1000], "lineage_edge_count": len(edges)})
