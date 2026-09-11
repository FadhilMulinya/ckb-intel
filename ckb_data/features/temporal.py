from __future__ import annotations

import math
import statistics
from collections import Counter

from .base import FeatureResult, SupportState, observation_support

MIN_TEMPORAL_TRANSACTIONS = 5
MIN_PERIODICITY_TRANSACTIONS = 8


def _entropy(values: list[int], alphabet: int) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    raw = -sum((n / len(values)) * math.log2(n / len(values)) for n in counts.values())
    return raw / math.log2(alphabet) if alphabet > 1 else 0.0


def _cv(values: list[float]) -> float | None:
    mean = statistics.mean(values) if values else 0
    return statistics.pstdev(values) / mean if len(values) > 1 and mean else None


def extract(observation: dict) -> FeatureResult:
    txs = sorted((tx for tx in observation.get("transactions", [])
                  if tx.get("block_timestamp") is not None),
                 key=lambda tx: tx["block_timestamp"])
    timestamps = [tx["block_timestamp"] for tx in txs]
    support = observation_support({**observation, "transactions": txs},
                                  minimum_transactions=MIN_TEMPORAL_TRANSACTIONS)
    requirements = {"minimum_transactions": MIN_TEMPORAL_TRANSACTIONS,
                    "minimum_periodicity_transactions": MIN_PERIODICITY_TRANSACTIONS,
                    "requires_detail_complete": True}
    if len(timestamps) < MIN_TEMPORAL_TRANSACTIONS:
        return FeatureResult("temporal", SupportState.INSUFFICIENT_EVIDENCE,
                             {name: None for name in TEMPORAL_FEATURES}, requirements,
                             {"transactions": len(timestamps)})

    gaps = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    if len(gaps) < MIN_TEMPORAL_TRANSACTIONS - 1:
        return FeatureResult("temporal", SupportState.INSUFFICIENT_EVIDENCE,
                             {name: None for name in TEMPORAL_FEATURES}, requirements,
                             {"transactions": len(timestamps), "positive_intervals": len(gaps)})
    mean, median = statistics.mean(gaps), statistics.median(gaps)
    std = statistics.pstdev(gaps)
    repeated = sum(abs(gap - median) <= max(1.0, median * 0.05) for gap in gaps) / len(gaps)
    values = {
        "n_observed_transactions": len(timestamps),
        "interarrival_mean_seconds": mean,
        "interarrival_median_seconds": median,
        "interarrival_std_seconds": std,
        "interarrival_cv": _cv(gaps),
        "burstiness": (std - mean) / (std + mean) if std + mean else None,
        "active_hour_entropy": _entropy([(ts // 3600) % 24 for ts in timestamps], 24),
        "active_weekday_entropy": _entropy([(ts // 86400 + 4) % 7 for ts in timestamps], 7),
        "interval_repeat_ratio": repeated,
        "dominant_period_seconds": None,
        "periodicity_strength": None,
        "phase_stability": None,
    }
    if len(timestamps) >= MIN_PERIODICITY_TRANSACTIONS and median > 0:
        mad = statistics.median(abs(gap - median) for gap in gaps)
        angles = [2 * math.pi * ((ts - timestamps[0]) % median) / median for ts in timestamps]
        resultant = math.hypot(sum(math.cos(a) for a in angles),
                               sum(math.sin(a) for a in angles)) / len(angles)
        values.update(dominant_period_seconds=median,
                      periodicity_strength=math.exp(-mad / median),
                      phase_stability=resultant)
    return FeatureResult("temporal", support, values, requirements,
                         {"transactions": len(timestamps),
                          "supporting_transactions": [tx["tx_hash"] for tx in txs]})


TEMPORAL_FEATURES = [
    "n_observed_transactions", "interarrival_mean_seconds",
    "interarrival_median_seconds", "interarrival_std_seconds",
    "interarrival_cv", "burstiness", "active_hour_entropy",
    "active_weekday_entropy", "interval_repeat_ratio",
    "dominant_period_seconds", "periodicity_strength", "phase_stability",
]
