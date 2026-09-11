from __future__ import annotations

import math
import statistics

from .config import MINIMUM_SAMPLES, REPEAT_TOLERANCE
from .stats import cv, pearson, tolerant_clusters
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = [
    "dominant_period_seconds", "periodicity_strength", "phase_stability",
    "autocorrelation_peak_strength", "autocorrelation_peak_lag",
    "interval_cluster_concentration", "dominant_interval_cluster",
    "dominant_interval_cluster_ratio", "multi_period_candidate_count",
    "period_stability_score", "period_presence_count", "eligible_subwindow_count",
    "spectral_power", "spectral_peak_ratio",
]


def _baseline(timestamps: list[int]) -> tuple[list[int], dict]:
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    if not gaps:
        return gaps, {}
    median = statistics.median(gaps)
    mad = statistics.median(abs(gap - median) for gap in gaps)
    angles = [2 * math.pi * ((timestamp - timestamps[0]) % median) / median
              for timestamp in timestamps] if median else []
    phase = (math.hypot(sum(math.cos(angle) for angle in angles),
                        sum(math.sin(angle) for angle in angles)) / len(angles)) if angles else None
    return gaps, {"dominant_period_seconds": median,
                  "periodicity_strength": math.exp(-mad / median) if median else None,
                  "phase_stability": phase}


def _autocorrelation(gaps: list[int]) -> tuple[float | None, int | None]:
    candidates = []
    for lag in range(1, min(50, len(gaps) // 2) + 1):
        value = pearson(gaps[:-lag], gaps[lag:])
        if value is not None:
            candidates.append((value, lag))
    return max(candidates, default=(None, None), key=lambda item: item[0])


def extract(observation: dict) -> FeatureResultV2:
    timestamps = sorted(int(tx["block_timestamp"]) for tx in observation.get("transactions", [])
                        if tx.get("block_timestamp") is not None)
    minimum = MINIMUM_SAMPLES["periodicity"]
    requirements = {"minimum_transactions": minimum, "minimum_positive_gaps": minimum - 1,
                    "interval_cluster_tolerance": REPEAT_TOLERANCE,
                    "minimum_eligible_subwindows": 2,
                    "lomb_scargle": "NOT_IMPLEMENTED_OPTIONAL_DEPENDENCY"}
    gaps, baseline = _baseline(timestamps)
    if len(timestamps) < minimum or len(gaps) < minimum - 1:
        return empty_result("periodicity", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(gaps), FEATURES,
                            {"positive_gap_count": len(gaps)})
    clusters = tolerant_clusters(gaps)
    ordered_clusters = sorted(clusters, key=lambda cluster: (-len(cluster), statistics.median(cluster)))
    dominant = ordered_clusters[0]
    autocorrelation, autocorrelation_lag = _autocorrelation(gaps)
    start = observation.get("metadata", {}).get("window_start_timestamp") or timestamps[0]
    weekly_periods = []
    eligible = 0
    for week in range(4):
        lower, upper = start + week * 604800, start + (week + 1) * 604800
        subset = [timestamp for timestamp in timestamps if lower <= timestamp < upper]
        weekly_gaps, weekly = _baseline(subset)
        if len(weekly_gaps) >= 3:
            eligible += 1
            weekly_periods.append(weekly.get("dominant_period_seconds"))
    global_period = baseline["dominant_period_seconds"]
    present = [period for period in weekly_periods if period is not None and
               abs(period - global_period) <= max(1, global_period * .10)]
    stability = None
    if eligible >= 2:
        stability = (len(present) / eligible) * (1 / (1 + (cv(present) or 0)))
    values = {**baseline,
              "autocorrelation_peak_strength": autocorrelation,
              "autocorrelation_peak_lag": autocorrelation_lag,
              "interval_cluster_concentration": len(dominant) / len(gaps),
              "dominant_interval_cluster": statistics.median(dominant),
              "dominant_interval_cluster_ratio": len(dominant) / len(gaps),
              "multi_period_candidate_count": sum(len(cluster) >= 2 for cluster in clusters),
              "period_stability_score": stability,
              "period_presence_count": len(present),
              "eligible_subwindow_count": eligible,
              "spectral_power": None, "spectral_peak_ratio": None}
    support = family_support(observation, len(timestamps), minimum, require_details=True)
    return FeatureResultV2("periodicity", support, requirements, len(gaps),
                           {"timestamp_coverage": len(timestamps) / len(observation.get("transactions", []))},
                           values, {"positive_gaps_seconds": gaps,
                                    "interval_clusters": [{"median": statistics.median(cluster),
                                                           "count": len(cluster)}
                                                          for cluster in ordered_clusters],
                                    "weekly_periods": weekly_periods})

