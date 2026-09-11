from __future__ import annotations

import math
import statistics
from collections import Counter

from .config import DURATION_BINS_SECONDS, REPEAT_TOLERANCE


def quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def cv(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    return statistics.pstdev(values) / mean if mean else None


def skewness(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean, std = statistics.mean(values), statistics.pstdev(values)
    return sum(((value - mean) / std) ** 3 for value in values) / len(values) if std else 0.0


def excess_kurtosis(values: list[float]) -> float | None:
    if len(values) < 4:
        return None
    mean, std = statistics.mean(values), statistics.pstdev(values)
    return (sum(((value - mean) / std) ** 4 for value in values) / len(values) - 3.0) if std else 0.0


def entropy_from_counts(counts) -> float:
    counts = [count for count in counts if count]
    total = sum(counts)
    return -sum((count / total) * math.log2(count / total) for count in counts) if total else 0.0


def normalized_entropy(values: list, *, fixed_alphabet: int | None = None) -> float | None:
    if not values:
        return None
    counts = Counter(values)
    alphabet = fixed_alphabet or len(counts)
    denominator = math.log2(alphabet) if alphabet > 1 else 0.0
    return entropy_from_counts(counts.values()) / denominator if denominator else 0.0


def duration_bin(value: float) -> int:
    for index, boundary in enumerate(DURATION_BINS_SECONDS):
        if value <= boundary:
            return index
    return len(DURATION_BINS_SECONDS)


def duration_entropy(values: list[float]) -> float | None:
    return normalized_entropy([duration_bin(value) for value in values],
                              fixed_alphabet=len(DURATION_BINS_SECONDS) + 1)


def repeat_ratio(values: list[float], tolerance: float = REPEAT_TOLERANCE) -> float | None:
    if not values:
        return None
    clusters: list[list[float]] = []
    for value in sorted(values):
        match = next((cluster for cluster in clusters
                      if abs(value - statistics.median(cluster)) <=
                      max(1.0, abs(statistics.median(cluster)) * tolerance)), None)
        if match is None:
            clusters.append([value])
        else:
            match.append(value)
    repeated = sum(len(cluster) for cluster in clusters if len(cluster) > 1)
    return repeated / len(values)


def tolerant_clusters(values: list[float], tolerance: float = REPEAT_TOLERANCE) -> list[list[float]]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        for cluster in clusters:
            representative = statistics.median(cluster)
            if abs(value - representative) <= max(1.0, abs(representative) * tolerance):
                cluster.append(value)
                break
        else:
            clusters.append([value])
    return clusters


def transition_entropy(values: list) -> float | None:
    if len(values) < 2:
        return None
    transitions = list(zip(values, values[1:]))
    return normalized_entropy(transitions)


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    lm, rm = statistics.mean(left), statistics.mean(right)
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - lm) ** 2 for a in left) *
                            sum((b - rm) ** 2 for b in right))
    return numerator / denominator if denominator else None
