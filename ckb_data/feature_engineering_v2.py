from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from features_v2.config import (DATASET_VERSION, FEATURE_CONFIG_VERSION,
                                FEATURE_SCHEMA_VERSION, OBSERVATION_CONTRACT_VERSION)
from features_v2.pipeline import assess_observation_v2, load_observation_v2
from features_v2.stats import pearson, quantile

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "ckb_data_v2" / "ckb_explorer.sqlite"
V1_DIR = ROOT / "dataset_completion"
OUT_DIR = ROOT / "feature_engineering_v2"
SNAPSHOT_DIR = OUT_DIR / "dataset_v1_snapshot"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def freeze_dataset(conn, database: Path) -> dict:
    population = json.loads((V1_DIR / "population_contract_v1.json").read_text())
    window = json.loads((V1_DIR / "observation_window_v1.json").read_text())
    quality = json.loads((V1_DIR / "dataset_quality_v1.json").read_text())
    state_counts = dict(conn.execute(
        "SELECT collection_state,COUNT(*) FROM wallet_collection_state GROUP BY collection_state"))
    v1_artifacts = [
        "population_contract_v1.json", "observation_window_v1.json", "population_manifest_v1.jsonl",
        "wallet_behaviour_features_canonical_v1.csv", "wallet_behaviour_features_ml_v1.csv",
        "wallet_behaviour_features_ml_metadata_v1.csv", "wallet_behaviour_evidence_v1.jsonl",
        "wallet_collection_states_v1.csv", "dataset_quality_v1.json", "DATASET_COMPLETION_REPORT.md",
    ]
    artifact_manifest = []
    for name in v1_artifacts:
        path = V1_DIR / name
        artifact_manifest.append({"path": str(path.relative_to(ROOT.parent)), "bytes": path.stat().st_size,
                                  "sha256": sha256(path)})
    database_record = {"path": str(database.relative_to(ROOT.parent)), "bytes": database.stat().st_size,
                       "sha256": sha256(database)}
    canonical_header = next(csv.DictReader((V1_DIR / "wallet_behaviour_features_canonical_v1.csv").open())).get(
        "feature_schema_version")
    contract = {
        "dataset_version": DATASET_VERSION,
        "population_version": population["research_population_version"],
        "manifest_hash": population["manifest_hash"],
        "observation_window_id": window["observation_window_id"],
        "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
        "total_wallets": sum(state_counts.values()), "complete_wallets": state_counts.get("COMPLETE", 0),
        "partial_wallets": state_counts.get("PARTIAL", 0),
        "failed_wallets": sum(value for key, value in state_counts.items() if key.startswith("FAILED_")),
        "collection_states": state_counts, "transaction_count": quality["transactions_observed"],
        "input_count": quality["applicable_input_resolution"]["total_inputs"],
        "applicable_input_count": quality["applicable_input_resolution"]["applicable_inputs"],
        "resolved_input_count": quality["applicable_input_resolution"]["resolved_applicable_inputs"],
        "feature_schema_version": canonical_header or "ckb-behaviour-features-v1",
        "creation_timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_database": database_record,
        "freeze_strategy": "LOGICAL_CONTENT_ADDRESSED_SNAPSHOT",
    }
    existing = SNAPSHOT_DIR / "dataset_contract_v1.json"
    if existing.exists():
        previous = json.loads(existing.read_text())
        comparable = {key: value for key, value in contract.items() if key != "creation_timestamp"}
        old_comparable = {key: value for key, value in previous.items() if key != "creation_timestamp"}
        if comparable != old_comparable:
            raise RuntimeError("frozen Dataset V1 source digest or contract changed")
        contract = previous
    else:
        dump(existing, contract)
        dump(SNAPSHOT_DIR / "artifact_manifest_v1.json", artifact_manifest)
    return contract


def unresolved_assessment(reason: str) -> dict:
    from features_v2.config import MINIMUM_SAMPLES
    from features_v2.rules import RULE_NAMES, RULE_VERSION
    families = {}
    for family in ("temporal", "periodicity", "topology", "lifecycle", "templates", "scripts",
                   "typed_assets", "capacity", "lineage"):
        families[family] = {"feature_schema_version": FEATURE_SCHEMA_VERSION,
                            "dataset_version": DATASET_VERSION,
                            "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
                            "feature_family": family, "support_state": "UNRESOLVED",
                            "requirements": {"minimum_samples": MINIMUM_SAMPLES[family]},
                            "sample_count": 0, "coverage": {}, "values": {},
                            "evidence": {"reason": reason}}
    rules = [{"rule": name, "support_state": "UNRESOLVED", "score": None,
              "reason_codes": [reason], "supporting_features": {},
              "supporting_transaction_hashes": [], "supporting_transaction_count": 0,
              "rule_version": RULE_VERSION} for name in RULE_NAMES]
    return {"features": families, "rules": rules}


def flatten(wallet: dict, state: dict, assessment: dict) -> tuple[dict, dict]:
    row = {"wallet": wallet["address"], "canonical_lock_hash": wallet.get("canonical_lock_hash"),
           "dataset_version": DATASET_VERSION, "feature_schema_version": FEATURE_SCHEMA_VERSION,
           "feature_config_version": FEATURE_CONFIG_VERSION,
           "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
           "collection_state": state["collection_state"], "sampling_stratum": wallet.get("sampling_stratum"),
           "lifetime_tx_count": wallet.get("lifetime_tx_count"),
           "legacy_proxy_label": wallet.get("legacy_proxy_label")}
    for family, result in assessment["features"].items():
        row[f"{family}_support"] = result["support_state"]
        row[f"{family}_sample_count"] = result["sample_count"]
        row[f"{family}_coverage"] = json.dumps(result["coverage"], sort_keys=True)
        for name, value in result["values"].items():
            row[f"{family}__{name}"] = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
    for rule in assessment["rules"]:
        prefix = f"rule__{rule['rule']}"
        row[prefix + "__support"] = rule["support_state"]
        row[prefix + "__score"] = rule["score"]
    evidence = {"wallet": wallet["address"], "dataset_version": DATASET_VERSION,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "collection_state": state["collection_state"], **assessment}
    return row, evidence


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def numeric_summary(values: list[float]) -> dict:
    return {"count": len(values), "mean": statistics.mean(values),
            "median": statistics.median(values),
            "std": statistics.pstdev(values), "min": min(values), "max": max(values),
            "p10": quantile(values, .10), "p25": quantile(values, .25),
            "p75": quantile(values, .75), "p90": quantile(values, .90),
            "p99": quantile(values, .99)}


def audit(rows: list[dict], evidence: list[dict]) -> tuple[dict, dict]:
    support = defaultdict(Counter)
    rule_support = defaultdict(Counter)
    rule_positive = Counter()
    for item in evidence:
        for family, result in item["features"].items():
            support[family][result["support_state"]] += 1
        for rule in item["rules"]:
            rule_support[rule["rule"]][rule["support_state"]] += 1
            if "THRESHOLDS_MET" in rule["reason_codes"]:
                rule_positive[rule["rule"]] += 1
    numeric_columns = sorted({key for row in rows for key, value in row.items()
                              if "__" in key and numeric(value)})
    summaries, quality = {}, {}
    for column in numeric_columns:
        values = [row[column] for row in rows if numeric(row.get(column))]
        if not values:
            continue
        summaries[column] = numeric_summary(values)
        counts = Counter(values)
        q25, q75 = quantile(values, .25), quantile(values, .75)
        iqr = q75 - q25
        quality[column] = {"missing_count": len(rows) - len(values),
                           "missing_ratio": (len(rows) - len(values)) / len(rows),
                           "constant": len(counts) == 1,
                           "near_constant": counts.most_common(1)[0][1] / len(values) >= .99,
                           "extreme_outlier_count": sum(value < q25 - 3 * iqr or value > q75 + 3 * iqr
                                                        for value in values) if iqr else 0}
        for audit_name, getter in {
            "transaction_count_correlation": lambda row: row.get("temporal__transaction_count"),
            "collection_complete_correlation": lambda row: 1 if row.get("collection_state") == "COMPLETE" else 0,
            "family_supported_correlation": lambda row, family=column.split("__", 1)[0]:
                1 if row.get(family + "_support") == "SUPPORTED" else 0,
        }.items():
            pairs = [(row.get(column), getter(row)) for row in rows
                     if numeric(row.get(column)) and numeric(getter(row))]
            quality[column][audit_name] = pearson([a for a, _ in pairs], [b for _, b in pairs]) \
                if len(pairs) >= 10 else None
    high, duplicates = [], []
    for index, left in enumerate(numeric_columns):
        for right in numeric_columns[index + 1:]:
            pairs = [(row.get(left), row.get(right)) for row in rows
                     if numeric(row.get(left)) and numeric(row.get(right))]
            if len(pairs) < 10:
                continue
            correlation = pearson([a for a, _ in pairs], [b for _, b in pairs])
            if correlation is not None and abs(correlation) >= .95:
                high.append({"left": left, "right": right, "n": len(pairs), "pearson_r": correlation})
            equal = sum(abs(a - b) <= max(1e-12, abs(a) * 1e-9, abs(b) * 1e-9) for a, b in pairs)
            if equal / len(pairs) >= .99:
                duplicates.append({"left": left, "right": right, "n": len(pairs),
                                   "agreement_ratio": equal / len(pairs)})
    quality_report = {"dataset_version": DATASET_VERSION, "total_wallets": len(rows),
                      "feature_support": {key: dict(value) for key, value in support.items()},
                      "rule_support": {key: dict(value) for key, value in rule_support.items()},
                      "rule_positive_counts_among_evaluated": dict(rule_positive),
                      "numeric_summaries": summaries, "feature_quality": quality}
    redundancy = {"high_correlation_threshold": .95, "near_duplicate_agreement": .99,
                  "high_correlation_pairs": high, "near_duplicate_features": duplicates,
                  "automatic_removal": False}
    return quality_report, redundancy


def feature_definitions() -> dict:
    from features_v2 import capacity, lifecycle, lineage, periodicity, scripts, templates, temporal, topology, typed_assets
    definitions = {
        "temporal": {"sample_universe": "participating transactions with timestamps",
                     "method": "positive interarrival gaps; 30-minute sessions; 60-second bursts of at least three transactions"},
        "periodicity": {"sample_universe": "ordered positive interarrival gaps",
                        "method": "V1 median/MAD baseline, 5%-tolerant interval clusters, gap-sequence autocorrelation, four fixed weekly subwindows; Lomb-Scargle omitted"},
        "topology": {"sample_universe": "target-participating normalized transactions",
                     "method": "structural Cell and unique-lock counts only; no sender-recipient mapping"},
        "lifecycle": {"sample_universe": "target-controlled inputs consumed inside the frozen window with locally established creation transaction",
                      "method": "consumption timestamp/block minus creation timestamp/block; unconsumed target outputs are right-censored"},
        "templates": {"sample_universe": "comparable target-participating transactions",
                      "method": "SHA-256 of canonical structural shape with TARGET sentinel, script family/hash, data length, topology, and 5%-rounded relative capacity"},
        "scripts": {"sample_universe": "lock/type script slots on participating Cells",
                    "method": "exact code-hash/hash-type registry match; unmatched scripts remain canonical hashes"},
        "typed_assets": {"sample_universe": "target-controlled Cells matching the verified xUDT mainnet deployment",
                         "method": "first 16 data bytes as uint128 little-endian; cached metadata is cross-check only"},
        "capacity": {"sample_universe": "target-controlled input and output Cells",
                     "method": "structural Shannon-capacity distributions; occupied capacity only from explicit cached raw evidence"},
        "lineage": {"sample_universe": "locally established Cell-to-transaction and transaction-to-Cell hyperedges",
                    "method": "directed bipartite hypergraph; depth in transaction hops; no pairwise routes"},
    }
    modules = {module.__name__.rsplit(".", 1)[-1]: module for module in
               (temporal, periodicity, topology, lifecycle, templates, scripts, typed_assets, capacity, lineage)}
    for family, definition in definitions.items():
        definition["features"] = modules[family].FEATURES
        definition["executable_definition"] = f"ckb_data/features_v2/{family}.py::extract"
        definition["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        definition["feature_config_version"] = FEATURE_CONFIG_VERSION
    return definitions


def export(rows: list[dict], evidence: list[dict], quality: dict, redundancy: dict,
           definitions: dict) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    canonical = OUT_DIR / "wallet_behaviour_features_v2.csv"
    with canonical.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns); writer.writeheader(); writer.writerows(rows)
    metadata_columns = ["row_id", "wallet", "canonical_lock_hash", "dataset_version",
                        "collection_state", "sampling_stratum", "lifetime_tx_count",
                        "legacy_proxy_label"]
    metadata = OUT_DIR / "wallet_behaviour_features_v2_metadata.csv"
    with metadata.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=metadata_columns); writer.writeheader()
        for index, row in enumerate(rows):
            writer.writerow({key: index if key == "row_id" else row.get(key) for key in metadata_columns})
    forbidden = ("wallet", "hash", "label", "stratum", "lifetime", "timestamp", "collection",
                 "support", "coverage", "sample_count", "state", "cluster", "classifier", "prediction")
    ml_columns = [column for column in columns if "__" in column and
                  not any(token in column.lower() for token in forbidden) and
                  all(row.get(column) in (None, "") or numeric(row.get(column)) for row in rows) and
                  any(numeric(row.get(column)) for row in rows)]
    ml = OUT_DIR / "wallet_behaviour_features_v2_ml.csv"
    with ml.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ml_columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    evidence_path = OUT_DIR / "wallet_behaviour_features_v2_evidence.jsonl"
    with evidence_path.open("w") as handle:
        for item in evidence:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    dump(OUT_DIR / "feature_quality_v2.json", quality)
    dump(OUT_DIR / "feature_redundancy_v2.json", redundancy)
    dump(OUT_DIR / "feature_definitions_v2.json", definitions)
    return {"canonical": str(canonical), "ml": str(ml), "metadata": str(metadata),
            "evidence": str(evidence_path), "ml_columns": ml_columns}


def report(snapshot: dict, quality: dict, redundancy: dict, paths: dict,
           definitions: dict) -> Path:
    support = quality["feature_support"]
    readiness = {family: ("READY" if counts.get("SUPPORTED", 0) == snapshot["total_wallets"]
                          else "PARTIAL" if sum(counts.values()) else "NOT READY")
                 for family, counts in support.items()}
    lines = ["# CKB Behaviour Feature Engineering V2 Report", "", "## A. Dataset snapshot", "",
             f"- Dataset: `{DATASET_VERSION}`", f"- Wallets: {snapshot['total_wallets']}",
             f"- Complete / partial / failed: {snapshot['complete_wallets']} / {snapshot['partial_wallets']} / {snapshot['failed_wallets']}",
             f"- Manifest: `{snapshot['manifest_hash']}`", "",
             "## B. Implemented V2 feature families", "",
             "Temporal, periodicity, lifecycle, topology, fragmentation/consolidation, templates, scripts, typed assets, capacity, and Cell lineage.", "",
             "Exact executable definitions are versioned in `feature_definitions_v2.json`:", ""]
    for family, definition in definitions.items():
        lines += [f"- **{family}** — {definition['method']}; values: " +
                  ", ".join(f"`{name}`" for name in definition["features"]), ""]
    headings = [("C", "Cell lifecycle results", "lifecycle"), ("D", "Temporal results", "temporal"),
                ("E", "Topology results", "topology"), ("F", "Template results", "templates"),
                ("G", "Script/type results", "scripts"), ("H", "Capacity results", "capacity"),
                ("I", "Cell lineage results", "lineage")]
    for letter, title, family in headings:
        lines += [f"## {letter}. {title}", "", "```json",
                  json.dumps(support.get(family, {}), indent=2, sort_keys=True), "```", ""]
        if family == "temporal":
            lines += ["Periodicity support:", "", "```json",
                      json.dumps(support.get("periodicity", {}), indent=2, sort_keys=True), "```", ""]
        if family == "scripts":
            lines += ["Typed-asset support:", "", "```json",
                      json.dumps(support.get("typed_assets", {}), indent=2, sort_keys=True), "```",
                      "The verified xUDT deployment is present, but cached Cells lack the raw 16-byte data payload; Explorer amount metadata is retained as cross-check evidence, so typed-asset results remain support-limited.", ""]
    lines += ["## J. Behaviour-evidence rules", "", "```json",
              json.dumps(quality["rule_support"], indent=2, sort_keys=True), "```", "",
              "Positive threshold matches among evaluated observations (descriptive, not population prevalence):", "", "```json",
              json.dumps(quality["rule_positive_counts_among_evaluated"], indent=2, sort_keys=True), "```", "",
              "## K. Feature support matrix", "", "```json",
              json.dumps(support, indent=2, sort_keys=True), "```", "",
              "## L. Feature-quality audit", "",
              f"Numeric features audited: {len(quality['numeric_summaries'])}. Suspicious features are flagged, not removed.", "",
              "## M. Feature redundancy report", "",
              f"High-correlation pairs: {len(redundancy['high_correlation_pairs'])}; near-duplicates: {len(redundancy['near_duplicate_features'])}.", "",
              "## N. ML-safe V2 export", "", f"- `{paths['ml']}`", f"- Numeric predictors: {len(paths['ml_columns'])}",
              "- No imputation was performed.", "", "## O. Readiness", "",
              "- **DATASET V1: READY** — content-addressed logical snapshot verified.",
              f"- **CELL LIFECYCLE: {readiness.get('lifecycle', 'NOT READY')}**",
              f"- **TEMPORAL V2: {readiness.get('temporal', 'NOT READY')}**",
              f"- **TOPOLOGY V2: {readiness.get('topology', 'NOT READY')}**",
              f"- **TEMPLATES V2: {readiness.get('templates', 'NOT READY')}**",
              f"- **SCRIPT FEATURES V2: {readiness.get('scripts', 'NOT READY')}**",
              f"- **TYPED ASSETS: {readiness.get('typed_assets', 'NOT READY')}**",
              f"- **CAPACITY V2: {readiness.get('capacity', 'NOT READY')}**",
              f"- **CELL LINEAGE: {readiness.get('lineage', 'NOT READY')}**",
              "- **BEHAVIOUR EVIDENCE V2: PARTIAL** — support-qualified observable rules only.",
              "- **ML FEATURE ANALYSIS: PARTIAL** — export is safe; missingness and redundancy require review.",
              "- **CLUSTERING: NOT READY** — not run in this phase.", "",
              "No Explorer collection, wallet retry, identity inference, ML, clustering, commit, or merge was performed."]
    path = OUT_DIR / "FEATURE_ENGINEERING_V2_REPORT.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    uri = f"file:{args.database.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity check failed")
    snapshot = freeze_dataset(conn, args.database)
    manifest = [json.loads(line) for line in (V1_DIR / "population_manifest_v1.jsonl").read_text().splitlines()]
    states = {row["address"]: dict(row) for row in conn.execute("SELECT * FROM wallet_collection_state")}
    observations = {row["address"]: row["observation_id"] for row in conn.execute(
        "SELECT address,observation_id FROM wallet_observations WHERE window_start_timestamp=1785542400 AND window_end_timestamp=1788134400")}
    timing = {row["tx_hash"]: (row["block_timestamp"], row["block_number"])
              for row in conn.execute("SELECT tx_hash,block_timestamp,block_number FROM transactions")}
    rows, evidence = [], []
    for wallet in manifest:
        address = wallet["address"]
        state = states[address]
        if address in observations:
            observation = load_observation_v2(conn, observations[address], state["collection_state"], timing)
            assessment = assess_observation_v2(observation)
        else:
            assessment = unresolved_assessment("NO_NORMALIZED_OBSERVATION")
        row, item = flatten(wallet, state, assessment)
        rows.append(row); evidence.append(item)
    quality, redundancy = audit(rows, evidence)
    definitions = feature_definitions()
    paths = export(rows, evidence, quality, redundancy, definitions)
    report_path = report(snapshot, quality, redundancy, paths, definitions)
    print(json.dumps({"dataset": snapshot, "rows": len(rows), "paths": paths,
                      "report": str(report_path), "feature_support": quality["feature_support"]}, indent=2))


if __name__ == "__main__":
    main()
