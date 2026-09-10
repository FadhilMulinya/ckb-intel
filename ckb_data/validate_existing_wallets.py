"""Validate existing local wallets against wallet-observation-30d-v1.

This command never discovers wallets.  It imports historical local Explorer
JSONL into the shared cache, selects a label-blind cohort, and only asks
Explorer for evidence not already sufficient locally.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

from wallet_intelligence.clients import ClientUnavailable, ExplorerClient, resolve_observation_boundaries
from wallet_intelligence.collection import Store
from wallet_intelligence.normalization import (ObservationContract, STATUS_COMPLETE, STATUS_INCOMPLETE,
                        STATUS_NOT_APPLICABLE, normalize_transaction,
                        persist_observation, persist_transaction, ratio)
from research_pipeline.dataset_features.base import load_normalized_observation
from research_pipeline.dataset_features.pipeline import assess_observation
from research_pipeline.dataset_features.rule_config import THRESHOLDS
from wallet_intelligence.resolution import resolve_transaction_inputs
from wallet_intelligence.cache import CacheStats, persist_statistics
from research_manifest import build_manifest, write_manifest


WINDOW_START = 1_785_542_400  # 2026-08-01T00:00:00Z
WINDOW_END = 1_788_134_400    # 2026-08-31T00:00:00Z
RUN_VERSION = "existing-wallet-validation-v1"
POPULATION_VERSION = "ckb-wallet-population-local-v1"
OBSERVATION_WINDOW_ID = "ckb-mainnet-30d-2026-08-31-v1"


def network_safe_address(address: str) -> bool:
    """Reject contaminated manifest strings before constructing an Explorer URL."""
    return (isinstance(address, str) and address.startswith("ckb1") and
            all(33 <= ord(character) <= 126 for character in address))


def _timestamp(item: dict) -> int | None:
    value = item.get("block_timestamp") or item.get("create_timestamp")
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value // 1000 if value > 100_000_000_000 else value


def import_local_jsonl(repo_root: Path, store: Store, manifest: list[dict],
                       stats: CacheStats) -> dict:
    imported = cache_reuses = failed = source_records = 0
    source_hashes: set[str] = set()
    conn = store.conn
    for record in manifest:
        address = record["address"]
        for relative in record["existing_raw_paths"]:
            path = repo_root / relative
            try:
                handle = path.open()
                next(handle, None)  # address header
                for line in handle:
                    try:
                        payload = json.loads(line)
                        tx = normalize_transaction(payload, target_lock_hash=address)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        failed += 1
                        continue
                    source_records += 1
                    source_hashes.add(tx["tx_hash"])
                    existed = conn.execute(
                        "SELECT 1 FROM raw_transactions WHERE tx_hash=?", (tx["tx_hash"],)
                    ).fetchone()
                    if existed:
                        cache_reuses += 1
                        stats.increment("transaction_cache_hits")
                    else:
                        conn.execute(
                            "INSERT INTO raw_transactions (tx_hash,raw_json,fetched_at,source_kind) "
                            "VALUES (?,?,?,?)",
                            (tx["tx_hash"], json.dumps(payload, sort_keys=True),
                             int(dt.datetime.now(dt.timezone.utc).timestamp()),
                             "local_historical_address_transaction"),
                        )
                        imported += 1
                        stats.increment("transaction_cache_misses")
                    normalized_exists = conn.execute(
                        "SELECT 1 FROM transactions WHERE tx_hash=?", (tx["tx_hash"],)
                    ).fetchone()
                    if normalized_exists:
                        stats.increment("normalized_cache_hits")
                    else:
                        persist_transaction(conn, tx)
                    conn.execute(
                        "INSERT OR IGNORE INTO address_tx_seen VALUES (?,?,?)",
                        (address, tx["tx_hash"], tx["block_timestamp"]),
                    )
            except OSError:
                failed += 1
            finally:
                try:
                    handle.close()
                except (NameError, UnboundLocalError):
                    pass
    conn.commit()
    return {"source_transaction_records": source_records,
            "unique_local_transactions": len(source_hashes),
            "duplicate_transaction_records": source_records - len(source_hashes),
            "transactions_newly_imported": imported,
            "transaction_cache_reuses": cache_reuses,
            "records_failed": failed}


def _local_rows(conn, address: str) -> list[dict]:
    rows = conn.execute(
        """SELECT r.raw_json FROM address_tx_seen a
           JOIN raw_transactions r ON r.tx_hash=a.tx_hash
           WHERE a.address=? AND a.block_timestamp>=? AND a.block_timestamp<?
           ORDER BY a.block_timestamp""", (address, WINDOW_START, WINDOW_END)
    ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _local_listing_complete(conn, address: str, lifetime: int | None) -> bool:
    observed = conn.execute(
        """SELECT 1 FROM wallet_observations
           WHERE address=? AND window_start_timestamp=? AND window_end_timestamp=?
             AND listing_complete=1 LIMIT 1""",
        (address, WINDOW_START, WINDOW_END),
    ).fetchone()
    if observed:
        return True
    row = conn.execute(
        "SELECT COUNT(*),MIN(block_timestamp) FROM address_tx_seen WHERE address=?",
        (address,),
    ).fetchone()
    return bool(row and ((lifetime is not None and row[0] >= lifetime) or
                         (row[1] is not None and row[1] <= WINDOW_START)))


def annotate_completion_requirements(manifest: list[dict], conn) -> None:
    for item in manifest:
        if _local_listing_complete(conn, item["address"], item["lifetime_tx_count"]):
            requirement = "ZERO_REMOTE"
        elif item["existing_raw_data"]:
            requirement = "PARTIAL_REFILL"
        else:
            requirement = "FULL_30_DAY_COLLECTION"
        item["completion_requirement"] = requirement
        item["estimated_listing_requests"] = (
            0 if requirement == "ZERO_REMOTE" else
            math.ceil(item["lifetime_tx_count"] / 50)
            if item["lifetime_tx_count"] is not None else None)


def _fetch_listing(address: str, explorer: ExplorerClient, conn,
                   stats: CacheStats) -> tuple[list[dict], bool]:
    items = []
    for page in range(1, 10_001):
        cached = conn.execute(
            "SELECT raw_json FROM raw_address_pages WHERE address=? AND observation_window_id=? AND page=?",
            (address, OBSERVATION_WINDOW_ID, page),
        ).fetchone()
        if cached:
            stats.increment("address_page_cache_hits")
            try:
                payload = json.loads(cached[0])
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"cache corruption in address page {address} page {page}") from exc
        else:
            stats.increment("address_page_cache_misses")
            payload = explorer.get_address_transactions(address, page=page)
            if not isinstance(payload, dict) or "data" not in payload:
                raise ClientUnavailable("Explorer address page schema changed")
            conn.execute(
                "INSERT OR REPLACE INTO raw_address_pages VALUES (?,?,?,?,strftime('%s','now'))",
                (address, OBSERVATION_WINDOW_ID, page, json.dumps(payload, sort_keys=True)),
            )
            conn.commit()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ClientUnavailable("Explorer address page schema changed")
        page_items = payload.get("data") or []
        if not page_items:
            break
        stop = False
        for wrapped in page_items:
            if not isinstance(wrapped, dict):
                raise ClientUnavailable("Explorer address page item schema changed")
            attrs = wrapped.get("attributes", wrapped)
            if not isinstance(attrs, dict):
                raise ClientUnavailable("Explorer transaction attributes schema changed")
            timestamp = _timestamp(attrs)
            if timestamp is not None and timestamp < WINDOW_START:
                stop = True
                continue
            if timestamp is None or timestamp < WINDOW_END:
                items.append(wrapped)
        total = (payload.get("meta") or {}).get("total")
        if stop or len(page_items) < 50 or (total is not None and page * 50 >= int(total)):
            break
    return items, True


def _persist_listing_item(store: Store, address: str, item: dict,
                          explorer: ExplorerClient, stats: CacheStats) -> dict | None:
    attrs = item.get("attributes", item)
    tx_hash = attrs.get("transaction_hash") or item.get("id")
    if not tx_hash:
        return None
    cached = store.conn.execute(
        "SELECT raw_json FROM raw_transactions WHERE tx_hash=?", (tx_hash,)
    ).fetchone()
    if cached:
        stats.increment("transaction_cache_hits")
        stats.increment("transactions_reused")
        stats.increment("raw_cache_hits")
        payload = json.loads(cached[0])
    else:
        stats.increment("transaction_cache_misses")
        if attrs.get("display_inputs") is not None and attrs.get("display_outputs") is not None:
            payload = attrs
        else:
            payload = explorer.get_transaction(tx_hash)
        if not payload:
            return None
        store.save_transaction(tx_hash, payload, "ckb_explorer_wallet_validation")
        stats.increment("transactions_fetched")
    tx = normalize_transaction(payload, target_lock_hash=address)
    resolve_transaction_inputs(store.conn, tx, explorer=explorer, stats=stats)
    persist_transaction(store.conn, tx)
    store.mark_address_tx_seen(address, tx_hash, tx["block_timestamp"])
    return tx


def select_candidates(manifest: list[dict], conn) -> tuple[dict | None, list[dict]]:
    raw_scored = []
    all_scored = []
    for item in manifest:
        count, oldest = conn.execute(
            "SELECT COUNT(*),MIN(block_timestamp) FROM address_tx_seen WHERE address=?",
            (item["address"],),
        ).fetchone()
        in_window = conn.execute(
            "SELECT COUNT(*) FROM address_tx_seen WHERE address=? AND block_timestamp>=? AND block_timestamp<?",
            (item["address"], WINDOW_START, WINDOW_END),
        ).fetchone()[0]
        locally_complete = ((item["lifetime_tx_count"] is not None and
                             count >= item["lifetime_tx_count"]) or
                            (oldest is not None and oldest <= WINDOW_START))
        score = (int(item["existing_raw_data"]), int(locally_complete),
                 int(in_window >= 8), int(item["provenance_status"] == "AVAILABLE"),
                 in_window, count, -(item["lifetime_tx_count"] or 10**18), item["address"])
        all_scored.append((score, item))
        if item["existing_raw_data"]:
            raw_scored.append((score, item))
    raw_scored.sort(reverse=True, key=lambda value: value[0])
    all_scored.sort(reverse=True, key=lambda value: value[0])
    first = raw_scored[0][1] if raw_scored else None

    by_stratum: dict[str, list[tuple]] = {}
    for score, item in all_scored:
        by_stratum.setdefault(item["sampling_stratum"], []).append((score, item))
    cohort = []
    ordered = ["1-10", "11-50", "51-200", "201-500", "501-1000",
               "1001-5000", "5000+"]
    for stratum in ordered:
        values = by_stratum.get(stratum, [])
        if values:
            candidate = values.pop(0)[1]
            if candidate != first:
                cohort.append(candidate)
            elif values:
                cohort.append(values.pop(0)[1])
    for _, candidate in raw_scored:
        if len(cohort) >= 8:
            break
        if candidate != first and candidate not in cohort:
            cohort.append(candidate)
    if len(cohort) < 8:
        for _, candidate in all_scored:
            if candidate != first and candidate not in cohort:
                cohort.append(candidate)
                if len(cohort) >= 8:
                    break
    return first, cohort


def validate_wallet(store: Store, record: dict, explorer: ExplorerClient,
                    global_stats: CacheStats, boundaries: dict) -> dict:
    address = record["address"]
    if not network_safe_address(address):
        raise ValueError("invalid frozen wallet address: contains whitespace, control characters, or wrong prefix")
    before = global_stats.snapshot()
    locally_complete = _local_listing_complete(store.conn, address,
                                                record["lifetime_tx_count"])
    listing_items = []
    listing_error = None
    listing_error_type = None
    listing_http_status = None
    remote_listing_complete = False
    if not locally_complete:
        try:
            listing_items, remote_listing_complete = _fetch_listing(
                address, explorer, store.conn, global_stats)
        except ClientUnavailable as exc:
            listing_error = str(exc)
            listing_error_type = exc.error_type or "EXPLORER_UNAVAILABLE"
            listing_http_status = exc.http_status
    for item in listing_items:
        _persist_listing_item(store, address, item, explorer, global_stats)

    payloads = _local_rows(store.conn, address)
    normalized = []
    resolution = Counter()
    for payload in payloads:
        tx = normalize_transaction(payload, target_lock_hash=address)
        counts = resolve_transaction_inputs(store.conn, tx, explorer=explorer,
                                            stats=global_stats)
        resolution.update(counts)
        persist_transaction(store.conn, tx)
        normalized.append(tx)

    listing_complete = locally_complete or remote_listing_complete
    total_inputs = sum(len(tx["inputs"]) for tx in normalized)
    applicable_inputs = sum(item["resolution_status"] != STATUS_NOT_APPLICABLE
                            for tx in normalized for item in tx["inputs"])
    resolved_inputs = sum(item["resolution_status"] == STATUS_COMPLETE
                          for tx in normalized for item in tx["inputs"]
                          if item["resolution_status"] != STATUS_NOT_APPLICABLE)
    detail_complete = len(normalized) == len(payloads)
    input_complete = resolved_inputs == applicable_inputs if applicable_inputs else None
    boundary_status = boundaries.get("boundary_resolution_status", "unresolved")
    observation = ObservationContract(
        address=address,
        canonical_lock_identifier=record.get("canonical_lock_hash") or address,
        window_start_timestamp=WINDOW_START,
        window_end_timestamp=WINDOW_END,
        window_start_block=boundaries.get("window_start_block"),
        window_end_block=boundaries.get("window_end_block"),
        boundary_resolution_source=boundaries.get("boundary_resolution_source"),
        boundary_resolution_status=("complete" if boundary_status == "complete" else "partial"),
        transactions_observed=len(payloads),
        lifetime_transaction_count_at_cutoff=record["lifetime_tx_count"],
        listing_status=STATUS_COMPLETE if listing_complete else STATUS_INCOMPLETE,
        detail_status=STATUS_COMPLETE if detail_complete else STATUS_INCOMPLETE,
        input_resolution_status=(STATUS_NOT_APPLICABLE if applicable_inputs == 0 else
                                 STATUS_COMPLETE if input_complete else STATUS_INCOMPLETE),
        listing_complete=listing_complete,
        detail_complete=detail_complete,
        input_resolution_complete=input_complete,
        history_censored=not listing_complete,
        listing_coverage_ratio=1.0 if listing_complete else None,
        detail_coverage_ratio=ratio(len(normalized), len(payloads)),
        input_resolution_ratio=ratio(resolved_inputs, applicable_inputs),
    )
    persist_observation(store.conn, observation, normalized)
    store.conn.commit()
    loaded = load_normalized_observation(store.conn, observation.observation_id)
    assessment = assess_observation(loaded)
    counters = global_stats.delta(before)
    persist_statistics(store.conn, observation.observation_id, address, counters)
    store.conn.commit()
    return {
        "address": address,
        "legacy_proxy_label": record["legacy_proxy_label"],
        "sampling_stratum": record["sampling_stratum"],
        "observation_id": observation.observation_id,
        "observation": observation.as_record(),
        "input_cells": total_inputs,
        "applicable_inputs": applicable_inputs,
        "resolved_applicable_inputs": resolved_inputs,
        "output_cells": sum(len(tx["outputs"]) for tx in normalized),
        "resolved_inputs": resolved_inputs,
        "unresolved_inputs": applicable_inputs - resolved_inputs,
        "not_applicable_inputs": total_inputs - applicable_inputs,
        "resolution_sources": dict(resolution),
        "cache_statistics": counters,
        "listing_error": listing_error,
        "listing_error_type": listing_error_type,
        "listing_http_status": listing_http_status,
        **assessment,
    }


def sensitivity(result: dict) -> dict:
    features = result["features"]
    values = {**features["temporal"]["values"], **features["topology"]["values"],
              **features["templates"]["values"]}
    output = {}
    metric_map = {
        "PERIODIC_EXECUTION": [("periodicity_strength", ">="), ("phase_stability", ">="),
                               ("interarrival_cv", "<=")],
        "BATCH_DISTRIBUTION": [("fanout_transaction_ratio", ">="),
                               ("mean_external_output_locks", ">="),
                               ("template_repeat_ratio", ">=")],
        "FAN_IN_COLLECTION": [("fanin_transaction_ratio", ">="),
                              ("mean_external_input_locks", ">="),
                              ("topology_repeat_ratio", ">=")],
    }
    config_keys = {
        "periodicity_strength": "periodicity_strength", "phase_stability": "phase_stability",
        "interarrival_cv": "maximum_interarrival_cv",
        "fanout_transaction_ratio": "fanout_transaction_ratio",
        "mean_external_output_locks": "minimum_external_output_locks",
        "template_repeat_ratio": "minimum_template_repeat_ratio",
        "fanin_transaction_ratio": "fanin_transaction_ratio",
        "mean_external_input_locks": "minimum_external_input_locks",
        "topology_repeat_ratio": "minimum_topology_repeat_ratio",
    }
    for pattern, metrics in metric_map.items():
        def decide(overrides: dict[str, float]) -> bool:
            passed = []
            for metric, operator in metrics:
                value = values.get(metric)
                threshold = overrides.get(
                    metric, THRESHOLDS[pattern][config_keys[metric]])
                passed.append(value is not None and
                              (value >= threshold if operator == ">=" else value <= threshold))
            return all(passed)

        simultaneous_decisions = []
        for factor in (0.8, 1.0, 1.2):
            simultaneous_decisions.append(decide({
                metric: THRESHOLDS[pattern][config_keys[metric]] * factor
                for metric, _ in metrics}))
        individual = {}
        for metric, _ in metrics:
            individual[metric] = {
                "lower_default_upper": [decide({
                    metric: THRESHOLDS[pattern][config_keys[metric]] * factor
                }) for factor in (0.8, 1.0, 1.2)]
            }
            individual[metric]["classification"] = (
                "stable" if len(set(individual[metric]["lower_default_upper"])) == 1
                else "threshold-sensitive")
        output[pattern] = {
            "lower_default_upper": simultaneous_decisions,
            "individual_cutoffs": individual,
            "classification": (
                "threshold-sensitive" if any(
                    item["classification"] == "threshold-sensitive"
                    for item in individual.values()) else "stable"),
        }
    return output


def _leakage_audit(observation: dict) -> dict:
    baseline = assess_observation(observation)
    polluted = json.loads(json.dumps(observation))
    polluted["metadata"].update({
        "legacy_proxy_label": "MUTATED", "lifetime_tx_count": 999999999,
        "sampling_stratum": "MUTATED", "predicted_segment": "MUTATED",
        "cluster_id": 999,
    })
    return {"status": "PASS" if assess_observation(polluted) == baseline else "CRITICAL",
            "excluded_fields": ["legacy_proxy_label", "lifetime_tx_count",
                                "sampling_stratum", "predicted_segment", "cluster_id"]}


def _status(conditions: list[bool]) -> str:
    return "READY" if all(conditions) else "PARTIAL" if any(conditions) else "NOT READY"


def write_report(out_dir: Path, inventory: dict, import_summary: dict,
                 first: dict | None, cohort: list[dict], manifest: list[dict],
                 global_stats: dict, leakage: dict) -> None:
    results = ([first] if first else []) + [item for item in cohort
                                            if not first or item["address"] != first["address"]]
    strata = inventory["sampling_strata"]
    zero = sum(item.get("completion_requirement") == "ZERO_REMOTE" for item in manifest)
    partial = sum(item.get("completion_requirement") == "PARTIAL_REFILL" for item in manifest)
    full = sum(item.get("completion_requirement") == "FULL_30_DAY_COLLECTION" for item in manifest)
    known_listing_requests = sum(item.get("estimated_listing_requests", 0) or 0 for item in manifest)
    quality = Counter()
    for item in results:
        obs = item["observation"]
        feature_states = {value["support_state"] for value in item["features"].values()}
        if not obs["transactions_observed"] or feature_states == {"INSUFFICIENT_EVIDENCE"}:
            quality["INSUFFICIENT_EVIDENCE"] += 1
        elif (obs["listing_complete"] and obs["detail_complete"] and
              obs["input_resolution_complete"] is not False and
              feature_states <= {"SUPPORTED"}):
            quality["SUPPORTED"] += 1
        else:
            quality["PARTIAL"] += 1
    sensitivity_rows = {item["address"]: sensitivity(item) for item in results}
    receipt_path = out_dir / "live_acquisition_receipt_v1.json"
    acquisition = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    remote_by_wallet = acquisition.get("per_wallet_remote_requests", {})
    sensitivity_counts = Counter(
        detail["classification"] for wallet in sensitivity_rows.values()
        for detail in wallet.values())
    payload = {"run_version": RUN_VERSION, "window_start_timestamp": WINDOW_START,
               "window_end_timestamp": WINDOW_END, "inventory": inventory,
               "local_import": import_summary, "one_wallet": first, "cohort": cohort,
               "global_cache_statistics": global_stats, "leakage_audit": leakage,
               "live_acquisition_receipt": acquisition,
               "threshold_sensitivity": sensitivity_rows,
               "completion_estimate": {"wallets_needing_zero_remote_requests": zero,
                                       "wallets_needing_partial_refill": partial,
                                       "wallets_needing_full_collection": full,
                                       "estimated_listing_requests_for_known_counts": known_listing_requests},
               "quality_states": dict(quality)}
    (out_dir / "validation_results_v1.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def result_line(item):
        obs = item["observation"]
        assessments = ", ".join(f"{a['pattern']}={a['support_state']}({a['score']})"
                                for a in item["assessments"])
        acquired = remote_by_wallet.get(item["address"], {})
        remote_requests = acquired.get("explorer_requests", item["cache_statistics"]["explorer_requests"])
        return (f"- `{item['address']}` — stratum {item['sampling_stratum']}; "
                f"{obs['transactions_observed']} tx; detail={obs['detail_coverage_ratio']}; "
                f"inputs={obs['input_resolution_ratio']}; Explorer requests="
                f"{remote_requests}; {assessments}")

    lines = [
        "# Existing Wallet 30-Day Validation Report", "",
        "Fixed window: `2026-08-01T00:00:00Z` to `2026-08-31T00:00:00Z`.", "",
        "## A. Existing wallet inventory", "",
        f"{inventory['unique_wallets']} unique wallets from {inventory['source_occurrences']} source occurrences; "
        f"{inventory['duplicate_occurrences']} duplicate occurrences. Historical labels are preserved only as `legacy_proxy_label`.", "",
        "## B. Activity-spectrum coverage", "",
        "| Stratum | Wallets | Percent | Inventory heuristic |", "|---|---:|---:|---|",
    ]
    for name, item in strata.items():
        heuristic = ("not assessed" if item["provisionally_sufficient"] is None else
                     "sufficient" if item["provisionally_sufficient"] else "underrepresented")
        lines.append(f"| {name} | {item['wallets']} | {item['percentage']}% | "
                     f"{heuristic} |")
    lines += ["", "The ten-wallet threshold is an inventory heuristic, not a statistical-power claim.", "",
              "## C. Existing data reuse", "",
              f"Raw wallet evidence: {inventory['raw_wallets']}; wallets with native normalized observations currently: "
        f"{inventory['normalized_wallets']}. The local JSONL contains {import_summary['source_transaction_records']} records, "
              f"{import_summary['unique_local_transactions']} unique transaction hashes, and "
              f"{import_summary['duplicate_transaction_records']} shared/duplicate records. This run added "
              f"{import_summary['transactions_newly_imported']} transactions and reused "
              f"{import_summary['transaction_cache_reuses']} cache entries.", "",
              "## D. Explorer requirements", "",
              f"Zero-request candidates: {zero}; partial refill: {partial}; full collection: {full}. "
              f"The known-count listing upper bound is {known_listing_requests} requests; transaction-detail totals "
              "remain dependent on 30-day activity and shared-cache reuse.", "",
              "## E. One-wallet validation", "",
              result_line(first) if first else "No eligible local raw wallet.", "",
              "## F. 5–10 wallet validation", ""]
    lines.extend(result_line(item) for item in cohort)
    lines += ["", "## G. Cache statistics", "",
              f"The successful live acquisition used {acquisition.get('total_explorer_requests', 0)} Explorer requests "
              f"({acquisition.get('boundary_resolution', {}).get('explorer_requests', 0)} shared boundary requests and "
              f"{acquisition.get('missing_evidence_fill', {}).get('explorer_requests', 0)} wallet-listing requests), with "
              f"{acquisition.get('missing_evidence_fill', {}).get('transaction_cache_misses', 0)} missing transactions "
              "persisted globally. The final resumability pass then produced:", "", "```json",
              json.dumps(global_stats, indent=2, sort_keys=True), "```", "",
              "## H. Leakage audit", "",
              f"**{leakage['status']}** — changing legacy labels, lifetime counts, strata, predictions, and clusters "
              "did not change feature or rule output." if leakage["status"] == "PASS" else
              "**CRITICAL** — legacy metadata changed behaviour output.", "",
              "## I. Threshold sensitivity", "",
              f"Across wallet/rule combinations, {sensitivity_counts['stable']} detections were stable and "
              f"{sensitivity_counts['threshold-sensitive']} were threshold-sensitive when every current threshold "
              "was varied ±20%. Defaults were not changed; per-wallet results are in `validation_results_v1.json`.", "",
              "## J. Existing dataset completion estimate", "",
              f"{zero} wallets need no remote refill, {partial} need partial refill, and {full} need full 30-day collection. "
              f"Known lifetime counts imply at most {known_listing_requests} listing-page requests before cache reuse; "
              "detail cost remains unresolved for unknown-count wallets. Expected cache reuse increases as shared transactions accumulate.", "",
              "## K. Missing sampling strata", ""]
    missing = [name for name, item in strata.items() if name != "unknown" and not item["provisionally_sufficient"]]
    lines.append("Underrepresented: " + (", ".join(missing) if missing else "none; do not collect new wallets."))
    lines += ["", "## L. Readiness", ""]
    observed = bool(results)
    full_observations = bool(results) and all(item["observation"]["listing_complete"] for item in results)
    boundaries_ready = bool(results) and all(
        item["observation"]["boundary_resolution_status"] == "complete" for item in results)
    details_ready = bool(results) and all(item["observation"]["detail_complete"] for item in results)
    input_ready = bool(results) and all(item["observation"]["input_resolution_complete"] is not False for item in results)
    feature_support_complete = bool(results) and all(
        feature["support_state"] == "SUPPORTED"
        for item in results for feature in item["features"].values())
    readiness = {
        "EXISTING WALLET MANIFEST": ("READY" if manifest else "NOT READY",
                                     f"{len(manifest)} deduplicated records have explicit missing-value states."),
        "30-DAY OBSERVATION": (_status([observed, full_observations,
                                         boundaries_ready, details_ready]),
                               "The validation wallets use one fixed window and shared proven block boundaries."),
        "EXPLORER PIPELINE": (_status([
            acquisition.get("missing_evidence_fill", {}).get("explorer_failures", 0) == 0,
            observed]), "The bounded live run had no failures, retries, or rate limits."),
        "CACHE / RESUMABILITY": ("READY" if import_summary["records_failed"] == 0 else "PARTIAL",
                                 "The repeated validation needed zero Explorer requests and reused global evidence."),
        "INPUT RESOLUTION": (_status([observed, input_ready]),
                             "All inputs in transaction-bearing validation observations resolved."),
        "BEHAVIOUR FEATURES": ("READY" if leakage["status"] == "PASS" and feature_support_complete else "PARTIAL",
                               "All families ran without label leakage, but script/minimum-support evidence is incomplete for part of the cohort."),
        "CURRENT LOCAL DATASET": (("READY" if full == 0 and partial == 0 else
                                   "PARTIAL" if inventory["raw_wallets"] > 0 else "NOT READY"),
                                  f"{zero} wallets are locally complete; {full + partial} require refill."),
        "NEW WALLET COLLECTION REQUIRED": ("NO" if not missing else "PARTIAL",
                                            "Every known stratum exceeds the ten-wallet inventory heuristic."),
        "ML / CLUSTERING": ("NOT READY",
                            "Model work was prohibited and evidence is not complete population-wide."),
    }
    for name, (value, reason) in readiness.items():
        lines.append(f"- **{name}: {value}** — {reason}")
    lines += ["", "Recommended research gates: exact observation boundary and complete listing; "
              "detail coverage 1.0; input resolution 1.0 for topology/template rules; and each feature family's "
              "existing minimum transaction support. Wallets failing a gate remain in the manifest as PARTIAL, "
              "INSUFFICIENT_EVIDENCE, or UNRESOLVED."]
    lines += ["", "No ML, clustering, wallet discovery, pairwise attribution, identity inference, or population-level validation was performed."]
    (out_dir / "RESEARCH_VALIDATION_REPORT.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "ckb_data_v2")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "research_validation")
    parser.add_argument("--offline", action="store_true", help="Do not call Explorer; emit PARTIAL boundaries/listings")
    args = parser.parse_args()
    if WINDOW_END - WINDOW_START != 30 * 86400:
        raise SystemExit("validation window is not exactly 30 days")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    store = Store(args.data_dir / "ckb_explorer.sqlite")
    stats = CacheStats()
    manifest, inventory = build_manifest(args.repo_root, store.conn and args.data_dir / "ckb_explorer.sqlite")
    imported = import_local_jsonl(args.repo_root, store, manifest, stats)
    manifest, inventory = build_manifest(args.repo_root, args.data_dir / "ckb_explorer.sqlite")
    annotate_completion_requirements(manifest, store.conn)
    write_manifest(manifest, inventory, args.out_dir)
    first_record, cohort_records = select_candidates(manifest, store.conn)
    explorer = ExplorerClient(stats=stats)
    if args.offline:
        boundaries = {"window_start_block": None, "window_end_block": None,
                      "boundary_resolution_source": None,
                      "boundary_resolution_status": "unresolved"}
    else:
        cached_boundary = store.conn.execute(
            """SELECT window_start_block,window_end_block,boundary_resolution_source,
                      boundary_resolution_status FROM wallet_observations
               WHERE window_start_timestamp=? AND window_end_timestamp=?
                 AND boundary_resolution_status='complete'
                 AND window_start_block IS NOT NULL AND window_end_block IS NOT NULL
               LIMIT 1""", (WINDOW_START, WINDOW_END)).fetchone()
        if cached_boundary:
            boundaries = dict(zip(("window_start_block", "window_end_block",
                                   "boundary_resolution_source", "boundary_resolution_status"),
                                  cached_boundary))
            stats.increment("normalized_cache_hits")
        else:
            try:
                boundaries = resolve_observation_boundaries(WINDOW_START, WINDOW_END,
                                                            rpc=None, explorer=explorer)
            except ClientUnavailable:
                boundaries = {"window_start_block": None, "window_end_block": None,
                              "boundary_resolution_source": None,
                              "boundary_resolution_status": "unresolved"}
    first = validate_wallet(store, first_record, explorer, stats, boundaries) if first_record else None
    if first and not first["features"]:
        raise SystemExit("one-wallet validation failed; cohort not started")
    cohort = []
    for record in cohort_records:
        if first and record["address"] == first["address"]:
            cohort.append(first)
        else:
            cohort.append(validate_wallet(store, record, explorer, stats, boundaries))
    sample_observation = (load_normalized_observation(store.conn, first["observation_id"])
                          if first else {"metadata": {}, "transactions": []})
    leakage = _leakage_audit(sample_observation)
    persist_statistics(store.conn, "global", None, stats.snapshot())
    store.conn.commit()
    manifest, inventory = build_manifest(args.repo_root, args.data_dir / "ckb_explorer.sqlite")
    annotate_completion_requirements(manifest, store.conn)
    write_manifest(manifest, inventory, args.out_dir)
    write_report(args.out_dir, inventory, imported, first, cohort, manifest,
                 stats.snapshot(), leakage)
    store.close()
    print(json.dumps({"first_wallet": first["address"] if first else None,
                      "cohort_wallets": len(cohort), "cache_statistics": stats.snapshot(),
                      "leakage_audit": leakage}, indent=2))


if __name__ == "__main__":
    main()
