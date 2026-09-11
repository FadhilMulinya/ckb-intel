from __future__ import annotations

import statistics
from collections import Counter

from .config import (BURST_GAP_SECONDS, BURST_MIN_TRANSACTIONS, MINIMUM_SAMPLES,
                     SESSION_GAP_SECONDS)
from .stats import (cv, duration_entropy, excess_kurtosis, normalized_entropy,
                    quantile, skewness)
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = [
    "transaction_count", "positive_gap_count", "interarrival_mean_seconds",
    "interarrival_median_seconds", "interarrival_std_seconds", "interarrival_cv",
    "interarrival_p10", "interarrival_p25", "interarrival_p75", "interarrival_p90",
    "interarrival_skewness", "interarrival_kurtosis", "gap_entropy",
    "activity_session_count", "mean_session_duration", "median_session_duration",
    "mean_transactions_per_session", "max_transactions_per_session", "burst_count",
    "mean_burst_size", "max_burst_size", "mean_burst_duration",
    "transactions_in_bursts_ratio", "hour_of_day_entropy", "weekday_entropy",
    "active_hour_concentration", "active_day_concentration",
]


def _groups(timestamps: list[int], maximum_gap: int, minimum_size: int = 1) -> list[list[int]]:
    if not timestamps:
        return []
    groups, current = [], [timestamps[0]]
    for timestamp in timestamps[1:]:
        if timestamp - current[-1] <= maximum_gap:
            current.append(timestamp)
        else:
            if len(current) >= minimum_size:
                groups.append(current)
            current = [timestamp]
    if len(current) >= minimum_size:
        groups.append(current)
    return groups


def extract(observation: dict) -> FeatureResultV2:
    txs = sorted((tx for tx in observation.get("transactions", [])
                  if tx.get("block_timestamp") is not None),
                 key=lambda tx: (tx["block_timestamp"], tx.get("transaction_index") or 0,
                                 tx.get("tx_hash") or ""))
    timestamps = [int(tx["block_timestamp"]) for tx in txs]
    minimum = MINIMUM_SAMPLES["temporal"]
    requirements = {"minimum_transactions": minimum,
                    "session_gap_seconds": SESSION_GAP_SECONDS,
                    "burst_gap_seconds": BURST_GAP_SECONDS,
                    "burst_minimum_transactions": BURST_MIN_TRANSACTIONS}
    if len(timestamps) < minimum:
        return empty_result("temporal", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(timestamps), FEATURES,
                            {"transaction_hashes": [tx.get("tx_hash") for tx in txs]},
                            {"timestamp_coverage": len(timestamps) / len(observation.get("transactions", []))
                             if observation.get("transactions") else None})
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    if len(gaps) < minimum - 1:
        return empty_result("temporal", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(timestamps), FEATURES,
                            {"positive_gap_count": len(gaps)})
    sessions = _groups(timestamps, SESSION_GAP_SECONDS)
    bursts = _groups(timestamps, BURST_GAP_SECONDS, BURST_MIN_TRANSACTIONS)
    session_durations = [group[-1] - group[0] for group in sessions]
    burst_durations = [group[-1] - group[0] for group in bursts]
    hour_counts = Counter((timestamp // 3600) % 24 for timestamp in timestamps)
    day_counts = Counter((timestamp // 86400 + 4) % 7 for timestamp in timestamps)
    values = {
        "transaction_count": len(timestamps), "positive_gap_count": len(gaps),
        "interarrival_mean_seconds": statistics.mean(gaps),
        "interarrival_median_seconds": statistics.median(gaps),
        "interarrival_std_seconds": statistics.pstdev(gaps), "interarrival_cv": cv(gaps),
        "interarrival_p10": quantile(gaps, .10), "interarrival_p25": quantile(gaps, .25),
        "interarrival_p75": quantile(gaps, .75), "interarrival_p90": quantile(gaps, .90),
        "interarrival_skewness": skewness(gaps),
        "interarrival_kurtosis": excess_kurtosis(gaps), "gap_entropy": duration_entropy(gaps),
        "activity_session_count": len(sessions),
        "mean_session_duration": statistics.mean(session_durations),
        "median_session_duration": statistics.median(session_durations),
        "mean_transactions_per_session": statistics.mean(map(len, sessions)),
        "max_transactions_per_session": max(map(len, sessions)), "burst_count": len(bursts),
        "mean_burst_size": statistics.mean(map(len, bursts)) if bursts else 0,
        "max_burst_size": max(map(len, bursts)) if bursts else 0,
        "mean_burst_duration": statistics.mean(burst_durations) if bursts else 0,
        "transactions_in_bursts_ratio": sum(map(len, bursts)) / len(timestamps),
        "hour_of_day_entropy": normalized_entropy([(ts // 3600) % 24 for ts in timestamps],
                                                   fixed_alphabet=24),
        "weekday_entropy": normalized_entropy([(ts // 86400 + 4) % 7 for ts in timestamps],
                                               fixed_alphabet=7),
        "active_hour_concentration": max(hour_counts.values()) / len(timestamps),
        "active_day_concentration": max(day_counts.values()) / len(timestamps),
    }
    timestamp_coverage = len(timestamps) / len(observation.get("transactions", []))
    support = family_support(observation, len(timestamps), minimum, require_details=True,
                             coverage_complete=timestamp_coverage == 1)
    return FeatureResultV2("temporal", support, requirements, len(timestamps),
                           {"timestamp_coverage": timestamp_coverage}, values,
                           {"transaction_hashes": [tx.get("tx_hash") for tx in txs],
                            "positive_gaps_seconds": gaps})

