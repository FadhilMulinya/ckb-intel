import math
from collections import Counter
from statistics import mean, median, pstdev

import numpy as np

import config
from cell_resolver import resolve_wallet_transactions


def _safe_div(a, b):
    return a / b if b else 0.0


def _cv(values):
    if not values or len(values) < 2:
        return 0.0
    m = mean(values)
    if m == 0:
        return 0.0
    return pstdev(values) / m


def _entropy(counter: Counter):
    total = sum(counter.values())
    if total == 0:
        return 0.0
    ent = 0.0
    for c in counter.values():
        p = c / total
        if p > 0:
            ent -= p * math.log2(p)
    return ent


def _burstiness(intervals):
    if len(intervals) < 2:
        return 0.0
    m = mean(intervals)
    s = pstdev(intervals)
    if (s + m) == 0:
        return 0.0
    return (s - m) / (s + m)


def _autocorr_periodicity(timestamps_s, window_days):
    """Bin activity hourly across the window, compute autocorrelation, return
    (dominant_period_hours, periodicity_strength in [0,1])."""
    if len(timestamps_s) < config.MIN_TX_FOR_PERIODICITY:
        return None, 0.0
    n_bins = window_days * 24
    t0 = min(timestamps_s)
    bins = np.zeros(n_bins)
    for t in timestamps_s:
        idx = int((t - t0) // 3600)
        if 0 <= idx < n_bins:
            bins[idx] += 1
    if bins.sum() == 0:
        return None, 0.0
    bins = bins - bins.mean()
    if np.all(bins == 0):
        return None, 0.0
    ac = np.correlate(bins, bins, mode="full")[n_bins - 1:]
    ac = ac / (ac[0] + 1e-9)
    search = ac[1:n_bins // 2] if n_bins > 3 else ac[1:]
    if len(search) == 0:
        return None, 0.0
    peak_lag = int(np.argmax(search)) + 1
    peak_val = float(search[peak_lag - 1])
    return peak_lag, max(0.0, min(1.0, peak_val))


def compute_wallet_features(raw_record: dict, address_info: dict = None, is_known_miner_address: bool = False):
    address = raw_record["address"]
    txs = resolve_wallet_transactions(raw_record)
    n_tx = len(txs)
    window_days = raw_record.get("window_days", config.OBSERVATION_WINDOW_DAYS)

    metadata = {
        "address": address,
        "window_days": window_days,
        "transactions_observed": n_tx,
        "pull_status": raw_record.get("status", "complete"),  # "complete" | "partial"
        "hit_max_cap": raw_record.get("hit_max_cap", False),
        "evidence_state": "OK" if n_tx >= config.MIN_TX_FOR_EVIDENCE else "INSUFFICIENT_EVIDENCE",
        "periodicity_evidence": n_tx >= config.MIN_TX_FOR_PERIODICITY,
    }

    feat = {}

    if n_tx == 0:
        feat.update({k: 0.0 for k in _ZERO_FEATURE_TEMPLATE})
        feat["is_inactive"] = 1.0
        feat["is_known_miner_address"] = float(is_known_miner_address)
        return feat, metadata

    feat["is_inactive"] = 0.0

    timestamps_s = [t["block_timestamp"] / 1000.0 for t in txs]
    intervals = [b - a for a, b in zip(timestamps_s, timestamps_s[1:])]
    feat["interarrival_mean_s"] = mean(intervals) if intervals else 0.0
    feat["interarrival_median_s"] = median(intervals) if intervals else 0.0
    feat["interarrival_std_s"] = pstdev(intervals) if len(intervals) > 1 else 0.0
    feat["interarrival_cv"] = _cv(intervals)
    feat["burstiness"] = _burstiness(intervals)

    hours = Counter(int((ts // 3600) % 24) for ts in timestamps_s)
    weekdays = Counter(int((ts // 86400) % 7) for ts in timestamps_s)
    feat["active_hour_entropy"] = _entropy(hours)
    feat["active_weekday_entropy"] = _entropy(weekdays)

    dominant_period, periodicity_strength = _autocorr_periodicity(timestamps_s, window_days)
    feat["dominant_period_hours"] = float(dominant_period or 0)
    feat["periodicity_strength"] = periodicity_strength

    interval_rounded = Counter(round(iv, -1) for iv in intervals)  # bucket to nearest 10s
    feat["interval_repeat_ratio"] = _safe_div(max(interval_rounded.values()) if interval_rounded else 0, len(intervals))

   
    in_cell_counts = [t["n_inputs"] for t in txs]
    out_cell_counts = [t["n_outputs"] for t in txs]
    feat["mean_input_cells"] = mean(in_cell_counts)
    feat["mean_output_cells"] = mean(out_cell_counts)
    feat["max_input_cells"] = max(in_cell_counts)
    feat["max_output_cells"] = max(out_cell_counts)
    feat["input_output_cell_ratio"] = _safe_div(mean(in_cell_counts), mean(out_cell_counts))

    single_to_single = sum(1 for t in txs if t["n_inputs"] == 1 and t["n_outputs"] == 1)
    fanout_tx = sum(1 for t in txs if t["target_input_cells"] and len(t["counterparty_output_addrs"]) >= 3)
    fanin_tx = sum(1 for t in txs if t["target_output_cells"] and len(t["counterparty_input_addrs"]) >= 3)
    many_to_many = sum(1 for t in txs if t["n_inputs"] >= 3 and t["n_outputs"] >= 3)
    feat["single_to_single_ratio"] = _safe_div(single_to_single, n_tx)
    feat["fanout_tx_ratio"] = _safe_div(fanout_tx, n_tx)
    feat["fanin_tx_ratio"] = _safe_div(fanin_tx, n_tx)
    feat["many_to_many_ratio"] = _safe_div(many_to_many, n_tx)

    topology_shapes = Counter((min(t["n_inputs"], 4), min(t["n_outputs"], 4)) for t in txs)
    feat["topology_entropy"] = _entropy(topology_shapes)
    feat["topology_repetition"] = _safe_div(max(topology_shapes.values()), n_tx)

   
    target_in_caps = [c["capacity_ckb"] for t in txs for c in t["target_input_cells"]]
    target_out_caps = [c["capacity_ckb"] for t in txs for c in t["target_output_cells"]]
    capacity_out_total = sum(target_in_caps)   # consumed BY target (target was spender)
    capacity_in_total = sum(target_out_caps)   # newly controlled by target
    feat["capacity_in_total"] = capacity_in_total
    feat["capacity_out_total"] = capacity_out_total
    feat["net_capacity_delta"] = capacity_in_total - capacity_out_total
    feat["capacity_turnover"] = capacity_in_total + capacity_out_total
    feat["median_input_capacity"] = median(target_in_caps) if target_in_caps else 0.0
    feat["median_output_capacity"] = median(target_out_caps) if target_out_caps else 0.0
    all_caps = target_in_caps + target_out_caps
    feat["capacity_cv"] = _cv(all_caps)

    cap_rounded = Counter(round(c, 0) for c in all_caps)
    feat["repeated_capacity_ratio"] = _safe_div(max(cap_rounded.values()) if cap_rounded else 0, len(all_caps) or 1)

    fragmentation_events = sum(1 for t in txs if len(t["target_input_cells"]) <= 1 and len(t["target_output_cells"]) >= 3)
    consolidation_events = sum(1 for t in txs if len(t["target_input_cells"]) >= 3 and len(t["target_output_cells"]) <= 1)
    feat["capacity_fragmentation"] = _safe_div(fragmentation_events, n_tx)
    feat["capacity_consolidation"] = _safe_div(consolidation_events, n_tx)

    created_index = {}  #
    for t in txs:
        for c in t["target_output_cells"]:
            created_index[(t["tx_hash"], c["index"])] = (t["block_timestamp"], t["block_number"])

    
    lifetimes, same_block = [], 0
    for tx in raw_record.get("transactions", []):
        for io in (tx.get("display_inputs") or []):
            if io.get("address_hash") != address:
                continue
            key = (io.get("generated_tx_hash"), int(io.get("cell_index", -1) or -1))
            created = created_index.get(key)
            if created:
                created_ts, created_block = created
                consumed_ts = int(tx.get("block_timestamp", 0) or 0)
                consumed_block = int(tx.get("block_number", 0) or 0)
                lifetimes.append((consumed_ts - created_ts) / 1000.0)
                if consumed_block == created_block:
                    same_block += 1

    if lifetimes:
        feat["cell_lifetime_mean_s"] = mean(lifetimes)
        feat["cell_lifetime_median_s"] = median(lifetimes)
        feat["cell_lifetime_cv"] = _cv(lifetimes)
        feat["short_lived_cell_ratio"] = _safe_div(sum(1 for l in lifetimes if l < 3600), len(lifetimes))
        feat["long_lived_cell_ratio"] = _safe_div(sum(1 for l in lifetimes if l > 7 * 86400), len(lifetimes))
        feat["same_block_spend_ratio"] = _safe_div(same_block, len(lifetimes))
        feat["lifecycle_resolved_ratio"] = _safe_div(len(lifetimes), len(target_in_caps) or 1)
    else:
        feat["cell_lifetime_mean_s"] = 0.0
        feat["cell_lifetime_median_s"] = 0.0
        feat["cell_lifetime_cv"] = 0.0
        feat["short_lived_cell_ratio"] = 0.0
        feat["long_lived_cell_ratio"] = 0.0
        feat["same_block_spend_ratio"] = 0.0
        feat["lifecycle_resolved_ratio"] = 0.0

    since_records = [c["since"] for t in txs for c in t["target_input_cells"] if c["since"]["present"]]
    total_target_inputs = len(target_in_caps) or 1
    feat["uses_since_ratio"] = _safe_div(len(since_records), total_target_inputs)
    feat["relative_since_ratio"] = _safe_div(sum(1 for s in since_records if s.get("relative")), total_target_inputs)
    feat["absolute_since_ratio"] = _safe_div(sum(1 for s in since_records if s.get("relative") is False), total_target_inputs)
    metric_counts = Counter(s.get("metric") for s in since_records)
    feat["since_block_ratio"] = _safe_div(metric_counts.get("block_number", 0), total_target_inputs)
    feat["since_epoch_ratio"] = _safe_div(metric_counts.get("epoch", 0), total_target_inputs)
    feat["since_timestamp_ratio"] = _safe_div(metric_counts.get("timestamp", 0), total_target_inputs)
    since_values = Counter(s.get("value") for s in since_records if s.get("value") is not None)
    feat["repeated_since_value_ratio"] = _safe_div(max(since_values.values()) if since_values else 0, len(since_records) or 1)

    
    all_target_cell_types = Counter(
        c["cell_type"] for t in txs for c in (t["target_input_cells"] + t["target_output_cells"])
    )
    total_target_cells = sum(all_target_cell_types.values()) or 1
    feat["type_script_diversity"] = len(all_target_cell_types)
    feat["dao_capacity_share"] = _safe_div(all_target_cell_types.get("dao", 0), total_target_cells)
    feat["udt_capacity_share"] = _safe_div(all_target_cell_types.get("udt", 0), total_target_cells)
    feat["nft_state_share"] = _safe_div(all_target_cell_types.get("nft_state", 0), total_target_cells)
    feat["dao_interaction_count"] = float(all_target_cell_types.get("dao", 0))

    all_counterparties_in = Counter()
    all_counterparties_out = Counter()
    for t in txs:
        for a in t["counterparty_input_addrs"]:
            all_counterparties_in[a] += 1
        for a in t["counterparty_output_addrs"]:
            all_counterparties_out[a] += 1
    feat["fanin_source_count"] = len(all_counterparties_in)
    feat["fanout_dest_count"] = len(all_counterparties_out)
    feat["fanin_source_entropy"] = _entropy(all_counterparties_in)
    feat["fanout_dest_entropy"] = _entropy(all_counterparties_out)
    both_sides = set(all_counterparties_in) & set(all_counterparties_out)
    feat["round_trip_partner_ratio"] = _safe_div(len(both_sides), len(set(all_counterparties_in) | set(all_counterparties_out)) or 1)
    feat["source_concentration"] = _safe_div(max(all_counterparties_in.values()) if all_counterparties_in else 0, sum(all_counterparties_in.values()) or 1)
    feat["dest_concentration"] = _safe_div(max(all_counterparties_out.values()) if all_counterparties_out else 0, sum(all_counterparties_out.values()) or 1)

    direct_cellbase_inputs = sum(
        1 for tx in raw_record.get("transactions", [])
        for io in (tx.get("display_inputs") or [])
        if io.get("address_hash") == address and io.get("from_cellbase")
    )
    feat["cellbase_reward_ratio"] = _safe_div(direct_cellbase_inputs, n_tx)
    feat["is_known_miner_address"] = float(is_known_miner_address)

    return feat, metadata


_ZERO_FEATURE_TEMPLATE = [
    "interarrival_mean_s", "interarrival_median_s", "interarrival_std_s", "interarrival_cv", "burstiness",
    "active_hour_entropy", "active_weekday_entropy", "dominant_period_hours", "periodicity_strength",
    "interval_repeat_ratio", "mean_input_cells", "mean_output_cells", "max_input_cells", "max_output_cells",
    "input_output_cell_ratio", "single_to_single_ratio", "fanout_tx_ratio", "fanin_tx_ratio",
    "many_to_many_ratio", "topology_entropy", "topology_repetition", "capacity_in_total", "capacity_out_total",
    "net_capacity_delta", "capacity_turnover", "median_input_capacity", "median_output_capacity", "capacity_cv",
    "repeated_capacity_ratio", "capacity_fragmentation", "capacity_consolidation", "cell_lifetime_mean_s",
    "cell_lifetime_median_s", "cell_lifetime_cv", "short_lived_cell_ratio", "long_lived_cell_ratio",
    "same_block_spend_ratio", "lifecycle_resolved_ratio", "uses_since_ratio", "relative_since_ratio",
    "absolute_since_ratio", "since_block_ratio", "since_epoch_ratio", "since_timestamp_ratio",
    "repeated_since_value_ratio", "type_script_diversity", "dao_capacity_share", "udt_capacity_share",
    "nft_state_share", "dao_interaction_count", "fanin_source_count", "fanout_dest_count",
    "fanin_source_entropy", "fanout_dest_entropy", "round_trip_partner_ratio", "source_concentration",
    "dest_concentration", "cellbase_reward_ratio",
]

FEATURE_COLUMNS = _ZERO_FEATURE_TEMPLATE + ["is_inactive", "is_known_miner_address"]
