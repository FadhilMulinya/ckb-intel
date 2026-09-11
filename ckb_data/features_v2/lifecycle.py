from __future__ import annotations

import statistics

from .config import (LONG_CELL_SECONDS, MINIMUM_SAMPLES, RAPID_CELL_SECONDS,
                     SHORT_CELL_SECONDS)
from .stats import cv, duration_entropy, quantile, repeat_ratio
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = [
    "observed_cell_count", "consumed_cell_count", "right_censored_cell_count",
    "mean_cell_lifetime_seconds", "median_cell_lifetime_seconds", "cell_lifetime_std",
    "cell_lifetime_cv", "cell_lifetime_p25", "cell_lifetime_p75", "cell_lifetime_p90",
    "mean_cell_lifetime_blocks", "median_cell_lifetime_blocks", "short_lived_cell_ratio",
    "long_lived_cell_ratio", "rapid_consumption_ratio", "same_block_consumption_ratio",
    "cell_lifetime_entropy", "cell_lifetime_repeat_ratio",
]


def extract(observation: dict) -> FeatureResultV2:
    records = observation.get("lifecycle_records", [])
    observed = observation.get("observed_target_cells", [])
    censored = observation.get("right_censored_target_cells", [])
    minimum = MINIMUM_SAMPLES["lifecycle"]
    requirements = {"minimum_resolved_consumed_cells": minimum,
                    "rapid_cell_seconds": RAPID_CELL_SECONDS,
                    "short_cell_seconds": SHORT_CELL_SECONDS,
                    "long_cell_seconds": LONG_CELL_SECONDS,
                    "consumption_must_be_inside_window": True}
    valid = [row for row in records if row.get("cell_lifetime_seconds") is not None and
             row["cell_lifetime_seconds"] >= 0 and row.get("cell_lifetime_blocks") is not None and
             row["cell_lifetime_blocks"] >= 0]
    if len(valid) < minimum:
        return empty_result("lifecycle", SupportState.INSUFFICIENT_EVIDENCE,
                            requirements, len(valid), FEATURES,
                            {"lifecycles": valid, "right_censored_outpoints": censored},
                            {"established_lifecycle_ratio": len(valid) / len(observed) if observed else None})
    seconds = [row["cell_lifetime_seconds"] for row in valid]
    blocks = [row["cell_lifetime_blocks"] for row in valid]
    values = {
        "observed_cell_count": len(observed), "consumed_cell_count": len(valid),
        "right_censored_cell_count": len(censored),
        "mean_cell_lifetime_seconds": statistics.mean(seconds),
        "median_cell_lifetime_seconds": statistics.median(seconds),
        "cell_lifetime_std": statistics.pstdev(seconds), "cell_lifetime_cv": cv(seconds),
        "cell_lifetime_p25": quantile(seconds, .25), "cell_lifetime_p75": quantile(seconds, .75),
        "cell_lifetime_p90": quantile(seconds, .90),
        "mean_cell_lifetime_blocks": statistics.mean(blocks),
        "median_cell_lifetime_blocks": statistics.median(blocks),
        "short_lived_cell_ratio": sum(value <= SHORT_CELL_SECONDS for value in seconds) / len(seconds),
        "long_lived_cell_ratio": sum(value >= LONG_CELL_SECONDS for value in seconds) / len(seconds),
        "rapid_consumption_ratio": sum(value <= RAPID_CELL_SECONDS for value in seconds) / len(seconds),
        "same_block_consumption_ratio": sum(value == 0 for value in blocks) / len(blocks),
        "cell_lifetime_entropy": duration_entropy(seconds),
        "cell_lifetime_repeat_ratio": repeat_ratio(seconds),
    }
    coverage = len(valid) / len(observed) if observed else None
    support = family_support(observation, len(valid), minimum, require_inputs=True,
                             coverage_complete=not any(row.get("unresolved") for row in records))
    return FeatureResultV2("lifecycle", support, requirements, len(valid),
                           {"established_lifecycle_ratio": coverage,
                            "right_censored_count": len(censored)}, values,
                           {"lifecycles": valid, "right_censored_outpoints": censored})

