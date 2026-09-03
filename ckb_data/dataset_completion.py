"""Resumable completion scheduler for the frozen local CKB wallet population."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import signal
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from ckb_clients import ClientUnavailable, ExplorerClient
from ckb_explorer_pull import Store
from features.base import load_normalized_observation
from features.pipeline import assess_observation
from research_cache import COUNTER_NAMES, CacheStats, persist_statistics
from research_manifest import MANIFEST_VERSION
from validate_existing_wallets import (
    OBSERVATION_WINDOW_ID, POPULATION_VERSION, WINDOW_END, WINDOW_START,
    annotate_completion_requirements, sensitivity, validate_wallet,
)


POPULATION_FIELDS = (
    "address", "canonical_lock_hash", "source_dataset", "source_run",
    "legacy_proxy_label", "lifetime_tx_count", "sampling_stratum",
)
FEATURE_DATASET_VERSION = "ckb-wallet-behaviour-dataset-v1"
DEFAULT_BOUNDARIES = {
    "window_start_block": 20_025_197,
    "window_end_block": 20_311_450,
    "boundary_resolution_source": "explorer",
    "boundary_resolution_status": "complete",
}


SCHEDULER_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_population_meta (
    population_version TEXT PRIMARY KEY,
    population_wallet_count INTEGER NOT NULL,
    manifest_hash TEXT NOT NULL,
    creation_timestamp TEXT NOT NULL,
    source_dataset_versions_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_windows (
    observation_window_id TEXT PRIMARY KEY,
    start_timestamp INTEGER NOT NULL,
    end_timestamp INTEGER NOT NULL,
    start_block INTEGER,
    end_block INTEGER,
    boundary_status TEXT NOT NULL,
    source TEXT,
    CHECK (end_timestamp - start_timestamp = 2592000)
);
CREATE TABLE IF NOT EXISTS wallet_collection_state (
    address TEXT PRIMARY KEY,
    population_version TEXT NOT NULL,
    observation_window_id TEXT NOT NULL,
    completion_category TEXT NOT NULL,
    collection_state TEXT NOT NULL,
    evidence_state TEXT NOT NULL DEFAULT 'UNRESOLVED',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_successful_stage TEXT,
    last_error TEXT,
    last_error_type TEXT,
    last_http_status INTEGER,
    failure_scope TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_checkpoints (
    batch_id TEXT PRIMARY KEY,
    population_version TEXT NOT NULL,
    observation_window_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    wallet_count INTEGER NOT NULL,
    summary_json TEXT,
    stop_reason TEXT
);
"""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def install_scheduler_schema(conn) -> None:
    conn.executescript(SCHEDULER_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(wallet_collection_state)")}
    for name, declaration in (
            ("last_error_type", "TEXT"), ("last_http_status", "INTEGER"),
            ("failure_scope", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE wallet_collection_state ADD COLUMN {name} {declaration}")
    conn.commit()


def load_manifest(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def stable_population_rows(manifest: list[dict]) -> list[dict]:
    return [{key: item.get(key) for key in POPULATION_FIELDS}
            for item in sorted(manifest, key=lambda value: value["address"])]


def population_hash(rows: list[dict]) -> str:
    encoded = "\n".join(json.dumps(item, sort_keys=True, separators=(",", ":"))
                         for item in rows)
    return hashlib.sha256(encoded.encode()).hexdigest()


def freeze_contracts(conn, manifest: list[dict], out_dir: Path) -> dict:
    install_scheduler_schema(conn)
    rows = stable_population_rows(manifest)
    digest = population_hash(rows)
    existing = conn.execute(
        "SELECT population_wallet_count,manifest_hash,creation_timestamp,source_dataset_versions_json "
        "FROM research_population_meta "
        "WHERE population_version=?", (POPULATION_VERSION,)).fetchone()
    if existing and existing[:2] != (len(rows), digest):
        raise RuntimeError("frozen research population changed")
    sources = sorted({source for item in manifest for source in item.get("source_dataset", [])})
    created = utc_now()
    conn.execute("INSERT OR IGNORE INTO research_population_meta VALUES (?,?,?,?,?)",
                 (POPULATION_VERSION, len(rows), digest, created,
                  json.dumps({source: MANIFEST_VERSION for source in sources}, sort_keys=True)))
    stored = conn.execute(
        "SELECT creation_timestamp,source_dataset_versions_json FROM research_population_meta "
        "WHERE population_version=?", (POPULATION_VERSION,)).fetchone()
    stored_created, stored_sources_json = stored
    conn.execute("INSERT OR IGNORE INTO observation_windows VALUES (?,?,?,?,?,?,?)",
                 (OBSERVATION_WINDOW_ID, WINDOW_START, WINDOW_END,
                  DEFAULT_BOUNDARIES["window_start_block"], DEFAULT_BOUNDARIES["window_end_block"],
                  "complete", "explorer"))
    window = conn.execute(
        "SELECT start_timestamp,end_timestamp,start_block,end_block,boundary_status "
        "FROM observation_windows WHERE observation_window_id=?", (OBSERVATION_WINDOW_ID,)
    ).fetchone()
    expected = (WINDOW_START, WINDOW_END, DEFAULT_BOUNDARIES["window_start_block"],
                DEFAULT_BOUNDARIES["window_end_block"], "complete")
    if window != expected:
        raise RuntimeError("frozen observation window changed")
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = out_dir / "population_manifest_v1.jsonl"
    if snapshot_path.exists():
        prior = [json.loads(line) for line in snapshot_path.read_text().splitlines() if line.strip()]
        if population_hash(prior) != digest:
            raise RuntimeError("population snapshot does not match frozen hash")
    else:
        snapshot_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in rows))
    meta = {"research_population_version": POPULATION_VERSION,
            "population_wallet_count": len(rows), "manifest_hash": digest,
            "creation_timestamp": stored_created,
            "source_dataset_versions": json.loads(stored_sources_json)}
    (out_dir / "population_contract_v1.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n")
    (out_dir / "observation_window_v1.json").write_text(json.dumps({
        "observation_window_id": OBSERVATION_WINDOW_ID,
        "observation_start_timestamp": WINDOW_START,
        "observation_end_timestamp": WINDOW_END,
        "observation_start_block": DEFAULT_BOUNDARIES["window_start_block"],
        "observation_end_block": DEFAULT_BOUNDARIES["window_end_block"],
        "boundary_status": "complete", "source": "explorer",
    }, indent=2, sort_keys=True) + "\n")
    conn.commit()
    return meta


def _existing_observation_state(conn, address: str) -> tuple[str, str, str | None]:
    row = conn.execute(
        """SELECT observation_id,boundary_resolution_status,listing_complete,
                  detail_complete,input_resolution_complete,transactions_observed
           FROM wallet_observations WHERE address=? AND window_start_timestamp=?
             AND window_end_timestamp=? ORDER BY collection_timestamp DESC LIMIT 1""",
        (address, WINDOW_START, WINDOW_END)).fetchone()
    if not row:
        return "NOT_STARTED", "UNRESOLVED", None
    observation_id, boundary, listing, detail, inputs, tx_count = row
    if boundary == "complete" and listing == 1 and detail == 1 and inputs in (None, 1):
        evidence = "INSUFFICIENT_EVIDENCE" if not tx_count else "SUPPORTED"
        return "COMPLETE", evidence, observation_id
    if listing or detail or tx_count:
        return "PARTIAL", "PARTIAL", observation_id
    return "FAILED", "UNRESOLVED", observation_id


def recover_interrupted_state(conn) -> dict:
    """Close abandoned checkpoints and make interrupted wallets resumable."""
    now = utc_now()
    batch_ids = [row[0] for row in conn.execute(
        "SELECT batch_id FROM batch_checkpoints WHERE status='IN_PROGRESS'")]
    wallet_count = conn.execute(
        "SELECT COUNT(*) FROM wallet_collection_state WHERE collection_state='IN_PROGRESS'"
    ).fetchone()[0]
    conn.execute("""UPDATE wallet_collection_state
        SET collection_state='PARTIAL',evidence_state='PARTIAL',
            last_error=COALESCE(last_error,'interrupted before checkpoint completion'),
            last_error_type=COALESCE(last_error_type,'INTERRUPTED'),
            failure_scope=COALESCE(failure_scope,'WALLET'),
            updated_at=? WHERE collection_state='IN_PROGRESS'""", (now,))
    conn.execute("""UPDATE batch_checkpoints SET completed_at=?,status='PAUSED',
        stop_reason=COALESCE(stop_reason,'interrupted before checkpoint completion')
        WHERE status='IN_PROGRESS'""", (now,))
    conn.commit()
    return {"recovered_wallets": wallet_count, "paused_batches": batch_ids}


def finalize_exhausted_states(conn, max_attempts: int) -> int:
    """Make terminally incomplete retry-exhausted subjects explicit failures."""
    now = utc_now()
    cursor = conn.execute("""UPDATE wallet_collection_state
        SET collection_state='FAILED_RETRY_EXHAUSTED',
            last_error=COALESCE(last_error,'maximum collection attempts exhausted'),
            last_error_type=COALESCE(last_error_type,'RETRY_EXHAUSTED'),
            failure_scope=COALESCE(failure_scope,'WALLET'),
            updated_at=?
        WHERE collection_state='PARTIAL' AND attempt_count>=?""",
                          (now, max_attempts))
    conn.commit()
    return cursor.rowcount


def initialize_scheduler(conn, manifest: list[dict]) -> None:
    now = utc_now()
    for item in manifest:
        state, evidence, _ = _existing_observation_state(conn, item["address"])
        category = ({"ZERO_REMOTE": "COMPLETE_LOCAL", "PARTIAL_REFILL": "NEEDS_PARTIAL_REFILL",
                     "FULL_30_DAY_COLLECTION": "NEEDS_FULL_REFILL"}
                    [item["completion_requirement"]])
        conn.execute("""INSERT INTO wallet_collection_state
            (address,population_version,observation_window_id,completion_category,
             collection_state,evidence_state,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(address) DO UPDATE SET
                completion_category=excluded.completion_category,
                collection_state=CASE
                    WHEN wallet_collection_state.collection_state='COMPLETE' THEN 'COMPLETE'
                    WHEN excluded.collection_state='COMPLETE' THEN 'COMPLETE'
                    WHEN wallet_collection_state.collection_state='IN_PROGRESS' THEN 'PARTIAL'
                    WHEN wallet_collection_state.collection_state IN
                        ('PARTIAL','FAILED','FAILED_RETRY_EXHAUSTED',
                         'FAILED_INVALID_ADDRESS','UNRESOLVED')
                        THEN wallet_collection_state.collection_state
                    ELSE excluded.collection_state END,
                evidence_state=CASE
                    WHEN wallet_collection_state.collection_state IN
                        ('COMPLETE','PARTIAL','FAILED','FAILED_RETRY_EXHAUSTED',
                         'FAILED_INVALID_ADDRESS','UNRESOLVED')
                        THEN wallet_collection_state.evidence_state
                    ELSE excluded.evidence_state END,
                updated_at=excluded.updated_at""",
            (item["address"], POPULATION_VERSION, OBSERVATION_WINDOW_ID,
             category, state, evidence, now))
    conn.commit()


def next_wallets(conn, limit: int, max_attempts: int = 3) -> list[str]:
    return [row[0] for row in conn.execute(
        """SELECT address FROM wallet_collection_state
           WHERE population_version=? AND observation_window_id=?
             AND collection_state='NOT_STARTED'
             AND attempt_count < ?
           ORDER BY CASE completion_category WHEN 'COMPLETE_LOCAL' THEN 0
                    WHEN 'NEEDS_PARTIAL_REFILL' THEN 1 ELSE 2 END,
                    attempt_count,address LIMIT ?""",
        (POPULATION_VERSION, OBSERVATION_WINDOW_ID, max_attempts, limit))]


def migrate_legacy_failure_states(conn) -> int:
    cursor = conn.execute("""UPDATE wallet_collection_state
        SET collection_state=CASE
                WHEN lower(COALESCE(last_error,'')) LIKE '%invalid frozen wallet address%'
                    THEN 'FAILED_INVALID_ADDRESS'
                ELSE 'FAILED_RETRY_EXHAUSTED' END,
            last_error_type=COALESCE(last_error_type,
                CASE WHEN lower(COALESCE(last_error,'')) LIKE '%invalid frozen wallet address%'
                     THEN 'INVALID_ADDRESS' ELSE 'RETRY_EXHAUSTED' END),
            failure_scope=COALESCE(failure_scope,'WALLET')
        WHERE collection_state='FAILED'""")
    conn.commit()
    return cursor.rowcount


def evidence_state(result: dict) -> str:
    observation = result["observation"]
    if observation["boundary_resolution_status"] != "complete":
        return "UNRESOLVED"
    if not observation["listing_complete"] or not observation["detail_complete"]:
        return "PARTIAL"
    if observation["input_resolution_complete"] is False:
        return "PARTIAL"
    if not observation["transactions_observed"]:
        return "INSUFFICIENT_EVIDENCE"
    states = {feature["support_state"] for feature in result["features"].values()}
    return "SUPPORTED" if states == {"SUPPORTED"} else "PARTIAL"


def safety_check(conn, summary: dict, config: dict) -> str | None:
    requests = summary["statistics"]["explorer_requests"]
    global_failures = summary.get("global_request_failures", 0)
    rate_limits = summary["statistics"]["rate_limit_events"]
    if (global_failures and requests and
            global_failures / requests > config["max_global_failure_rate"]):
        return f"global request failure rate {global_failures / requests:.1%} exceeded threshold"
    if (rate_limits >= config["max_rate_limit_events"] or
            requests >= 10 and rate_limits / requests > config["max_rate_limit_rate"]):
        return "persistent Explorer rate limiting"
    attempted = summary["wallets_attempted"]
    wallet_failures = summary.get("wallet_network_failures", 0)
    successes = summary["statistics"]["explorer_successes"]
    if (attempted >= config["outage_min_wallets"] and successes == 0 and
            wallet_failures / attempted >= config["outage_wallet_failure_rate"]):
        return "widespread Explorer service outage"
    parser_failures = summary.get("parser_failures", 0)
    if (attempted >= 3 and parser_failures / attempted > config["max_parser_failure_rate"]):
        return "unexpected parser/normalization failure rate"
    if (summary["transaction_bearing_wallets"] and
            summary["mean_input_resolution"] is not None and
            summary["mean_input_resolution"] < config["minimum_input_resolution"]):
        return "input-resolution degradation"
    if summary["detail_incomplete"] / max(summary["wallets_attempted"], 1) > config["max_detail_failure_rate"]:
        return "large rise in failed transaction details"
    if summary["boundary_inconsistent"]:
        return "boundary inconsistency"
    integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
    if integrity != "ok":
        return f"database integrity error: {integrity}"
    return None


def run_batch(store: Store, manifest_by_address: dict[str, dict], addresses: list[str],
              explorer: ExplorerClient, stats: CacheStats, out_dir: Path,
              config: dict) -> dict:
    started_monotonic = time.monotonic()
    started = utc_now()
    batch_id = "batch-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    before = stats.snapshot()
    store.conn.execute("INSERT INTO batch_checkpoints VALUES (?,?,?,?,?,?,?,?,?)",
                       (batch_id, POPULATION_VERSION, OBSERVATION_WINDOW_ID, started,
                        None, "IN_PROGRESS", len(addresses), None, None))
    store.conn.commit()
    completed = partial = failed = detail_incomplete = boundary_inconsistent = 0
    wallet_terminal_failures = wallet_network_failures = 0
    parser_failures = global_request_failures = 0
    total_inputs = applicable_inputs = resolved_applicable_inputs = 0
    unresolved_applicable_inputs = not_applicable_inputs = 0
    input_ratios = []
    transaction_bearing = 0
    wallet_results = []
    current_address = None
    interrupted_reason = None
    fatal_reason = None
    try:
        for address in addresses:
            current_address = address
            now = utc_now()
            store.conn.execute("""UPDATE wallet_collection_state SET collection_state='IN_PROGRESS',
                attempt_count=attempt_count+1,last_attempt_at=?,last_successful_stage='SCHEDULED',
                last_error=NULL,last_error_type=NULL,last_http_status=NULL,failure_scope=NULL,
                updated_at=? WHERE address=?""", (now, now, address))
            store.conn.commit()
            try:
                result = validate_wallet(store, manifest_by_address[address], explorer, stats,
                                         DEFAULT_BOUNDARIES)
                observation = result["observation"]
                listing_error = result.get("listing_error")
                if listing_error:
                    final_state = ("PARTIAL" if observation["transactions_observed"]
                                   else "FAILED_RETRY_EXHAUSTED")
                else:
                    final_state = ("COMPLETE" if observation["listing_complete"] and
                                   observation["detail_complete"] and
                                   observation["input_resolution_complete"] is not False and
                                   observation["boundary_resolution_status"] == "complete"
                                   else "PARTIAL")
                ev_state = evidence_state(result)
                completed += final_state == "COMPLETE"
                partial += final_state == "PARTIAL"
                failed += final_state.startswith("FAILED")
                wallet_terminal_failures += final_state.startswith("FAILED")
                wallet_network_failures += bool(listing_error and final_state.startswith("FAILED"))
                detail_incomplete += observation["detail_complete"] is not True
                boundary_inconsistent += not (
                    observation["window_start_block"] == DEFAULT_BOUNDARIES["window_start_block"] and
                    observation["window_end_block"] == DEFAULT_BOUNDARIES["window_end_block"])
                if observation["transactions_observed"]:
                    transaction_bearing += 1
                    if observation["input_resolution_ratio"] is not None:
                        input_ratios.append(observation["input_resolution_ratio"])
                total_inputs += result.get("input_cells", 0)
                applicable_inputs += result.get("applicable_inputs", 0)
                resolved_applicable_inputs += result.get("resolved_applicable_inputs", 0)
                unresolved_applicable_inputs += result.get("unresolved_inputs", 0)
                not_applicable_inputs += result.get("not_applicable_inputs", 0)
                store.conn.execute("""UPDATE wallet_collection_state SET collection_state=?,
                    evidence_state=?,last_successful_stage=?,last_error=?,last_error_type=?,
                    last_http_status=?,failure_scope=?,updated_at=? WHERE address=?""",
                    (final_state, ev_state,
                     "FEATURES_EXPORTED" if final_state == "COMPLETE" else "OBSERVATION_PARTIAL",
                     listing_error, result.get("listing_error_type"),
                     result.get("listing_http_status"), "WALLET" if listing_error else None,
                     utc_now(), address))
                wallet_results.append({"address": address, "state": final_state,
                                       "evidence_state": ev_state,
                                       "transactions": observation["transactions_observed"],
                                       "detail_coverage": observation["detail_coverage_ratio"],
                                       "input_resolution": observation["input_resolution_ratio"],
                                       "error_type": result.get("listing_error_type"),
                                       "http_status": result.get("listing_http_status")})
            except Exception as exc:
                permanent_invalid = "invalid frozen wallet address" in str(exc).lower()
                cache_failure = "cache corruption" in str(exc).lower()
                schema_failure = "schema" in str(exc).lower() or "population" in str(exc).lower()
                parser_failure = (not permanent_invalid and
                                  isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)))
                if permanent_invalid:
                    final_state, error_type, failure_scope = (
                        "FAILED_INVALID_ADDRESS", "INVALID_ADDRESS", "WALLET")
                elif isinstance(exc, ClientUnavailable):
                    cached_evidence = store.conn.execute(
                        "SELECT COUNT(*) FROM address_tx_seen WHERE address=? AND "
                        "block_timestamp>=? AND block_timestamp<?",
                        (address, WINDOW_START, WINDOW_END)).fetchone()[0]
                    final_state = "PARTIAL" if cached_evidence else "FAILED_RETRY_EXHAUSTED"
                    error_type = exc.error_type or "EXPLORER_UNAVAILABLE"
                    failure_scope = "WALLET"
                else:
                    final_state = "UNRESOLVED"
                    error_type = ("CACHE_CORRUPTION" if cache_failure else
                                  "SCHEMA_INCOMPATIBILITY" if schema_failure else
                                  "PARSER_NORMALIZATION_ERROR" if parser_failure else
                                  "UNEXPECTED_COLLECTION_ERROR")
                    failure_scope = "GLOBAL"
                failed += final_state != "PARTIAL"
                partial += final_state == "PARTIAL"
                wallet_terminal_failures += failure_scope == "WALLET" and final_state != "PARTIAL"
                wallet_network_failures += isinstance(exc, ClientUnavailable)
                parser_failures += parser_failure
                global_request_failures += failure_scope == "GLOBAL"
                store.conn.execute("""UPDATE wallet_collection_state SET collection_state=?,
                    evidence_state=?,last_error=?,last_error_type=?,last_http_status=?,
                    failure_scope=?,attempt_count=CASE WHEN ? THEN ? ELSE attempt_count END,
                    updated_at=? WHERE address=?""",
                    (final_state, "PARTIAL" if final_state == "PARTIAL" else "UNRESOLVED",
                     str(exc), error_type, getattr(exc, "http_status", None), failure_scope,
                     permanent_invalid, config["max_wallet_attempts"], utc_now(), address))
                wallet_results.append({"address": address, "state": final_state,
                                       "error": str(exc), "error_type": error_type,
                                       "http_status": getattr(exc, "http_status", None)})
                if failure_scope == "GLOBAL":
                    fatal_reason = f"global collection failure: {error_type}: {exc}"
                    store.conn.commit()
                    break
            store.conn.commit()
            current_address = None
            progress_delta = stats.delta(before)
            progress_summary = {
                "wallets_attempted": len(wallet_results),
                "transaction_bearing_wallets": transaction_bearing,
                "detail_incomplete": detail_incomplete,
                "boundary_inconsistent": boundary_inconsistent,
                "mean_input_resolution": (statistics.mean(input_ratios)
                                          if input_ratios else None),
                "wallet_terminal_failures": wallet_terminal_failures,
                "wallet_network_failures": wallet_network_failures,
                "parser_failures": parser_failures,
                "global_request_failures": global_request_failures,
                "statistics": progress_delta,
            }
            progress_stop = safety_check(store.conn, progress_summary, config)
            if progress_stop:
                fatal_reason = progress_stop
                break
    except KeyboardInterrupt:
        interrupted_reason = "collection interrupted; durable cache and wallet progress preserved"
        if current_address is not None:
            partial += 1
            store.conn.execute("""UPDATE wallet_collection_state SET collection_state='PARTIAL',
                evidence_state='PARTIAL',last_error=?,last_error_type='INTERRUPTED',
                failure_scope='WALLET',updated_at=? WHERE address=?""",
                               (interrupted_reason, utc_now(), current_address))
            wallet_results.append({"address": current_address, "state": "PARTIAL",
                                   "error": interrupted_reason})
        store.conn.commit()
    delta = stats.delta(before)
    state_counts = dict(store.conn.execute(
        "SELECT collection_state,count(*) FROM wallet_collection_state GROUP BY collection_state"))
    attempted = len(wallet_results)
    requests = delta["explorer_requests"]
    transaction_total = delta["transactions_fetched"] + delta["transactions_reused"]
    integrity = store.conn.execute("PRAGMA quick_check").fetchone()[0]
    summary = {
        "batch_id": batch_id, "started_at": started, "completed_at": utc_now(),
        "wallets_attempted": len(wallet_results), "wallets_completed": completed,
        "wallets_partial": partial, "wallets_failed": failed,
        "transaction_bearing_wallets": transaction_bearing,
        "detail_incomplete": detail_incomplete,
        "boundary_inconsistent": boundary_inconsistent,
        "mean_input_resolution": statistics.mean(input_ratios) if input_ratios else None,
        "total_inputs": total_inputs, "applicable_inputs": applicable_inputs,
        "resolved_applicable_inputs": resolved_applicable_inputs,
        "unresolved_applicable_inputs": unresolved_applicable_inputs,
        "not_applicable_inputs": not_applicable_inputs,
        "wallet_terminal_failures": wallet_terminal_failures,
        "wallet_network_failures": wallet_network_failures,
        "parser_failures": parser_failures,
        "global_request_failures": global_request_failures,
        "global_request_failure_rate": global_request_failures / requests if requests else 0.0,
        "wallet_terminal_failure_rate": wallet_terminal_failures / attempted if attempted else 0.0,
        "rate_limit_rate": delta["rate_limit_events"] / requests if requests else 0.0,
        "parser_failure_rate": parser_failures / attempted if attempted else 0.0,
        "statistics": delta, "transactions_fetched": delta["transactions_fetched"],
        "transactions_reused": delta["transactions_reused"],
        "previous_outputs_resolved": delta["previous_output_cache_hits"],
        "unresolved_previous_outputs": delta["previous_output_cache_misses"],
        "remaining_not_started": state_counts.get("NOT_STARTED", 0),
        "completion_rate": completed / attempted if attempted else 0.0,
        "partial_rate": partial / attempted if attempted else 0.0,
        "terminal_failure_rate": failed / attempted if attempted else 0.0,
        "explorer_requests_per_completed_wallet": requests / completed if completed else None,
        "new_unique_transactions_per_request": (delta["transactions_fetched"] / requests
                                                if requests else None),
        "cache_reuse_ratio": (delta["transactions_reused"] / transaction_total
                              if transaction_total else None),
        "population_attempted_ratio": (1172 - state_counts.get("NOT_STARTED", 0)) / 1172,
        "population_complete_ratio": state_counts.get("COMPLETE", 0) / 1172,
        "population_terminal_ratio": (1172 - state_counts.get("NOT_STARTED", 0)) / 1172,
        "population_state_counts": state_counts,
        "database_integrity": integrity,
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "wallet_results": wallet_results,
    }
    stop_reason = interrupted_reason or fatal_reason or safety_check(store.conn, summary, config)
    summary["safety_stop"] = stop_reason
    status = "PAUSED" if stop_reason else "COMPLETE"
    store.conn.execute("""UPDATE batch_checkpoints SET completed_at=?,status=?,summary_json=?,
        stop_reason=? WHERE batch_id=?""", (summary["completed_at"], status,
                                            json.dumps(summary, sort_keys=True),
                                            stop_reason, batch_id))
    persist_statistics(store.conn, batch_id, None, delta)
    store.conn.commit()
    checkpoint_dir = out_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / f"{batch_id}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def flatten_feature_row(manifest_item: dict, observation: dict | None,
                        assessment: dict | None, collection: dict) -> tuple[dict, dict]:
    row = {
        "wallet": manifest_item["address"],
        "canonical_lock_hash": manifest_item.get("canonical_lock_hash"),
        "population_version": POPULATION_VERSION,
        "observation_window_id": OBSERVATION_WINDOW_ID,
        "observation_contract_version": "wallet-observation-30d-v1",
        "feature_schema_version": "ckb-behaviour-features-v1",
        "rule_version": "ckb-transparent-rules-v1",
        "sampling_stratum": manifest_item["sampling_stratum"],
        "lifetime_tx_count": manifest_item["lifetime_tx_count"],
        "legacy_proxy_label": manifest_item["legacy_proxy_label"],
        "collection_state": collection["collection_state"],
        "evidence_state": collection["evidence_state"],
    }
    evidence = {"wallet": manifest_item["address"], "features": {}, "assessments": []}
    if not observation or not assessment:
        for key in ("transaction_count_30d", "listing_coverage", "detail_coverage",
                    "input_resolution_ratio"):
            row[key] = None
        return row, evidence
    metadata = observation["metadata"]
    row.update({
        "transaction_count_30d": metadata.get("transactions_observed"),
        "observation_boundary_status": metadata.get("boundary_resolution_status"),
        "listing_status": metadata.get("listing_status"),
        "listing_coverage": metadata.get("listing_coverage_ratio"),
        "detail_status": metadata.get("detail_status"),
        "detail_coverage": metadata.get("detail_coverage_ratio"),
        "input_resolution_status": metadata.get("input_resolution_status"),
        "input_resolution_ratio": metadata.get("input_resolution_ratio"),
    })
    for family, result in assessment["features"].items():
        row[f"{family}_support"] = result["support_state"]
        for name, value in result["values"].items():
            if result["support_state"] in {"INSUFFICIENT_EVIDENCE", "UNRESOLVED"}:
                row[f"{family}__{name}"] = None
            else:
                row[f"{family}__{name}"] = (json.dumps(value, sort_keys=True)
                                             if isinstance(value, (dict, list)) else value)
        evidence["features"][family] = result["evidence"]
    for result in assessment["assessments"]:
        prefix = result["pattern"]
        row[f"rule__{prefix}__score"] = result["score"]
        row[f"rule__{prefix}__state"] = result["support_state"]
        evidence["assessments"].append({
            "pattern": prefix, "reason_codes": result["reason_codes"],
            "supporting_transactions": result["supporting_transactions"],
            "feature_values": result["feature_values"], "support": result["support"],
        })
    evidence["threshold_sensitivity"] = sensitivity(assessment)
    return row, evidence


def export_feature_datasets(conn, manifest: list[dict], out_dir: Path) -> dict:
    collection_columns = ["address", "collection_state", "evidence_state", "attempt_count",
                          "last_attempt_at", "last_successful_stage", "last_error",
                          "last_error_type", "last_http_status", "failure_scope"]
    collection_rows = {row[0]: dict(zip(collection_columns, row))
                       for row in conn.execute(
                           "SELECT " + ",".join(collection_columns) +
                           " FROM wallet_collection_state")}
    rows, evidence_rows = [], []
    for item in manifest:
        address = item["address"]
        observation_row = conn.execute(
            """SELECT observation_id FROM wallet_observations WHERE address=?
               AND window_start_timestamp=? AND window_end_timestamp=?
               ORDER BY collection_timestamp DESC LIMIT 1""", (address, WINDOW_START, WINDOW_END)
        ).fetchone()
        observation = assessment = None
        if observation_row:
            observation = load_normalized_observation(conn, observation_row[0])
            assessment = assess_observation(observation)
        row, evidence = flatten_feature_row(item, observation, assessment,
                                            collection_rows[address])
        rows.append(row)
        evidence_rows.append(evidence)
    columns = sorted({key for row in rows for key in row})
    canonical_path = out_dir / "wallet_behaviour_features_canonical_v1.csv"
    with canonical_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    with (out_dir / "wallet_behaviour_evidence_v1.jsonl").open("w") as handle:
        for item in evidence_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    forbidden_exact = {
        "wallet", "canonical_lock_hash", "sampling_stratum", "lifetime_tx_count",
        "legacy_proxy_label", "collection_state", "evidence_state",
        "population_version", "observation_window_id", "observation_contract_version",
        "feature_schema_version", "rule_version", "observation_boundary_status",
        "listing_status", "detail_status", "input_resolution_status",
    }
    predictor_columns = []
    for column in columns:
        observed = [row.get(column) for row in rows if row.get(column) not in (None, "")]
        numeric_only = all(isinstance(value, (int, float)) and not isinstance(value, bool)
                           for value in observed)
        if (column not in forbidden_exact and "support" not in column and
                "coverage" not in column and
                not column.endswith("__state") and
                column not in {"listing_coverage", "detail_coverage",
                               "input_resolution_ratio"} and numeric_only):
            predictor_columns.append(column)
    ml_path = out_dir / "wallet_behaviour_features_ml_v1.csv"
    with ml_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=predictor_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    metadata_path = out_dir / "wallet_behaviour_features_ml_metadata_v1.csv"
    metadata_columns = ["row_id", "wallet", "canonical_lock_hash", "sampling_stratum",
                        "lifetime_tx_count", "legacy_proxy_label", "collection_state",
                        "evidence_state", "observation_window_id"]
    with metadata_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=metadata_columns)
        writer.writeheader()
        for index, row in enumerate(rows):
            writer.writerow({key: index if key == "row_id" else row.get(key)
                             for key in metadata_columns})
    collection_path = out_dir / "wallet_collection_states_v1.csv"
    manifest_by_address = {item["address"]: item for item in manifest}
    state_columns = collection_columns + ["sampling_stratum", "lifetime_tx_count"]
    with collection_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=state_columns)
        writer.writeheader()
        for address in sorted(collection_rows):
            item = dict(collection_rows[address])
            item["sampling_stratum"] = manifest_by_address[address]["sampling_stratum"]
            item["lifetime_tx_count"] = manifest_by_address[address]["lifetime_tx_count"]
            writer.writerow(item)

    retry_path = out_dir / "retry_candidates_v1.csv"
    retry_columns = state_columns + ["failure_category", "recommendation"]
    with retry_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=retry_columns)
        writer.writeheader()
        for address in sorted(collection_rows):
            item = dict(collection_rows[address])
            if item["collection_state"] not in {"PARTIAL", "FAILED_RETRY_EXHAUSTED"}:
                continue
            error_type = item.get("last_error_type") or "OTHER"
            if error_type in {"EXPLORER_TIMEOUT", "EXPLORER_RATE_LIMIT",
                              "EXPLORER_HTTP_ERROR", "EXPLORER_NETWORK_ERROR",
                              "RETRY_EXHAUSTED", "EXPLORER_UNAVAILABLE"}:
                category, recommendation = "Explorer timeout/service", "RETRY_LATER"
            elif error_type in {"CACHE_CORRUPTION", "SCHEMA_INCOMPATIBILITY",
                                "PARSER_NORMALIZATION_ERROR"}:
                category, recommendation = "schema/data issue", "NEEDS_CODE_FIX"
            else:
                category, recommendation = "other", "NEEDS_MANUAL_REVIEW"
            item["sampling_stratum"] = manifest_by_address[address]["sampling_stratum"]
            item["lifetime_tx_count"] = manifest_by_address[address]["lifetime_tx_count"]
            item["failure_category"] = category
            item["recommendation"] = recommendation
            writer.writerow(item)
    return {"rows": rows, "evidence_rows": evidence_rows,
            "predictor_columns": predictor_columns,
            "canonical_path": str(canonical_path), "ml_path": str(ml_path),
            "metadata_path": str(metadata_path),
            "collection_path": str(collection_path), "retry_path": str(retry_path)}


def _numeric(values):
    return [float(value) for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))]


def feature_quality(rows: list[dict]) -> dict:
    feature_columns = sorted({key for row in rows for key in row
                              if "__" in key and not key.endswith("__state")})
    output = {}
    for column in feature_columns:
        values = _numeric([row.get(column) for row in rows])
        missing = len(rows) - len(values)
        if not values:
            output[column] = {"count": 0, "missing": missing, "constant": None}
            continue
        ordered = sorted(values)
        def percentile(p):
            return ordered[round((len(ordered) - 1) * p)]
        counts = Counter(values)
        q1, q3 = percentile(0.25), percentile(0.75)
        iqr = q3 - q1
        outliers = sum(value < q1 - 3 * iqr or value > q3 + 3 * iqr for value in values)
        output[column] = {
            "count": len(values), "missing": missing, "min": min(values), "max": max(values),
            "mean": statistics.mean(values), "median": statistics.median(values),
            "stddev": statistics.pstdev(values), "p05": percentile(0.05),
            "p25": q1, "p75": q3, "p95": percentile(0.95),
            "constant": len(counts) == 1,
            "near_constant": counts.most_common(1)[0][1] / len(values) >= 0.95,
            "extreme_outliers": outliers,
            "impossible_value_count": sum(
                ("ratio" in column or "entropy" in column or "strength" in column or
                 "stability" in column) and not 0 <= value <= 1 for value in values),
        }
    return output


def _distribution(values) -> dict:
    numeric = sorted(_numeric(values))
    if not numeric:
        return {"count": 0, "min": None, "p05": None, "p25": None,
                "median": None, "p75": None, "p95": None, "max": None,
                "mean": None}

    def percentile(p):
        return numeric[round((len(numeric) - 1) * p)]

    return {"count": len(numeric), "min": numeric[0], "p05": percentile(0.05),
            "p25": percentile(0.25), "median": statistics.median(numeric),
            "p75": percentile(0.75), "p95": percentile(0.95),
            "max": numeric[-1], "mean": statistics.mean(numeric)}


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) *
                            sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else None


def coverage_correlations(rows: list[dict]) -> dict:
    features = sorted({key for row in rows for key in row if "__" in key
                       and not key.endswith("__state")})
    output = {}
    for feature in features:
        output[feature] = {}
        for coverage in ("detail_coverage", "input_resolution_ratio"):
            pairs = []
            for row in rows:
                x, y = row.get(feature), row.get(coverage)
                if (isinstance(x, (int, float)) and not isinstance(x, bool) and
                        isinstance(y, (int, float)) and not isinstance(y, bool) and
                        math.isfinite(float(x)) and math.isfinite(float(y))):
                    pairs.append((float(x), float(y)))
            output[feature][coverage] = {"n": len(pairs), "pearson_r": _pearson(pairs)}
    return output


def behaviour_quality(rows: list[dict], evidence_rows: list[dict]) -> dict:
    output = {}
    for pattern in ("PERIODIC_EXECUTION", "BATCH_DISTRIBUTION", "FAN_IN_COLLECTION"):
        score_key, state_key = f"rule__{pattern}__score", f"rule__{pattern}__state"
        sensitivity_counts = Counter()
        decisions = Counter()
        individual_cutoffs: dict[str, Counter] = defaultdict(Counter)
        for evidence in evidence_rows:
            result = evidence.get("threshold_sensitivity", {}).get(pattern)
            if result:
                sensitivity_counts[result["classification"]] += 1
                for factor, decision in zip(("lower", "default", "upper"),
                                            result["lower_default_upper"]):
                    decisions[f"{factor}_{str(decision).lower()}"] += 1
                for metric, metric_result in result.get("individual_cutoffs", {}).items():
                    individual_cutoffs[metric][metric_result["classification"]] += 1
                    for factor, decision in zip(
                            ("lower", "default", "upper"),
                            metric_result["lower_default_upper"]):
                        individual_cutoffs[metric][f"{factor}_{str(decision).lower()}"] += 1
        output[pattern] = {
            "score_distribution": _distribution(row.get(score_key) for row in rows),
            "support_states": dict(Counter(row.get(state_key, "UNRESOLVED") for row in rows)),
            "sensitivity_classifications": dict(sensitivity_counts),
            "sensitivity_decisions": dict(decisions),
            "individual_cutoff_sensitivity": {
                metric: dict(counts) for metric, counts in individual_cutoffs.items()},
        }
    return output


def dataset_quality(conn, exported: dict, manifest: list[dict]) -> dict:
    rows = exported["rows"]
    states = Counter(row["collection_state"] for row in rows)
    evidence = Counter(row["evidence_state"] for row in rows)
    families = ["temporal", "topology", "templates", "scripts", "capacity"]
    support = {family: dict(Counter(row.get(f"{family}_support", "UNRESOLVED") for row in rows))
               for family in families}
    by_stratum = {}
    for stratum in sorted({row["sampling_stratum"] for row in rows}):
        subset = [row for row in rows if row["sampling_stratum"] == stratum]
        def mean_field(name):
            values = _numeric([row.get(name) for row in subset])
            return statistics.mean(values) if values else None
        by_stratum[stratum] = {
            "wallets": len(subset),
            "attempted": sum(row["collection_state"] != "NOT_STARTED" for row in subset),
            "complete": sum(row["collection_state"] == "COMPLETE" for row in subset),
            "partial": sum(row["collection_state"] == "PARTIAL" for row in subset),
            "failed": sum(row["collection_state"].startswith("FAILED") or
                          row["collection_state"] == "UNRESOLVED" for row in subset),
            "not_started": sum(row["collection_state"] == "NOT_STARTED" for row in subset),
            "mean_detail_coverage": mean_field("detail_coverage"),
            "mean_input_resolution": mean_field("input_resolution_ratio"),
            "censored_or_incomplete": sum(row.get("listing_coverage") != 1 for row in subset),
        }
        by_stratum[stratum]["completion_rate_among_attempted"] = (
            by_stratum[stratum]["complete"] / by_stratum[stratum]["attempted"]
            if by_stratum[stratum]["attempted"] else None)
    input_counts = dict(conn.execute("""SELECT i.resolution_status,COUNT(*)
        FROM transaction_inputs i JOIN wallet_transaction_participation p
          ON p.tx_hash=i.tx_hash
        JOIN wallet_observations o ON o.observation_id=p.observation_id
        WHERE o.window_start_timestamp=? AND o.window_end_timestamp=?
        GROUP BY i.resolution_status""", (WINDOW_START, WINDOW_END)))
    applicable = sum(count for status, count in input_counts.items()
                     if status != "not_applicable")
    resolved_applicable = input_counts.get("complete", 0)
    known_rates = [item["completion_rate_among_attempted"] for key, item in by_stratum.items()
                   if key != "unknown" and item["completion_rate_among_attempted"] is not None]
    selection_bias = {
        "methodological_concern": (max(known_rates) - min(known_rates) > 0.20
                                    if len(known_rates) >= 2 else None),
        "completion_rate_range": ([min(known_rates), max(known_rates)]
                                  if known_rates else None),
        "note": "Sampling strata are diagnostics only; failed and partial wallets remain included.",
    }
    quality = {
        "total_wallets": len(rows), "collection_states": dict(states),
        "evidence_states": dict(evidence),
        "transactions_observed": sum(row.get("transaction_count_30d") or 0 for row in rows),
        "feature_support": support, "by_sampling_stratum": by_stratum,
        "feature_quality": feature_quality(rows),
        "coverage_distributions": {
            name: _distribution(row.get(name) for row in rows)
            for name in ("listing_coverage", "detail_coverage", "input_resolution_ratio")
        },
        "feature_coverage_correlations": coverage_correlations(rows),
        "behaviour_quality": behaviour_quality(rows, exported["evidence_rows"]),
        "applicable_input_resolution": {
            "total_inputs": sum(input_counts.values()),
            "applicable_inputs": applicable,
            "not_applicable_cellbase_inputs": input_counts.get("not_applicable", 0),
            "resolved_applicable_inputs": resolved_applicable,
            "unresolved_applicable_inputs": applicable - resolved_applicable,
            "input_resolution_ratio": (resolved_applicable / applicable
                                       if applicable else None),
        },
        "selection_bias": selection_bias,
        "missing_value_matrix": {column: sum(row.get(column) in (None, "") for row in rows)
                                 for column in sorted({key for row in rows for key in row})},
    }
    return quality


def manual_examples(rows: list[dict], evidence_rows: list[dict]) -> dict:
    evidence_by_wallet = {item["wallet"]: item for item in evidence_rows}

    def compact(row: dict, pattern: str) -> dict:
        evidence = next((item for item in evidence_by_wallet[row["wallet"]]
                         .get("assessments", []) if item["pattern"] == pattern), {})
        score = row.get(f"rule__{pattern}__score")
        return {"wallet": row["wallet"], "pattern": pattern, "score": score,
                "support_state": row.get(f"rule__{pattern}__state"),
                "reason_codes": evidence.get("reason_codes", []),
                "supporting_transaction_hashes": evidence.get("supporting_transactions", []),
                "feature_values": evidence.get("feature_values", {}),
                "coverage": evidence.get("support", {}),
                "explanation": (
                    "All configured rule checks passed with direct transaction evidence."
                    if score == 1 and evidence.get("supporting_transactions") else
                    "Score is near the current decision boundary; review the listed feature values and coverage."
                    if score is not None else
                    "The wallet lacks enough supported evidence for a numeric score.")}

    output = {}
    for pattern in ("PERIODIC_EXECUTION", "BATCH_DISTRIBUTION", "FAN_IN_COLLECTION"):
        score_key, state_key = f"rule__{pattern}__score", f"rule__{pattern}__state"
        candidates = [row for row in rows if isinstance(row.get(score_key), (int, float))]
        evidenced = [row for row in candidates if next((item for item in
                     evidence_by_wallet[row["wallet"]].get("assessments", [])
                     if item["pattern"] == pattern), {}).get("supporting_transactions")]
        strong_pool = evidenced or candidates
        strong = sorted(strong_pool, key=lambda row: row[score_key], reverse=True)[:10]
        borderline = sorted(candidates, key=lambda row: abs(row[score_key] - (2 / 3)))[:5]
        output[pattern] = {"strong": [compact(row, pattern) for row in strong],
                           "borderline": [compact(row, pattern) for row in borderline]}
    return output


def write_dataset_reports(conn, exported: dict, manifest: list[dict], out_dir: Path,
                          population_meta: dict) -> dict:
    quality = dataset_quality(conn, exported, manifest)
    examples = manual_examples(exported["rows"], exported["evidence_rows"])
    (out_dir / "dataset_quality_v1.json").write_text(
        json.dumps(quality, indent=2, sort_keys=True) + "\n")
    (out_dir / "manual_review_examples_v1.json").write_text(
        json.dumps(examples, indent=2, sort_keys=True) + "\n")
    checkpoints = [json.loads(row[0]) for row in conn.execute(
        "SELECT summary_json FROM batch_checkpoints WHERE summary_json IS NOT NULL")]
    aggregate_stats = {name: sum(item["statistics"].get(name, 0) for item in checkpoints)
                       for name in COUNTER_NAMES}
    states = quality["collection_states"]
    complete = states.get("COMPLETE", 0)
    not_started = states.get("NOT_STARTED", 0)
    total = quality["total_wallets"]
    population_ready = "READY" if not_started == 0 else "NOT READY"
    dataset_ready = "READY" if complete == total else "PARTIAL" if not_started == 0 else "NOT READY"
    feature_partial = any(values.get("PARTIAL", 0) or values.get("UNRESOLVED", 0)
                          for values in quality["feature_support"].values())
    feature_ready = "PARTIAL" if feature_partial or complete < total else "READY"
    error_groups = dict(conn.execute("""SELECT COALESCE(last_error_type,'UNKNOWN'),COUNT(*)
        FROM wallet_collection_state
        WHERE collection_state IN ('PARTIAL','FAILED_RETRY_EXHAUSTED',
                                    'FAILED_INVALID_ADDRESS','UNRESOLVED')
        GROUP BY COALESCE(last_error_type,'UNKNOWN')"""))
    lines = ["# Existing Dataset Completion Report", "", "## A. Population", "",
             f"- Total wallets: {total}", f"- Population version: `{POPULATION_VERSION}`",
             f"- Manifest hash: `{population_meta['manifest_hash']}`", "",
             "## B. Collection results", "", "```json", json.dumps(states, indent=2), "```", "",
             "## C. Explorer utilization", "", "```json", json.dumps(aggregate_stats, indent=2), "```", "",
             "## D. Observation quality", "",
             f"Transactions observed: {quality['transactions_observed']}. Coverage distributions, feature/coverage correlations, and missingness are in `dataset_quality_v1.json`.", "",
             "Applicable-input resolution (cellbase excluded):", "", "```json",
             json.dumps(quality["applicable_input_resolution"], indent=2), "```", "",
             "## E. Feature readiness", "", "```json", json.dumps(quality["feature_support"], indent=2), "```", "",
             "## F. Behaviour results", "",
             "Population score distributions and independent ±20% threshold sweeps are recorded in `dataset_quality_v1.json`; wallet-level sweep results are in `wallet_behaviour_evidence_v1.jsonl`. Prevalence is not validated while collection is partial.", "",
             "## G. Sampling-stratum diagnostics", "", "```json",
             json.dumps(quality["by_sampling_stratum"], indent=2), "```", "",
             "Selection-bias diagnostic:", "", "```json",
             json.dumps(quality["selection_bias"], indent=2), "```", "",
             "## H. Feature-quality audit", "",
             "Constant/near-constant features, outliers, impossible values, and missingness are in `dataset_quality_v1.json`.", "",
             "## I. ML-safe dataset", "", f"- `{exported['ml_path']}`",
             f"- Companion metadata: `{exported['metadata_path']}`", "",
             "## J. Manual-review evidence set", "", "See `manual_review_examples_v1.json`.", "",
             "Retry candidates are listed in `retry_candidates_v1.csv` and are not executed automatically after the first pass.", "",
             "## K. Dataset readiness decision", "",
             f"- **FROZEN POPULATION ATTEMPTED: {population_ready}** — {total - not_started}/{total} wallets have terminal first-pass states.",
             f"- **DATASET COMPLETENESS: {dataset_ready}** — {complete}/{total} observations are complete.",
             f"- **EXPLORER RELIABILITY: {'READY' if not error_groups else 'PARTIAL'}** — failures by cause: `{json.dumps(error_groups, sort_keys=True)}`.",
             f"- **OBSERVATION QUALITY: {feature_ready}** — incomplete wallets and support limits remain explicit.",
             f"- **FEATURE DATASET: {feature_ready}** — unsupported values remain missing rather than zero.",
             f"- **BEHAVIOUR ANALYSIS: {feature_ready}** — conclusions remain coverage-qualified and provisional.",
             f"- **ML FEATURE ANALYSIS: {'READY' if population_ready == 'READY' and feature_ready == 'READY' else 'PARTIAL'}** — export is ML-safe, but readiness depends on completion.",
             "- **CLUSTERING: NOT READY** — not run; review is required first.",
             "- **SUPERVISED CLASSIFICATION: NOT READY** — no ground-truth labels and not run.", "",
             "No wallet discovery, PCA, UMAP, clustering, or supervised learning was performed."]
    (out_dir / "DATASET_COMPLETION_REPORT.md").write_text("\n".join(lines) + "\n")
    return {"quality": quality, "aggregate_statistics": aggregate_stats,
            "population_readiness": population_ready, "dataset_readiness": dataset_ready,
            "feature_readiness": feature_ready}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "ckb_data_v2")
    parser.add_argument("--validation-dir", type=Path,
                        default=Path(__file__).parent / "research_validation")
    parser.add_argument("--out-dir", type=Path,
                        default=Path(__file__).parent / "dataset_completion")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--max-wallet-attempts", type=int, default=3)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if int(os.getenv("EXPLORER_MAX_CONCURRENCY", "1")) != 1:
        raise SystemExit("dataset completion currently enforces EXPLORER_MAX_CONCURRENCY=1")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(args.validation_dir / "wallet_manifest_v1.jsonl")
    if len(manifest) != 1172:
        raise SystemExit(f"frozen population expected 1172 wallets, found {len(manifest)}")
    store = Store(args.data_dir / "ckb_explorer.sqlite")
    signal.signal(signal.SIGTERM, lambda _signum, _frame: (_ for _ in ()).throw(
        KeyboardInterrupt("termination requested")))
    annotate_completion_requirements(manifest, store.conn)
    population_meta = freeze_contracts(store.conn, manifest, args.out_dir)
    recovery = recover_interrupted_state(store.conn)
    initialize_scheduler(store.conn, manifest)
    migrated_legacy_failures = migrate_legacy_failure_states(store.conn)
    exhausted_failures = finalize_exhausted_states(store.conn, args.max_wallet_attempts)
    manifest_by_address = {item["address"]: item for item in manifest}
    stats = CacheStats()
    explorer = ExplorerClient(stats=stats)
    config = {
        "max_global_failure_rate": float(os.getenv("COMPLETION_MAX_GLOBAL_FAILURE_RATE", "0.10")),
        "max_rate_limit_events": int(os.getenv("COMPLETION_MAX_RATE_LIMIT_EVENTS", "3")),
        "max_rate_limit_rate": float(os.getenv("COMPLETION_MAX_RATE_LIMIT_RATE", "0.20")),
        "outage_min_wallets": int(os.getenv("COMPLETION_OUTAGE_MIN_WALLETS", "5")),
        "outage_wallet_failure_rate": float(os.getenv(
            "COMPLETION_OUTAGE_WALLET_FAILURE_RATE", "0.80")),
        "max_parser_failure_rate": float(os.getenv(
            "COMPLETION_MAX_PARSER_FAILURE_RATE", "0.10")),
        "minimum_input_resolution": float(os.getenv("COMPLETION_MIN_INPUT_RESOLUTION", "0.95")),
        "max_detail_failure_rate": float(os.getenv("COMPLETION_MAX_DETAIL_FAILURE_RATE", "0.10")),
        "max_wallet_attempts": args.max_wallet_attempts,
    }
    reports = []
    if not args.prepare_only:
        for batch_index in range(args.max_batches):
            size = args.batch_size if batch_index == 0 else max(args.batch_size, 50)
            addresses = next_wallets(store.conn, size, args.max_wallet_attempts)
            if not addresses:
                break
            report = run_batch(store, manifest_by_address, addresses, explorer, stats,
                               args.out_dir, config)
            reports.append(report)
            if report["safety_stop"]:
                break
    exported = export_feature_datasets(store.conn, manifest, args.out_dir)
    final = write_dataset_reports(store.conn, exported, manifest, args.out_dir,
                                  population_meta)
    state_counts = dict(store.conn.execute(
        "SELECT collection_state,count(*) FROM wallet_collection_state GROUP BY collection_state"))
    store.close()
    console_reports = [{key: value for key, value in report.items()
                        if key != "wallet_results"} for report in reports]
    print(json.dumps({"population": population_meta, "recovery": recovery,
                      "migrated_legacy_failures": migrated_legacy_failures,
                      "exhausted_failures_finalized": exhausted_failures,
                      "state_counts": state_counts,
                      "batches": console_reports, "readiness": {
                          "population": final["population_readiness"],
                          "features": final["feature_readiness"]}}, indent=2))


if __name__ == "__main__":
    main()
