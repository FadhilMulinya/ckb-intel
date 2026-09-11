#!/usr/bin/env python3
"""Validate the frozen V2 feature space without collection, imputation, or ML."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from features_v2.periodicity import _baseline
from features_v2.stats import normalized_entropy, pearson, quantile, repeat_ratio

ROOT = Path(__file__).resolve().parent
V2_DIR = ROOT / "feature_engineering_v2"
OUT_DIR = ROOT / "feature_validation"
DB_PATH = ROOT / "ckb_data_v2" / "ckb_explorer.sqlite"

ANALYSIS_VERSION = "ckb-feature-validation-v1"
CONFIG = {
    "analysis_version": ANALYSIS_VERSION,
    "population_size": 1172,
    "sparse_missing_ratio": 0.60,
    "very_sparse_missing_ratio": 0.90,
    "minimum_non_missing": 30,
    "near_constant_mode_ratio": 0.99,
    "minimum_correlation_overlap": 50,
    "minimum_activity_overlap": 30,
    "strong_correlation": 0.90,
    "near_duplicate_correlation": 0.95,
    "moderate_activity_dependence": 0.50,
    "high_activity_dependence": 0.80,
    "high_confidence_max_missing_ratio": 0.60,
    "high_confidence_minimum_non_missing": 300,
    "outlier_iqr_multiplier": 3.0,
    "coverage_thresholds": [0.20, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90],
    "weekly_window_seconds": 604800,
    "weekly_subwindows": 4,
    "weekly_coverage_note": "Four fixed seven-day windows cover days 1-28; days 29-30 are excluded from stability only.",
    "primary_matrix_exclusions": ["rule scores", "typed assets without supported observations",
                                    "explicit activity-volume diagnostics"],
}

FAMILIES = ("temporal", "periodicity", "topology", "templates", "lifecycle",
            "scripts", "typed_assets", "capacity", "lineage", "cross_feature")
CORE_FAMILIES = {"temporal", "topology", "templates", "scripts", "capacity", "lineage", "lifecycle"}
ACTIVITY_PREDICTORS = {"temporal__transaction_count", "lifecycle__observed_cell_count"}
COUNT_TOKENS = ("count", "depth", "lag")


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value):
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    result = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2
        for original, _ in ordered[index:end]:
            result[original] = rank
        index = end
    return result


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(ranks(left), ranks(right)) if len(left) == len(right) else None


def paired(rows: list[dict], left: str, right: str) -> tuple[list[float], list[float]]:
    pairs = [(number(row.get(left)), number(row.get(right))) for row in rows]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    return [a for a, _ in pairs], [b for _, b in pairs]


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def load_inputs() -> tuple[list[dict], list[str], list[dict], dict, dict]:
    canonical_path = V2_DIR / "wallet_behaviour_features_v2.csv"
    ml_path = V2_DIR / "wallet_behaviour_features_v2_ml.csv"
    with canonical_path.open() as handle:
        canonical = list(csv.DictReader(handle))
    with ml_path.open() as handle:
        reader = csv.DictReader(handle); predictors = list(reader.fieldnames or [])
    evidence = [json.loads(line) for line in
                (V2_DIR / "wallet_behaviour_features_v2_evidence.jsonl").read_text().splitlines()]
    definitions = json.loads((V2_DIR / "feature_definitions_v2.json").read_text())
    contract = json.loads((V2_DIR / "dataset_v1_snapshot/dataset_contract_v1.json").read_text())
    if len(canonical) != CONFIG["population_size"] or len(evidence) != CONFIG["population_size"]:
        raise RuntimeError("frozen population alignment failed")
    if contract["manifest_hash"] != "6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe":
        raise RuntimeError("frozen manifest changed")
    return canonical, predictors, evidence, definitions, contract


def family_of(predictor: str) -> str:
    prefix = predictor.split("__", 1)[0]
    return prefix if prefix in FAMILIES else "cross_feature"


def feature_name(predictor: str) -> str:
    return predictor.split("__", 1)[1] if "__" in predictor else predictor


def unit_for(name: str) -> str:
    lower = feature_name(name).lower()
    if "capacity" in lower and not any(token in lower for token in ("ratio", "entropy", "cv", "count")):
        return "shannon"
    if "lifetime_blocks" in lower:
        return "blocks"
    if any(token in lower for token in ("seconds", "duration")):
        return "seconds"
    if "entropy" in lower:
        return "normalized_entropy"
    if "cv" in lower:
        return "coefficient"
    if ratio_like(lower):
        return "ratio"
    if any(token in lower for token in COUNT_TOKENS):
        return "count"
    if "skewness" in lower or "kurtosis" in lower:
        return "shape_statistic"
    return "numeric"


def ratio_like(name: str) -> bool:
    return name.endswith(("_ratio", "_strength", "_stability", "_concentration",
                          "_coverage", "_score", "_support", "_repetition"))


def specificity_for(family: str) -> str:
    if family in {"lifecycle", "topology", "lineage", "scripts", "templates", "capacity", "typed_assets"}:
        return "STRONGLY_CKB_NATIVE"
    if family == "periodicity":
        return "WEAKLY_CKB_SPECIFIC"
    return "GENERIC_ACCOUNT_LIKE"


def transform_for(name: str, audit: dict) -> tuple[str, str]:
    unit = unit_for(name)
    if unit == "ratio" or unit == "normalized_entropy":
        return "NONE_OR_STANDARD_SCALER", "Bounded dimensionless value; preserve its domain."
    if unit in {"shannon", "seconds", "blocks", "count"}:
        return "LOG1P_THEN_ROBUST_SCALER", "Non-negative magnitude/count is potentially heavy-tailed."
    if audit.get("heavy_tail"):
        return "ROBUST_SCALER", "Observed distribution is heavy-tailed; avoid mean-sensitive scaling."
    return "STANDARD_SCALER", "Unbounded or shape statistic on a moderate numerical scale."


def theoretical_domain(predictor: str) -> tuple[float | None, float | None, str]:
    name = feature_name(predictor).lower()
    if predictor.startswith("rule__"):
        return 0.0, 1.0, "rule score"
    if "autocorrelation_peak_strength" in name:
        return -1.0, 1.0, "correlation"
    if any(token in name for token in ("skewness", "kurtosis", "net_capacity_delta", "net_token_delta")):
        return None, None, "signed statistic"
    if "entropy" in name:
        return 0.0, 1.0, "normalized entropy"
    if ratio_like(name):
        return 0.0, 1.0, "bounded ratio"
    if "cv" in name:
        return 0.0, None, "non-negative coefficient of variation"
    if any(token in name for token in COUNT_TOKENS) or any(token in name for token in
            ("capacity", "seconds", "duration", "period", "interarrival", "factor", "mean", "median", "std", "p10", "p25", "p75", "p90")):
        return 0.0, None, "non-negative magnitude"
    return None, None, "unrestricted numeric"


def predictor_definition(predictor: str, definitions: dict) -> dict:
    family = family_of(predictor)
    name = feature_name(predictor)
    if family == "cross_feature":
        rule = name.replace("__score", "").replace("_", " ").title()
        definition = f"Support-qualified composite score for the {rule} descriptive rule."
        requirement = "All feature families used by the rule must be support-qualified."
        limitation = "Hand-authored rule output; excluded from every primary exploratory matrix."
        why = "Useful only as a secondary comparison against structures learned from raw features."
    else:
        family_definition = definitions[family]
        label = name.replace("_", " ")
        definition = f"{label.capitalize()} calculated by the {family} V2 extractor."
        requirement = json.dumps(family_definition.get("sample_universe"), sort_keys=True)
        limitation = ("Missing values mean insufficient support or unavailable evidence; they do not mean zero behaviour. "
                      + family_definition.get("method", ""))
        why = {
            "temporal": "Describes timing regularity, concentration, sessions, and bursts.",
            "periodicity": "Distinguishes repeated execution rhythms from irregular timing.",
            "topology": "Captures CKB Cell fan-in, fan-out, fragmentation, and consolidation structure.",
            "templates": "Measures recurrence of CKB-native transaction structures without wallet identity.",
            "lifecycle": "Describes how long controlled Cells live before consumption.",
            "scripts": "Measures reuse and diversity of CKB lock/type scripts.",
            "typed_assets": "Describes verified xUDT Cell and token-amount structure when raw payloads exist.",
            "capacity": "Measures Shannon-capacity structure, repetition, and controlled capacity balance.",
            "lineage": "Measures Cell-to-transaction-to-Cell hypergraph structure and continuation.",
        }[family]
    low, high, domain = theoretical_domain(predictor)
    return {"predictor": predictor, "family": family, "definition": definition,
            "support_requirement": requirement, "unit": unit_for(predictor),
            "missing_semantics": "NOT_SUPPORTED_OR_NOT_OBSERVED",
            "why_it_may_matter": why, "ckb_native_classification": specificity_for(family),
            "known_limitations": limitation, "theoretical_domain": domain,
            "theoretical_min": low, "theoretical_max": high}


def predictor_audit(rows: list[dict], predictors: list[str], definitions: dict) -> tuple[list[dict], list[dict]]:
    audits, registry = [], []
    for predictor in predictors:
        values = [value for row in rows if (value := number(row.get(predictor))) is not None]
        missing = len(rows) - len(values)
        counts = Counter(values)
        low, high, domain = theoretical_domain(predictor)
        impossible = sum((low is not None and value < low - 1e-12) or
                         (high is not None and value > high + 1e-12) for value in values)
        if values:
            stats = {"mean": statistics.mean(values), "median": statistics.median(values),
                     "std": statistics.pstdev(values), "min": min(values), "max": max(values),
                     **{f"p{int(q * 100):02d}": quantile(values, q)
                        for q in (.01, .05, .10, .25, .75, .90, .95, .99)}}
            mode_ratio = counts.most_common(1)[0][1] / len(values)
            median = abs(stats["median"])
            heavy_tail = abs(stats["p99"]) > 10 * max(median, 1e-12) and abs(stats["p99"]) > 1
        else:
            stats = {key: None for key in ("mean", "median", "std", "min", "max",
                                            "p01", "p05", "p10", "p25", "p75", "p90", "p95", "p99")}
            mode_ratio, heavy_tail = None, False
        missing_ratio = missing / len(rows)
        if impossible:
            classification = "SUSPICIOUS"
        elif values and len(counts) == 1:
            classification = "CONSTANT"
        elif values and len(values) >= CONFIG["minimum_non_missing"] and mode_ratio >= CONFIG["near_constant_mode_ratio"]:
            classification = "NEAR_CONSTANT"
        elif missing_ratio >= CONFIG["very_sparse_missing_ratio"] or len(values) < CONFIG["minimum_non_missing"]:
            classification = "VERY_SPARSE"
        elif missing_ratio >= CONFIG["sparse_missing_ratio"]:
            classification = "SPARSE"
        else:
            classification = "USABLE"
        audit = {"predictor": predictor, "family": family_of(predictor),
                 "non_missing_count": len(values), "missing_count": missing,
                 "missing_ratio": missing_ratio, "unique_value_count": len(counts),
                 "mode_ratio": mode_ratio, "classification": classification,
                 "impossible_value_count": impossible, "heavy_tail": heavy_tail,
                 "theoretical_domain": domain, **stats}
        transform, reason = transform_for(predictor, audit)
        audit.update(recommended_transform=transform, transformation_reason=reason)
        entry = predictor_definition(predictor, definitions)
        entry.update(recommended_transform=transform, transformation_reason=reason,
                     audit_classification=classification)
        audits.append(audit); registry.append(entry)
    return audits, registry


def load_activity_diagnostics() -> dict[str, dict]:
    conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
    query = """
        WITH input_counts AS (
            SELECT tx_hash, COUNT(*) AS input_count FROM transaction_inputs GROUP BY tx_hash
        ), output_counts AS (
            SELECT creating_tx_hash AS tx_hash, COUNT(*) AS output_count FROM cells GROUP BY creating_tx_hash
        )
        SELECT wo.address,
               COUNT(wtp.tx_hash) AS transaction_count,
               COALESCE(SUM(ic.input_count), 0) AS input_count,
               COALESCE(SUM(oc.output_count), 0) AS output_count,
               COALESCE(SUM(wtp.controlled_input_count + wtp.controlled_output_count), 0) AS observed_cell_count
        FROM wallet_observations wo
        LEFT JOIN wallet_transaction_participation wtp ON wtp.observation_id = wo.observation_id
        LEFT JOIN input_counts ic ON ic.tx_hash = wtp.tx_hash
        LEFT JOIN output_counts oc ON oc.tx_hash = wtp.tx_hash
        WHERE wo.window_start_timestamp = 1785542400 AND wo.window_end_timestamp = 1788134400
        GROUP BY wo.address
    """
    diagnostics = {row[0]: {"transaction_count": row[1], "input_count": row[2],
                             "output_count": row[3], "observed_cell_count": row[4]}
                   for row in conn.execute(query)}
    conn.close()
    return diagnostics


def missingness_analysis(rows: list[dict], predictors: list[str]) -> tuple[list[dict], dict]:
    wallet_rows, patterns = [], Counter()
    family_predictors = {family: [p for p in predictors if family_of(p) == family]
                         for family in FAMILIES}
    for row in rows:
        available = sum(number(row.get(predictor)) is not None for predictor in predictors)
        supported = [family for family in FAMILIES if family != "cross_feature" and
                     row.get(f"{family}_support") in {"SUPPORTED", "PARTIAL"}]
        pattern = tuple(supported)
        patterns[pattern] += 1
        wallet_rows.append({"wallet": row["wallet"], "collection_state": row["collection_state"],
                            "available_predictor_count": available,
                            "missing_predictor_count": len(predictors) - available,
                            "feature_coverage_ratio": available / len(predictors),
                            "supported_feature_family_count": len(supported),
                            "supported_feature_families": "+".join(supported) or "NONE",
                            **{f"{family}_available_count": sum(number(row.get(p)) is not None
                                                               for p in family_predictors[family])
                               for family in family_predictors}})
    coverage = {f"at_least_{int(threshold * 100)}pct":
                sum(row["feature_coverage_ratio"] >= threshold for row in wallet_rows)
                for threshold in CONFIG["coverage_thresholds"]}
    common = [{"families": list(pattern), "wallet_count": count,
               "pattern": "+".join(pattern) or "NONE"}
              for pattern, count in patterns.most_common()]
    cohort_labels = Counter()
    for row in wallet_rows:
        families = set(row["supported_feature_families"].split("+"))
        if row["feature_coverage_ratio"] >= .70 and row["supported_feature_family_count"] >= 6:
            label = "HIGH_INFORMATION"
        elif {"topology", "templates"}.issubset(families):
            label = "TRANSACTION_STRUCTURE"
        elif ({"scripts", "capacity"} & families) and "temporal" not in families:
            label = "SCRIPT_CAPACITY_ONLY"
        else:
            label = "VERY_LOW_ACTIVITY_OR_SUPPORT"
        row["data_support_cohort"] = label; cohort_labels[label] += 1
    summary = {"predictor_count": len(predictors), "coverage_threshold_counts": coverage,
               "common_support_patterns": common, "data_support_cohorts": dict(cohort_labels),
               "semantic_warning": "These are observation-support cohorts, not behavioural labels."}
    return wallet_rows, summary


def activity_leakage(rows: list[dict], predictors: list[str], diagnostics: dict[str, dict]) -> list[dict]:
    metrics = ("transaction_count", "observed_cell_count", "input_count", "output_count")
    output = []
    for predictor in predictors:
        result = {"predictor": predictor, "family": family_of(predictor)}
        maximum = 0.0
        for metric in metrics:
            pairs = [(number(row.get(predictor)), number(diagnostics.get(row["wallet"], {}).get(metric)))
                     for row in rows]
            pairs = [(left, right) for left, right in pairs if left is not None and right is not None]
            left, right = [a for a, _ in pairs], [b for _, b in pairs]
            p = pearson(left, right) if len(pairs) >= CONFIG["minimum_activity_overlap"] else None
            s = spearman(left, right) if len(pairs) >= CONFIG["minimum_activity_overlap"] else None
            result.update({f"{metric}_overlap": len(pairs), f"{metric}_pearson": p,
                           f"{metric}_spearman": s})
            if s is not None:
                maximum = max(maximum, abs(s))
        result["maximum_absolute_spearman"] = maximum
        result["activity_dependence"] = ("HIGH_ACTIVITY_DEPENDENCE" if maximum >= CONFIG["high_activity_dependence"]
                                         else "MODERATE_ACTIVITY_DEPENDENCE" if maximum >= CONFIG["moderate_activity_dependence"]
                                         else "LOW_ACTIVITY_DEPENDENCE")
        output.append(result)
    return output


class UnionFind:
    def __init__(self, names: list[str]):
        self.parent = {name: name for name in names}

    def find(self, name: str) -> str:
        while self.parent[name] != name:
            self.parent[name] = self.parent[self.parent[name]]
            name = self.parent[name]
        return name

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def redundancy_analysis(rows: list[dict], predictors: list[str]) -> tuple[list[dict], list[dict], dict]:
    pairs, union = [], UnionFind(predictors)
    family_summary = defaultdict(lambda: {"eligible_pairs": 0, "strong_pairs": 0,
                                           "near_duplicate_pairs": 0, "absolute_spearman": []})
    for index, left_name in enumerate(predictors):
        for right_name in predictors[index + 1:]:
            left, right = paired(rows, left_name, right_name)
            if len(left) < CONFIG["minimum_correlation_overlap"]:
                continue
            p, s = pearson(left, right), spearman(left, right)
            family_pair = "|".join(sorted((family_of(left_name), family_of(right_name))))
            family_summary[family_pair]["eligible_pairs"] += 1
            if s is not None:
                family_summary[family_pair]["absolute_spearman"].append(abs(s))
            maximum = max(abs(p or 0), abs(s or 0))
            if maximum < CONFIG["strong_correlation"]:
                continue
            recommendation = "KEEP_ONE" if maximum >= CONFIG["near_duplicate_correlation"] else "REVIEW"
            if recommendation == "KEEP_ONE":
                union.union(left_name, right_name)
                family_summary[family_pair]["near_duplicate_pairs"] += 1
            family_summary[family_pair]["strong_pairs"] += 1
            pairs.append({"left": left_name, "right": right_name,
                          "left_family": family_of(left_name), "right_family": family_of(right_name),
                          "pairwise_overlap_count": len(left), "pearson": p, "spearman": s,
                          "recommendation": recommendation})
    grouped = defaultdict(list)
    for name in predictors:
        grouped[union.find(name)].append(name)
    groups = [{"group_id": index + 1, "predictors": sorted(names)}
              for index, names in enumerate(sorted((names for names in grouped.values() if len(names) > 1),
                                                   key=lambda names: names[0]))]
    family = {}
    for key, values in family_summary.items():
        correlations = values.pop("absolute_spearman")
        values["median_absolute_spearman"] = statistics.median(correlations) if correlations else None
        values["distinct_information_assessment"] = (
            "REVIEW_OVERLAP" if values["near_duplicate_pairs"] else "DISTINCT_AT_CURRENT_THRESHOLD")
        family[key] = values
    return sorted(pairs, key=lambda row: (-max(abs(row["pearson"] or 0), abs(row["spearman"] or 0)),
                                          row["left"], row["right"])), groups, family


def compact_evidence(item: dict, family: str) -> dict:
    if family == "cross_feature":
        return {}
    result = item["features"].get(family, {})
    evidence = result.get("evidence") or {}
    hashes = []
    if isinstance(evidence.get("transaction_hashes"), list):
        hashes = evidence["transaction_hashes"]
    elif isinstance(evidence.get("transaction_templates"), dict):
        hashes = list(evidence["transaction_templates"])
    elif isinstance(evidence.get("transactions_detail"), list):
        hashes = [row.get("tx_hash") for row in evidence["transactions_detail"]]
    elif isinstance(evidence.get("lifecycles"), list):
        hashes = [row.get("consuming_tx_hash") for row in evidence["lifecycles"]]
    return {"support_state": result.get("support_state"), "sample_count": result.get("sample_count"),
            "coverage": result.get("coverage"), "supporting_transaction_hashes":
            [value for value in hashes if value][:10], "evidence_fields": sorted(evidence)}


def distribution_issues(rows: list[dict], predictors: list[str], audits: list[dict],
                        evidence: list[dict]) -> list[dict]:
    evidence_by_wallet = {item["wallet"]: item for item in evidence}
    audit_by = {row["predictor"]: row for row in audits}
    issues = []
    for predictor in predictors:
        values = [(row["wallet"], number(row.get(predictor))) for row in rows]
        values = [(wallet, value) for wallet, value in values if value is not None]
        if not values:
            continue
        audit = audit_by[predictor]
        q25, q75 = audit["p25"], audit["p75"]
        iqr = q75 - q25 if q25 is not None and q75 is not None else 0
        low, high, _ = theoretical_domain(predictor)
        candidates = []
        for wallet, value in values:
            impossible = ((low is not None and value < low - 1e-12) or
                          (high is not None and value > high + 1e-12))
            extreme = bool(iqr and (value < q25 - CONFIG["outlier_iqr_multiplier"] * iqr or
                                    value > q75 + CONFIG["outlier_iqr_multiplier"] * iqr))
            if impossible or extreme:
                distance = max(abs(value - q25), abs(value - q75)) / iqr if iqr else abs(value)
                candidates.append((impossible, distance, wallet, value))
        for impossible, _, wallet, value in sorted(candidates, reverse=True)[:5]:
            family = family_of(predictor)
            issues.append({"predictor": predictor, "family": family, "wallet": wallet,
                           "value": value, "issue": "IMPOSSIBLE_VALUE" if impossible else "EXTREME_IQR_OUTLIER",
                           "p25": q25, "p75": q75, "p99": audit["p99"],
                           "supporting_observation": compact_evidence(evidence_by_wallet[wallet], family)})
    return issues


def _weekly_repeat(mapping: dict[str, str], timing: dict[str, int], lower: int, upper: int) -> float | None:
    sequence = [value for tx_hash, value in sorted(mapping.items(), key=lambda item: timing.get(item[0], 0))
                if lower <= timing.get(tx_hash, -1) < upper]
    if len(sequence) < 3:
        return None
    counts = Counter(sequence)
    return sum(count for count in counts.values() if count > 1) / len(sequence)


def stability_analysis(evidence: list[dict]) -> tuple[list[dict], dict]:
    conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
    timing = {row[0]: row[1] for row in conn.execute(
        "SELECT tx_hash,block_timestamp FROM transactions WHERE block_timestamp IS NOT NULL")}
    conn.close()
    start = 1785542400
    wallet_metric_rows = []
    by_metric_week = defaultdict(lambda: defaultdict(dict))
    for item in evidence:
        wallet = item["wallet"]
        features = item["features"]
        template_map = (features["templates"].get("evidence") or {}).get("transaction_templates") or {}
        topology_details = (features["topology"].get("evidence") or {}).get("transactions_detail") or []
        topology_map = {row["tx_hash"]: row["topology"] for row in topology_details
                        if row.get("tx_hash") and row.get("topology")}
        tx_hashes = set(template_map) | set(topology_map)
        tx_hashes.update((features["temporal"].get("evidence") or {}).get("transaction_hashes") or [])
        timestamps = sorted(timing[tx_hash] for tx_hash in tx_hashes if tx_hash in timing)
        weekly = defaultdict(list)
        for week in range(CONFIG["weekly_subwindows"]):
            lower = start + week * CONFIG["weekly_window_seconds"]
            upper = lower + CONFIG["weekly_window_seconds"]
            subset = [timestamp for timestamp in timestamps if lower <= timestamp < upper]
            _, baseline = _baseline(subset)
            hour_counts = Counter((timestamp // 3600) % 24 for timestamp in subset)
            metrics = {
                "dominant_period_seconds": baseline.get("dominant_period_seconds") if len(subset) >= 5 else None,
                "periodicity_strength": baseline.get("periodicity_strength") if len(subset) >= 5 else None,
                "activity_hour_concentration": max(hour_counts.values()) / len(subset) if subset else None,
                "template_repeat_ratio": _weekly_repeat(template_map, timing, lower, upper),
                "topology_repeat_ratio": _weekly_repeat(topology_map, timing, lower, upper),
            }
            for metric, value in metrics.items():
                weekly[metric].append(value)
                if value is not None:
                    by_metric_week[metric][week][wallet] = value
        for metric, values in weekly.items():
            observed = [value for value in values if value is not None]
            variance = statistics.pvariance(observed) if len(observed) >= 2 else None
            mean = statistics.mean(observed) if observed else None
            coefficient = (statistics.pstdev(observed) / abs(mean)
                           if len(observed) >= 2 and mean not in (None, 0) else None)
            wallet_metric_rows.append({"wallet": wallet, "metric": metric,
                                       "eligible_week_count": len(observed),
                                       "week_1": values[0], "week_2": values[1],
                                       "week_3": values[2], "week_4": values[3],
                                       "week_to_week_variance": variance,
                                       "coefficient_of_variation": coefficient})
    summary = {}
    for metric, weeks in by_metric_week.items():
        rank_stability = []
        for week in range(CONFIG["weekly_subwindows"] - 1):
            wallets = sorted(set(weeks[week]) & set(weeks[week + 1]))
            rho = spearman([weeks[week][wallet] for wallet in wallets],
                           [weeks[week + 1][wallet] for wallet in wallets]) if len(wallets) >= 10 else None
            rank_stability.append({"left_week": week + 1, "right_week": week + 2,
                                   "overlap": len(wallets), "spearman_rank_stability": rho})
        relevant = [row for row in wallet_metric_rows if row["metric"] == metric and
                    row["eligible_week_count"] >= 2]
        cvs = [row["coefficient_of_variation"] for row in relevant
               if row["coefficient_of_variation"] is not None]
        variances = [row["week_to_week_variance"] for row in relevant
                     if row["week_to_week_variance"] is not None]
        summary[metric] = {"wallets_with_two_or_more_weeks": len(relevant),
                           "median_within_wallet_cv": statistics.median(cvs) if cvs else None,
                           "median_within_wallet_variance": statistics.median(variances) if variances else None,
                           "adjacent_week_rank_stability": rank_stability}
    summary["limitations"] = [CONFIG["weekly_coverage_note"],
                              "Stability is descriptive and support-aware; transient bursts need not be stable."]
    return wallet_metric_rows, summary


def candidate_feature_sets(rows: list[dict], predictors: list[str], audits: list[dict],
                           leakage: list[dict], groups: list[dict]) -> tuple[dict, list[dict]]:
    audit_by = {row["predictor"]: row for row in audits}
    leakage_by = {row["predictor"]: row for row in leakage}
    broad = [predictor for predictor in predictors
             if family_of(predictor) not in {"cross_feature", "typed_assets"}
             and predictor not in ACTIVITY_PREDICTORS
             and audit_by[predictor]["classification"] not in
             {"VERY_SPARSE", "CONSTANT", "NEAR_CONSTANT", "SUSPICIOUS"}]
    core = [predictor for predictor in broad if family_of(predictor) in CORE_FAMILIES]
    low = set(core)
    removals = []
    dependence_order = {"LOW_ACTIVITY_DEPENDENCE": 0, "MODERATE_ACTIVITY_DEPENDENCE": 1,
                        "HIGH_ACTIVITY_DEPENDENCE": 2}
    specificity_order = {"STRONGLY_CKB_NATIVE": 0, "WEAKLY_CKB_SPECIFIC": 1,
                         "GENERIC_ACCOUNT_LIKE": 2}
    for group in groups:
        candidates = [name for name in group["predictors"] if name in low]
        if len(candidates) < 2:
            continue
        keep = min(candidates, key=lambda name: (
            dependence_order[leakage_by[name]["activity_dependence"]],
            audit_by[name]["missing_ratio"], specificity_order[specificity_for(family_of(name))], name))
        for remove in candidates:
            if remove == keep:
                continue
            low.remove(remove)
            removals.append({"removed": remove, "retained": keep, "group_id": group["group_id"],
                             "reason": "NEAR_DUPLICATE_ABS_CORRELATION_AT_LEAST_0.95"})
    low = sorted(low)
    high = [predictor for predictor in low
            if audit_by[predictor]["non_missing_count"] >= CONFIG["high_confidence_minimum_non_missing"]
            and audit_by[predictor]["missing_ratio"] <= CONFIG["high_confidence_max_missing_ratio"]
            and leakage_by[predictor]["activity_dependence"] != "HIGH_ACTIVITY_DEPENDENCE"]
    secondary = sorted(column for column in rows[0]
                       if column.startswith("rule__") and column.endswith("__score") and
                       any(number(row.get(column)) is not None for row in rows))
    sets = {"BROAD_V2": sorted(broad), "CORE_BEHAVIOUR": sorted(core),
            "LOW_REDUNDANCY_CORE": low, "HIGH_CONFIDENCE": sorted(high),
            "SECONDARY_EXPERIMENTAL_RULE_SCORES": sorted(secondary)}
    summaries = {}
    for name, features in sets.items():
        available = [sum(number(row.get(feature)) is not None for feature in features) for row in rows]
        possible = len(rows) * len(features)
        summaries[name] = {"feature_count": len(features),
                           "wallet_count": len(rows),
                           "wallets_with_any_value": sum(count > 0 for count in available),
                           "complete_case_wallets": sum(count == len(features) for count in available) if features else 0,
                           "wallets_at_least_50pct_complete":
                               sum(count / len(features) >= .5 for count in available) if features else 0,
                           "missing_value_count": possible - sum(available),
                           "missing_ratio": (possible - sum(available)) / possible if possible else None,
                           "family_composition": dict(Counter(family_of(feature) for feature in features)),
                           "features": features}
    summaries["LOW_REDUNDANCY_CORE"]["documented_removals"] = removals
    return summaries, removals


def export_candidate_matrices(rows: list[dict], candidates: dict) -> dict:
    names = {"BROAD_V2": "broad_v2_primary.csv",
             "CORE_BEHAVIOUR": "core_behaviour_primary.csv",
             "LOW_REDUNDANCY_CORE": "low_redundancy_core.csv",
             "HIGH_CONFIDENCE": "high_confidence.csv",
             "SECONDARY_EXPERIMENTAL_RULE_SCORES": "secondary_experimental_rule_scores.csv"}
    paths = {}
    metadata = [{"row_id": index, "wallet": row["wallet"],
                 "collection_state": row["collection_state"]}
                for index, row in enumerate(rows)]
    write_csv(OUT_DIR / "candidate_matrix_metadata_v1.csv", metadata,
              ["row_id", "wallet", "collection_state"])
    for set_name, filename in names.items():
        features = candidates[set_name]["features"]
        path = OUT_DIR / filename
        write_csv(path, [{feature: row.get(feature) for feature in features} for row in rows], features)
        paths[set_name] = str(path)
    return paths


def cohort_analysis(rows: list[dict], broad_features: list[str]) -> tuple[list[dict], dict]:
    memberships = []
    coverage_sensitivity = Counter()
    family_sensitivity = Counter()
    for row in rows:
        available = sum(number(row.get(feature)) is not None for feature in broad_features)
        coverage = available / len(broad_features) if broad_features else 0
        supported = {family for family in FAMILIES if family != "cross_feature" and
                     row.get(f"{family}_support") == "SUPPORTED"}
        for threshold in CONFIG["coverage_thresholds"]:
            if coverage >= threshold:
                coverage_sensitivity[f"at_least_{int(threshold * 100)}pct"] += 1
        for minimum in range(3, 9):
            if len(supported) >= minimum:
                family_sensitivity[f"at_least_{minimum}_families"] += 1
        memberships.append({"wallet": row["wallet"], "broad_available_predictors": available,
                            "broad_coverage_ratio": coverage,
                            "supported_family_count": len(supported),
                            "cohort_a_at_least_50pct": coverage >= .50,
                            "cohort_b_topology_templates_scripts_capacity":
                                {"topology", "templates", "scripts", "capacity"}.issubset(supported),
                            "cohort_c_temporal_topology_templates":
                                {"temporal", "topology", "templates"}.issubset(supported),
                            "cohort_d_at_least_6_families": len(supported) >= 6})
    summary = {"coverage_threshold_sensitivity": dict(coverage_sensitivity),
               "supported_family_threshold_sensitivity": dict(family_sensitivity),
               "named_cohorts": {
                   "A_at_least_50pct_broad": sum(row["cohort_a_at_least_50pct"] for row in memberships),
                   "B_topology_templates_scripts_capacity":
                       sum(row["cohort_b_topology_templates_scripts_capacity"] for row in memberships),
                   "C_temporal_topology_templates":
                       sum(row["cohort_c_temporal_topology_templates"] for row in memberships),
                   "D_at_least_6_supported_families":
                       sum(row["cohort_d_at_least_6_families"] for row in memberships)},
               "selection_status": "CANDIDATES_ONLY_NO_FINAL_COHORT_SELECTED"}
    return memberships, summary


def manual_review_set(evidence: list[dict]) -> list[dict]:
    by_rule = defaultdict(list)
    for item in evidence:
        for rule in item["rules"]:
            if rule["support_state"] not in {"SUPPORTED", "PARTIAL"} or rule["score"] is None:
                continue
            by_rule[rule["rule"]].append({"wallet": item["wallet"], **rule})
    output = []
    for rule_name, candidates in sorted(by_rule.items()):
        positives = [row for row in candidates if "THRESHOLDS_MET" in row["reason_codes"] or
                     "MULTIPLE_INDEPENDENT_PATTERNS" in row["reason_codes"]]
        negatives = [row for row in candidates if "THRESHOLDS_NOT_MET" in row["reason_codes"] or
                     "FEWER_THAN_TWO_POSITIVE_PATTERNS" in row["reason_codes"]]
        selected = []
        selected += [("STRONG", row) for row in sorted(positives, key=lambda row: -row["score"])[:5]]
        used = {row["wallet"] for _, row in selected}
        borderline_pool = [row for row in sorted(positives, key=lambda row: row["score"]) +
                           sorted(negatives, key=lambda row: -row["score"]) if row["wallet"] not in used]
        selected += [("BORDERLINE_SCORE_PROXY", row) for row in borderline_pool[:5]]
        used.update(row["wallet"] for _, row in selected)
        selected += [("SUPPORTED_NEGATIVE", row) for row in sorted(negatives, key=lambda row: row["score"])
                     if row["wallet"] not in used][:5]
        for category, row in selected:
            output.append({"rule": rule_name, "review_category": category,
                           "wallet": row["wallet"], "rule_score": row["score"],
                           "feature_values": row["supporting_features"],
                           "reason_codes": row["reason_codes"], "support_state": row["support_state"],
                           "supporting_transaction_hashes": row["supporting_transaction_hashes"],
                           "supporting_transaction_count": row["supporting_transaction_count"],
                           "caveat": "Rule scores are not calibrated decision probabilities; borderline is a review-priority proxy."})
    return output


def family_contribution(audits: list[dict], leakage: list[dict], redundancy_pairs: list[dict]) -> dict:
    leakage_by = {row["predictor"]: row for row in leakage}
    output = {}
    for family in FAMILIES:
        rows = [row for row in audits if row["family"] == family]
        if not rows:
            output[family] = {"predictor_count": 0, "assessment": "NO_NUMERIC_PREDICTORS"}
            continue
        cross_pairs = [pair for pair in redundancy_pairs if pair["left_family"] != pair["right_family"] and
                       family in {pair["left_family"], pair["right_family"]}]
        output[family] = {
            "predictor_count": len(rows),
            "usable_or_sparse_count": sum(row["classification"] in {"USABLE", "SPARSE"} for row in rows),
            "median_missing_ratio": statistics.median(row["missing_ratio"] for row in rows),
            "high_activity_dependence_count": sum(
                leakage_by[row["predictor"]]["activity_dependence"] == "HIGH_ACTIVITY_DEPENDENCE" for row in rows),
            "strong_cross_family_redundancy_pairs": len(cross_pairs),
            "assessment": "CONTRIBUTES_DISTINCT_CANDIDATES" if len(cross_pairs) < max(1, len(rows) // 2)
                          else "REVIEW_FAMILY_OVERLAP",
            "ckb_native_classification": specificity_for(family),
        }
    return output


def readiness_gates(audits: list[dict], redundancy_pairs: list[dict], cohorts: dict) -> dict:
    raw = [row for row in audits if row["family"] not in {"cross_feature", "typed_assets"} and
           row["predictor"] not in ACTIVITY_PREDICTORS]
    return {
        "sensitivity": {
            "features_by_maximum_missing_ratio": {
                str(threshold): sum(row["missing_ratio"] <= threshold for row in raw)
                for threshold in (.20, .40, .50, .60, .70, .80)},
            "features_by_minimum_non_missing": {
                str(minimum): sum(row["non_missing_count"] >= minimum for row in raw)
                for minimum in (100, 200, 300, 400, 500)},
            "redundancy_pairs_by_absolute_threshold": {
                str(threshold): sum(max(abs(row["pearson"] or 0), abs(row["spearman"] or 0)) >= threshold
                                    for row in redundancy_pairs)
                for threshold in (.90, .95, .98)},
            "wallet_cohorts": cohorts,
        },
        "recommended_preconditions": [
            {"gate": "minimum_wallet_cohort_size", "recommendation": 200,
             "reason": "Supports exploratory stability checks while sensitivity reports show the cost of stricter support."},
            {"gate": "maximum_feature_missing_ratio", "recommendation": 0.40,
             "reason": "Use only after selecting a support-aware cohort; do not impute before the missingness mechanism is chosen."},
            {"gate": "minimum_non_missing_per_predictor", "recommendation": 300,
             "reason": "Provides a defensible floor for correlation and transformation estimates."},
            {"gate": "near_duplicate_absolute_correlation", "recommendation": 0.95,
             "reason": "Apply documented KEEP_ONE decisions, then rerun redundancy on the selected cohort."},
            {"gate": "activity_leakage_reviewed", "recommendation": True,
             "reason": "High-activity dependence must be interpreted or excluded before clustering."},
            {"gate": "typed_assets_excluded", "recommendation": True,
             "reason": "No typed-asset predictor has fully supported observations."},
            {"gate": "scaling_strategy_locked", "recommendation": True,
             "reason": "Capacity, lifetime, count, ratio, and entropy scales are materially different."},
        ],
        "warning": "Thresholds are recommendations accompanied by sensitivity, not statistical power guarantees."
    }


def markdown_report(audits: list[dict], missingness: dict, cohorts: dict, leakage: list[dict],
                    redundancy_pairs: list[dict], groups: list[dict], issues: list[dict],
                    stability: dict, contribution: dict, candidates: dict,
                    review: list[dict], gates: dict, paths: dict) -> Path:
    classes = Counter(row["classification"] for row in audits)
    activity = Counter(row["activity_dependence"] for row in leakage)
    impossible = sum(row["impossible_value_count"] for row in audits)
    high_activity = sorted((row for row in leakage if row["activity_dependence"] == "HIGH_ACTIVITY_DEPENDENCE"),
                           key=lambda row: -row["maximum_absolute_spearman"])
    strong = sum(max(abs(row["pearson"] or 0), abs(row["spearman"] or 0)) >= .90
                 for row in redundancy_pairs)
    near = sum(max(abs(row["pearson"] or 0), abs(row["spearman"] or 0)) >= .95
               for row in redundancy_pairs)
    high_cohort = cohorts["named_cohorts"]["A_at_least_50pct_broad"]
    exploratory = "PARTIAL"
    lines = ["# CKB Feature Validation and ML Readiness Report", "",
             "This phase validates the frozen V2 feature space. It performs no imputation, PCA, UMAP, clustering, classification, collection, or Dataset V1 mutation.", "",
             "## A. Predictor audit", "",
             f"All **{len(audits)}** ML-safe predictors were audited. The complete table is `{paths['predictor_audit']}`.", "",
             "```json", json.dumps(dict(classes), indent=2, sort_keys=True), "```", "",
             "Classification thresholds are versioned in `validation_config_v1.json`; no feature was automatically removed from canonical V2.", "",
             "## B. Missingness report", "", "Feature coverage thresholds across all 121 predictors:", "", "```json",
             json.dumps(missingness["coverage_threshold_counts"], indent=2, sort_keys=True), "```", "",
             "Missing means **not supported or not observed**, never zero behaviour. No imputation was performed.", "",
             "## C. Support-cohort analysis", "", "```json",
             json.dumps(cohorts, indent=2, sort_keys=True), "```", "",
             "The named cohorts are candidates only; no final ML cohort was selected.", "",
             "## D. Activity leakage analysis", "",
             f"Dependence classes: `{dict(activity)}`. High dependence means absolute Spearman rho ≥ {CONFIG['high_activity_dependence']}.", "",
             "Most activity-associated predictors:", ""]
    for row in high_activity[:20]:
        lines.append(f"- `{row['predictor']}`: max |rho| = {row['maximum_absolute_spearman']:.4f}")
    lines += ["", "Raw transaction count, observed controlled-Cell count, input count, and output count remain diagnostics and are excluded from primary candidate matrices.", "",
              "## E. Redundancy report", "",
              f"Pairs at |correlation| ≥ 0.90: **{strong}**; pairs at ≥ 0.95: **{near}**; near-duplicate groups: **{len(groups)}**.", "",
              "Every KEEP_ONE removal is recorded in `candidate_feature_sets_v1.json`; canonical V2 remains unchanged.", "",
              "## F. Distribution audit", "",
              f"Impossible values: **{impossible}**. Recorded extreme/manual-review cases: **{len(issues)}**.", "",
              "Outliers were not clipped. Each issue record retains its wallet identifier and compact evidence provenance.", "",
              "## G. Stability analysis", "", "```json", json.dumps(stability, indent=2, sort_keys=True), "```", "",
              "Four fixed weekly subwindows were evaluated for periodicity, template recurrence, topology recurrence, and activity concentration. Transient burst behaviour is not required to be stable.", "",
              "## H. Feature-family contribution analysis", "", "```json",
              json.dumps(contribution, indent=2, sort_keys=True), "```", "",
              "## I. Candidate feature matrices", ""]
    for name in ("BROAD_V2", "CORE_BEHAVIOUR", "LOW_REDUNDANCY_CORE", "HIGH_CONFIDENCE",
                 "SECONDARY_EXPERIMENTAL_RULE_SCORES"):
        item = candidates[name]
        lines.append(f"- **{name}**: {item['feature_count']} features; missing ratio {item['missing_ratio']}; "
                     f"{item['wallets_at_least_50pct_complete']} wallets at least 50% complete")
    lines += ["", "Rule scores are present only in SECONDARY_EXPERIMENTAL. Typed assets are retained canonically but excluded from PRIMARY candidates because no typed-asset observation is fully supported.", "",
              "## J. Scaling and transformation recommendations", "",
              "Every predictor has a versioned recommendation in `predictor_registry_v1.csv`: bounded ratios/entropies are preserved, heavy-tailed counts/capacity/lifetimes use log1p plus RobustScaler, and remaining unbounded shape statistics use StandardScaler or RobustScaler as indicated. Nothing was transformed in this phase.", "",
              "## K. Manual behaviour review dataset", "",
              f"The review set contains **{len(review)}** strong, borderline-score-proxy, and supported-negative records across all rules, with feature values, reason codes, support, and transaction hashes.", "",
              "## L. Proposed exploratory ML workflow", "",
              "1. Select a support-aware wallet cohort after reviewing cohort sensitivity.",
              "2. Select the Low-Redundancy Core or High-Confidence candidate set.",
              "3. Decide the missing-data strategy by support mechanism; never zero-fill unsupported evidence.",
              "4. Apply the recorded log1p/scaling transformations.",
              "5. Use PCA first for global variance and activity-axis inspection.",
              "6. Use UMAP for visualization only after stability sensitivity.",
              "7. Compare HDBSCAN density structure with GMM soft assignments.",
              "8. Evaluate resampling, feature-set, scaling, and parameter stability.",
              "9. Interpret any structure using raw evidence, never legacy labels.", "",
              "## M. Clustering readiness", "",
              f"- **FEATURE DEFINITIONS: READY** — all {len(audits)} predictors have family, definition, support, unit, missing semantics, limitations, and transformation metadata.",
              "- **MISSINGNESS UNDERSTOOD: READY** — feature, wallet, block-pattern, and cohort analyses are explicit.",
              "- **ACTIVITY LEAKAGE: READY** — Pearson/Spearman diagnostics are complete; decisions remain for the ML phase.",
              "- **FEATURE REDUNDANCY: READY** — overlap-qualified pairs and KEEP_ONE candidates are documented.",
              "- **FEATURE STABILITY: PARTIAL** — four weekly windows are analyzed, but only one month is available and days 29–30 are outside weekly stability.",
              "- **CORE FEATURE MATRIX: READY** — raw rule scores, typed assets, and activity-volume diagnostics are excluded.",
              f"- **HIGH-CONFIDENCE WALLET COHORT: {'READY' if high_cohort >= 200 else 'PARTIAL'}** — candidate size at ≥50% Broad coverage is {high_cohort}; final selection remains pending.",
              f"- **EXPLORATORY ML: {exploratory}** — candidate inputs exist, but cohort/missingness/scaling choices must be locked first.",
              "- **PCA: PARTIAL** — recommended as the first analysis after preprocessing decisions; not run.",
              "- **UMAP: NOT READY** — depends on cohort, scaling, missingness, and PCA inspection; not run.",
              "- **HDBSCAN: NOT READY** — depends on a stable transformed feature space; not run.",
              "- **GMM: NOT READY** — depends on a stable dense representation and component sensitivity; not run.",
              "- **SUPERVISED CLASSIFICATION: NOT READY** — no defensible target labels exist.", "",
              "Readiness gates and their threshold sensitivity are in `clustering_readiness_gates_v1.json`.", "",
              "No Dataset V1/V2 source artifact was modified."]
    path = OUT_DIR / "FEATURE_VALIDATION_ML_READINESS_REPORT.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def verify_sources(contract: dict) -> dict:
    paths = [V2_DIR / "wallet_behaviour_features_v2.csv",
             V2_DIR / "wallet_behaviour_features_v2_ml.csv",
             V2_DIR / "wallet_behaviour_features_v2_metadata.csv",
             V2_DIR / "wallet_behaviour_features_v2_evidence.jsonl",
             V2_DIR / "feature_definitions_v2.json"]
    source = {str(path.relative_to(ROOT.parent)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
              for path in paths}
    if (DB_PATH.stat().st_size != contract["source_database"]["bytes"] or
            sha256(DB_PATH) != contract["source_database"]["sha256"]):
        raise RuntimeError("frozen source database changed")
    conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
    integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.close()
    if integrity != "ok":
        raise RuntimeError("SQLite integrity failed")
    return {"source_artifacts": source, "database": contract["source_database"],
            "manifest_hash": contract["manifest_hash"], "sqlite_quick_check": integrity}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, predictors, evidence, definitions, contract = load_inputs()
    source_before = verify_sources(contract)
    audits, registry = predictor_audit(rows, predictors, definitions)
    wallet_missingness, missingness = missingness_analysis(rows, predictors)
    diagnostics = load_activity_diagnostics()
    leakage = activity_leakage(rows, predictors, diagnostics)
    redundancy_pairs, redundancy_groups, family_redundancy = redundancy_analysis(rows, predictors)
    issues = distribution_issues(rows, predictors, audits, evidence)
    weekly_rows, stability = stability_analysis(evidence)
    candidates, removals = candidate_feature_sets(rows, predictors, audits, leakage, redundancy_groups)
    matrix_paths = export_candidate_matrices(rows, candidates)
    cohort_rows, cohorts = cohort_analysis(rows, candidates["BROAD_V2"]["features"])
    review = manual_review_set(evidence)
    contribution = family_contribution(audits, leakage, redundancy_pairs)
    gates = readiness_gates(audits, redundancy_pairs, cohorts)
    imputation = {
        family: {"missing_mechanism": "INSUFFICIENT_OBSERVATION_SUPPORT",
                 "recommendation": "DO_NOT_IMPUTE_IN_VALIDATION",
                 "future_option": "Model support cohorts separately or add explicit missingness indicators only after sensitivity analysis."}
        for family in FAMILIES if family != "cross_feature"
    }
    imputation["typed_assets"].update(
        missing_mechanism="RAW_XUDT_PAYLOAD_UNAVAILABLE_AND_INSUFFICIENT_SUPPORT",
        future_option="Exclude from primary ML until raw 16-byte payload support is established.")
    config = {**CONFIG, "source_dataset_version": contract["dataset_version"],
              "source_manifest_hash": contract["manifest_hash"], "source_predictor_count": len(predictors)}
    dump(OUT_DIR / "validation_config_v1.json", config)
    dump(OUT_DIR / "source_integrity_v1.json", source_before)
    write_csv(OUT_DIR / "predictor_audit_v1.csv", audits)
    write_csv(OUT_DIR / "predictor_registry_v1.csv", registry)
    dump(OUT_DIR / "predictor_registry_v1.json", registry)
    write_csv(OUT_DIR / "wallet_missingness_v1.csv", wallet_missingness)
    dump(OUT_DIR / "missingness_patterns_v1.json", missingness)
    activity_rows = [{"wallet": row["wallet"], **diagnostics.get(row["wallet"], {})} for row in rows]
    write_csv(OUT_DIR / "activity_diagnostics_v1.csv", activity_rows)
    write_csv(OUT_DIR / "activity_leakage_v1.csv", leakage)
    write_csv(OUT_DIR / "feature_redundancy_pairs_v1.csv", redundancy_pairs)
    dump(OUT_DIR / "feature_redundancy_groups_v1.json", redundancy_groups)
    dump(OUT_DIR / "feature_family_redundancy_v1.json", family_redundancy)
    with (OUT_DIR / "distribution_review_v1.jsonl").open("w") as handle:
        for item in issues:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    write_csv(OUT_DIR / "weekly_feature_stability_v1.csv", weekly_rows)
    dump(OUT_DIR / "feature_stability_v1.json", stability)
    dump(OUT_DIR / "feature_family_contribution_v1.json", contribution)
    dump(OUT_DIR / "candidate_feature_sets_v1.json", candidates)
    write_csv(OUT_DIR / "low_redundancy_removals_v1.csv", removals)
    write_csv(OUT_DIR / "wallet_cohort_candidates_v1.csv", cohort_rows)
    dump(OUT_DIR / "wallet_cohort_analysis_v1.json", cohorts)
    with (OUT_DIR / "behaviour_manual_review_v1.jsonl").open("w") as handle:
        for item in review:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    dump(OUT_DIR / "imputation_strategy_recommendation_v1.json", imputation)
    dump(OUT_DIR / "clustering_readiness_gates_v1.json", gates)
    paths = {"predictor_audit": str(OUT_DIR / "predictor_audit_v1.csv"), **matrix_paths}
    report = markdown_report(audits, missingness, cohorts, leakage, redundancy_pairs,
                             redundancy_groups, issues, stability, contribution, candidates,
                             review, gates, paths)
    source_after = verify_sources(contract)
    if source_before != source_after:
        raise RuntimeError("frozen V2 source artifacts changed during validation")
    print(json.dumps({"analysis_version": ANALYSIS_VERSION, "predictors": len(predictors),
                      "wallets": len(rows), "candidate_sets":
                      {name: value["feature_count"] for name, value in candidates.items()},
                      "manual_review_rows": len(review), "report": str(report),
                      "source_integrity": source_after}, indent=2))


if __name__ == "__main__":
    main()
