"""Lossless CKB transaction/Cell normalization and observation contracts.

The normalized transaction is a hypergraph: inputs consume previous outputs and
outputs create new Cells.  This module deliberately does not create pairwise
wallet value transfers because CKB transactions do not establish that mapping.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Any, Optional


NETWORK = "mainnet"
SOURCE_VERSION = "ckb-explorer-api-v1"
PARSER_VERSION = "ckb-native-parser-v1"
OBSERVATION_CONTRACT_VERSION = "wallet-observation-30d-v1"
OBSERVATION_DAYS = 30
PAIRWISE_VALUE_ATTRIBUTION = "NOT_ESTABLISHED"

STATUS_MISSING = "missing"
STATUS_FAILED = "failed_to_fetch"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_INCOMPLETE = "incomplete"
STATUS_COMPLETE = "complete"

_HASH_TYPE_BYTE = {"data": 0, "type": 1, "data1": 2, "data2": 4}


NORMALIZED_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    tx_hash TEXT PRIMARY KEY,
    block_number INTEGER,
    block_timestamp INTEGER,
    transaction_index INTEGER,
    input_capacity_shannon INTEGER,
    output_capacity_shannon INTEGER,
    fee_shannon INTEGER,
    capacity_conservation_status TEXT NOT NULL,
    pairwise_value_attribution TEXT NOT NULL DEFAULT 'NOT_ESTABLISHED',
    parser_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lock_scripts (
    script_hash TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    hash_type TEXT NOT NULL,
    args TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS type_scripts (
    script_hash TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    hash_type TEXT NOT NULL,
    args TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cells (
    creating_tx_hash TEXT NOT NULL,
    output_index INTEGER NOT NULL,
    capacity_shannon INTEGER,
    lock_script_hash TEXT,
    lock_identifier TEXT,
    type_script_hash TEXT,
    output_data TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (creating_tx_hash, output_index),
    FOREIGN KEY (creating_tx_hash) REFERENCES transactions(tx_hash),
    FOREIGN KEY (lock_script_hash) REFERENCES lock_scripts(script_hash),
    FOREIGN KEY (type_script_hash) REFERENCES type_scripts(script_hash)
);
CREATE TABLE IF NOT EXISTS transaction_inputs (
    tx_hash TEXT NOT NULL,
    input_index INTEGER NOT NULL,
    previous_tx_hash TEXT,
    previous_output_index INTEGER,
    resolved_capacity_shannon INTEGER,
    resolved_lock_script_hash TEXT,
    resolved_lock_identifier TEXT,
    resolved_type_script_hash TEXT,
    resolved_output_data TEXT,
    resolution_status TEXT NOT NULL,
    resolution_source TEXT NOT NULL DEFAULT 'normalized_payload',
    raw_json TEXT NOT NULL,
    PRIMARY KEY (tx_hash, input_index),
    FOREIGN KEY (tx_hash) REFERENCES transactions(tx_hash)
);
CREATE TABLE IF NOT EXISTS wallet_observations (
    observation_id TEXT PRIMARY KEY,
    address TEXT,
    canonical_lock_identifier TEXT NOT NULL,
    network TEXT NOT NULL,
    window_start_block INTEGER,
    window_end_block INTEGER,
    window_start_timestamp INTEGER NOT NULL,
    window_end_timestamp INTEGER NOT NULL,
    boundary_resolution_source TEXT,
    boundary_resolution_status TEXT NOT NULL DEFAULT 'unresolved',
    transactions_observed INTEGER,
    lifetime_transaction_count_at_cutoff INTEGER,
    listing_status TEXT NOT NULL,
    detail_status TEXT NOT NULL,
    input_resolution_status TEXT NOT NULL,
    listing_complete INTEGER,
    detail_complete INTEGER,
    input_resolution_complete INTEGER,
    history_censored INTEGER NOT NULL,
    listing_coverage_ratio REAL,
    detail_coverage_ratio REAL,
    input_resolution_ratio REAL,
    source_version TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    observation_contract_version TEXT NOT NULL,
    collection_timestamp TEXT NOT NULL,
    CHECK (window_end_timestamp - window_start_timestamp = 2592000)
);
CREATE TABLE IF NOT EXISTS wallet_transaction_participation (
    observation_id TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    target_controls_input INTEGER NOT NULL,
    target_controls_output INTEGER NOT NULL,
    controlled_input_count INTEGER NOT NULL,
    controlled_output_count INTEGER NOT NULL,
    PRIMARY KEY (observation_id, tx_hash),
    FOREIGN KEY (observation_id) REFERENCES wallet_observations(observation_id),
    FOREIGN KEY (tx_hash) REFERENCES transactions(tx_hash)
);
CREATE TABLE IF NOT EXISTS collection_receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    source TEXT NOT NULL,
    request_parameters_json TEXT,
    collection_status TEXT NOT NULL,
    collected_at INTEGER NOT NULL,
    error TEXT
);
"""


def install_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(NORMALIZED_SCHEMA)
    conn.execute("INSERT OR REPLACE INTO schema_meta VALUES (?, ?)",
                 ("normalized_schema_version", "ckb-cell-schema-v1"))
    conn.execute("INSERT OR REPLACE INTO schema_meta VALUES (?, ?)",
                 ("legacy_edges_status", "LEGACY_DISABLED_NOT_SOURCE_OF_TRUTH"))
    _ensure_column(conn, "transaction_inputs", "resolution_source",
                   "TEXT NOT NULL DEFAULT 'normalized_payload'")
    _ensure_column(conn, "transaction_inputs", "resolved_lock_identifier", "TEXT")
    _ensure_column(conn, "cells", "lock_identifier", "TEXT")
    _ensure_column(conn, "wallet_observations", "boundary_resolution_source", "TEXT")
    _ensure_column(conn, "wallet_observations", "boundary_resolution_status",
                   "TEXT NOT NULL DEFAULT 'unresolved'")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str,
                   declaration: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def script_hash(script: Optional[dict]) -> Optional[str]:
    if not script:
        return None
    try:
        code_hash_hex = script["code_hash"]
        hash_type = script["hash_type"]
        args_hex = script.get("args", "0x")
        code_hash = bytes.fromhex(code_hash_hex.removeprefix("0x"))
        args = bytes.fromhex(args_hex.removeprefix("0x"))
        hash_type_byte = _HASH_TYPE_BYTE[hash_type]
        if len(code_hash) != 32:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    args_field = len(args).to_bytes(4, "little") + args
    header = 16
    offsets = (header, header + 32, header + 33)
    body = code_hash + bytes([hash_type_byte]) + args_field
    molecule = (header + len(body)).to_bytes(4, "little")
    molecule += b"".join(v.to_bytes(4, "little") for v in offsets) + body
    digest = hashlib.blake2b(molecule, digest_size=32,
                            person=b"ckb-default-hash").hexdigest()
    return "0x" + digest


def _int(value: Any) -> Optional[int]:
    try:
        return int(Decimal(str(value))) if value is not None else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def _epoch_seconds(value: Any) -> Optional[int]:
    parsed = _int(value)
    if parsed is None:
        return None
    return parsed // 1000 if parsed > 100_000_000_000 else parsed


def _attrs(payload: dict) -> tuple[dict, dict]:
    if payload.get("transaction_hash"):
        return payload, payload
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    data = data or {}
    return data, data.get("attributes") or {}


def _script(cell: dict, kind: str) -> Optional[dict]:
    candidates = (kind, f"{kind}_script", f"resolved_{kind}")
    for key in candidates:
        value = cell.get(key)
        if isinstance(value, dict) and value.get("code_hash"):
            return {"code_hash": value.get("code_hash"),
                    "hash_type": value.get("hash_type"),
                    "args": value.get("args", "0x")}
    return None


def _outpoint(cell: dict) -> tuple[Optional[str], Optional[int]]:
    point = cell.get("previous_output") or cell.get("out_point") or {}
    tx_hash = (point.get("tx_hash") or point.get("transaction_hash") or
               cell.get("previous_tx_hash") or cell.get("generated_tx_hash"))
    index = (point.get("index") if point.get("index") is not None
             else point.get("output_index"))
    if index is None:
        index = cell.get("previous_output_index")
    return tx_hash, _int(index)


def _data(cell: dict) -> Optional[str]:
    value = cell.get("output_data")
    if value is None:
        value = cell.get("data")
    return value if isinstance(value, str) else None


def _lock_identifier(cell: dict, lock: Optional[dict]) -> Optional[str]:
    """Return a script hash, or preserve the historical address fallback."""
    return script_hash(lock) or cell.get("lock_hash") or cell.get("address_hash")


def _target_matches(cell: dict, lock: Optional[dict], target: Optional[str], target_address: Optional[str] = None) -> bool:
    """Match canonical script identity and Explorer address identity."""
    if not target and not target_address:
        return False
    identities = {_lock_identifier(cell, lock), cell.get("lock_hash"), cell.get("address_hash")}
    return bool((target and target in identities) or (target_address and target_address in identities))


def normalize_transaction(payload: dict, target_lock_hash: Optional[str] = None,
                           target_address: Optional[str] = None) -> dict:
    data, attrs = _attrs(payload)
    tx_hash = attrs.get("transaction_hash") or data.get("id") or payload.get("tx_hash")
    if not tx_hash:
        raise ValueError("transaction payload has no tx hash")
    raw_inputs = attrs.get("display_inputs") or attrs.get("inputs") or []
    raw_outputs = attrs.get("display_outputs") or attrs.get("outputs") or []

    outputs = []
    for index, cell in enumerate(raw_outputs):
        lock = _script(cell, "lock")
        type_script = _script(cell, "type")
        outputs.append({
            "output_index": (_int(cell.get("output_index")) if cell.get("output_index") is not None
                             else _int(cell.get("cell_index")) if cell.get("cell_index") is not None else index),
            "capacity": _int(cell.get("capacity")),
            "lock_script": lock,
            "lock_script_hash": script_hash(lock),
            "lock_identifier": _lock_identifier(cell, lock),
            "type_script": type_script,
            "type_script_hash": script_hash(type_script),
            "output_data": _data(cell),
            "target_controls_output": _target_matches(cell, lock, target_lock_hash, target_address),
            "raw": cell,
        })

    inputs = []
    for index, cell in enumerate(raw_inputs):
        from_cellbase = bool(cell.get("from_cellbase"))
        previous_tx_hash, previous_output_index = _outpoint(cell)
        lock = _script(cell, "lock")
        type_script = _script(cell, "type")
        capacity = _int(cell.get("capacity"))
        lock_identifier = _lock_identifier(cell, lock)
        has_resolved_cell = capacity is not None and lock_identifier is not None
        inputs.append({
            "input_index": index,
            "previous_tx_hash": previous_tx_hash,
            "previous_output_index": previous_output_index,
            "resolved_capacity": capacity,
            "resolved_lock_script": lock,
            "resolved_lock_script_hash": script_hash(lock),
            "resolved_lock_identifier": lock_identifier,
            "resolved_type_script": type_script,
            "resolved_type_script_hash": script_hash(type_script),
            "resolved_output_data": _data(cell),
            "resolution_status": (STATUS_NOT_APPLICABLE if from_cellbase else
                                  STATUS_COMPLETE if has_resolved_cell else STATUS_INCOMPLETE),
            "resolution_source": ("cellbase" if from_cellbase else
                                  ("normalized_payload" if lock is not None else
                                   "local_address_transaction") if has_resolved_cell else "unresolved"),
            "target_controls_input": _target_matches(cell, lock, target_lock_hash, target_address),
            "raw": cell,
        })

    tx = {
        "tx_hash": tx_hash,
        "block_number": _int(attrs.get("block_number")),
        "block_timestamp": _epoch_seconds(attrs.get("block_timestamp")),
        "transaction_index": _int(attrs.get("transaction_index") or attrs.get("tx_index")),
        "inputs": inputs,
        "outputs": outputs,
        "reported_fee_shannon": _int(attrs.get("transaction_fee")),
        "is_cellbase": bool(attrs.get("is_cellbase")) or any(
            item.get("from_cellbase") for item in raw_inputs),
        "pairwise_value_attribution": PAIRWISE_VALUE_ATTRIBUTION,
    }
    _recompute_conservation(tx)
    return tx


def _recompute_conservation(tx: dict) -> None:
    resolved = bool(tx["inputs"]) and all(
        item["resolution_status"] == STATUS_COMPLETE for item in tx["inputs"])
    input_total = sum(item["resolved_capacity"] for item in tx["inputs"]) if resolved else None
    output_known = all(item["capacity"] is not None for item in tx["outputs"])
    output_total = sum(item["capacity"] for item in tx["outputs"]) if output_known else None
    fee = input_total - output_total if input_total is not None and output_total is not None else None
    reported_fee = tx.get("reported_fee_shannon")
    if tx.get("is_cellbase") and (not tx["inputs"] or all(
            item["resolution_status"] == STATUS_NOT_APPLICABLE for item in tx["inputs"])):
        status = STATUS_NOT_APPLICABLE
    elif fee is None:
        status = STATUS_INCOMPLETE
    elif fee < 0 or (reported_fee is not None and fee != reported_fee):
        status = "failed"
    else:
        status = STATUS_COMPLETE
    tx.update(input_capacity_shannon=input_total,
              output_capacity_shannon=output_total,
              fee_shannon=fee,
              capacity_conservation_status=status)


def _stored_script(conn: sqlite3.Connection, table: str,
                   digest: Optional[str]) -> Optional[dict]:
    if not digest:
        return None
    row = conn.execute(
        f"SELECT code_hash, hash_type, args FROM {table} WHERE script_hash = ?",
        (digest,),
    ).fetchone()
    return {"code_hash": row[0], "hash_type": row[1], "args": row[2]} if row else None


def resolve_inputs_from_cells(conn: sqlite3.Connection, tx: dict) -> int:
    """Hydrate unresolved inputs from normalized previous outputs already cached."""
    resolved_count = 0
    for item in tx["inputs"]:
        if item["resolution_status"] == STATUS_COMPLETE:
            continue
        if item["previous_tx_hash"] is None or item["previous_output_index"] is None:
            continue
        row = conn.execute(
            "SELECT capacity_shannon, lock_script_hash, lock_identifier, type_script_hash, "
            "output_data FROM cells WHERE creating_tx_hash = ? AND output_index = ?",
            (item["previous_tx_hash"], item["previous_output_index"]),
        ).fetchone()
        if not row:
            continue
        item["resolved_capacity"] = row[0]
        item["resolved_lock_script_hash"] = row[1]
        item["resolved_lock_identifier"] = row[2] or row[1]
        item["resolved_type_script_hash"] = row[3]
        item["resolved_output_data"] = row[4]
        item["resolved_lock_script"] = _stored_script(conn, "lock_scripts", row[1])
        item["resolved_type_script"] = _stored_script(conn, "type_scripts", row[3])
        item["resolution_status"] = (STATUS_COMPLETE if row[0] is not None and (row[2] or row[1])
                                     else STATUS_INCOMPLETE)
        item["resolution_source"] = "normalized_local_cells"
        resolved_count += item["resolution_status"] == STATUS_COMPLETE
    _recompute_conservation(tx)
    return resolved_count


def _save_script(conn: sqlite3.Connection, table: str, script: Optional[dict], digest: Optional[str]) -> None:
    if not script or not digest:
        return
    conn.execute(f"INSERT OR IGNORE INTO {table} VALUES (?, ?, ?, ?)",
                 (digest, script["code_hash"], script["hash_type"], script.get("args", "0x")))


def persist_transaction(conn: sqlite3.Connection, tx: dict) -> None:
    resolve_inputs_from_cells(conn, tx)
    conn.execute("""INSERT OR REPLACE INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        tx["tx_hash"], tx["block_number"], tx["block_timestamp"], tx["transaction_index"],
        tx["input_capacity_shannon"], tx["output_capacity_shannon"], tx["fee_shannon"],
        tx["capacity_conservation_status"], PAIRWISE_VALUE_ATTRIBUTION, PARSER_VERSION))
    conn.execute("DELETE FROM cells WHERE creating_tx_hash = ?", (tx["tx_hash"],))
    conn.execute("DELETE FROM transaction_inputs WHERE tx_hash = ?", (tx["tx_hash"],))
    for output in tx["outputs"]:
        _save_script(conn, "lock_scripts", output["lock_script"], output["lock_script_hash"])
        _save_script(conn, "type_scripts", output["type_script"], output["type_script_hash"])
        conn.execute("""INSERT INTO cells
            (creating_tx_hash,output_index,capacity_shannon,lock_script_hash,
             lock_identifier,type_script_hash,output_data,raw_json)
             VALUES (?,?,?,?,?,?,?,?)""", (
            tx["tx_hash"], output["output_index"], output["capacity"],
            output["lock_script_hash"], output.get("lock_identifier"),
            output["type_script_hash"], output["output_data"],
            json.dumps(output["raw"], sort_keys=True)))
    for item in tx["inputs"]:
        _save_script(conn, "lock_scripts", item["resolved_lock_script"], item["resolved_lock_script_hash"])
        _save_script(conn, "type_scripts", item["resolved_type_script"], item["resolved_type_script_hash"])
        conn.execute("""INSERT INTO transaction_inputs
            (tx_hash,input_index,previous_tx_hash,previous_output_index,
             resolved_capacity_shannon,resolved_lock_script_hash,
             resolved_lock_identifier,resolved_type_script_hash,resolved_output_data,resolution_status,
             resolution_source,raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            tx["tx_hash"], item["input_index"], item["previous_tx_hash"],
            item["previous_output_index"], item["resolved_capacity"],
            item["resolved_lock_script_hash"], item.get("resolved_lock_identifier"),
            item["resolved_type_script_hash"],
            item["resolved_output_data"], item["resolution_status"], item["resolution_source"],
            json.dumps(item["raw"], sort_keys=True)))


def rebuild_from_raw_cache(conn: sqlite3.Connection) -> dict:
    """Reparse cached Explorer details without making network requests."""
    install_schema(conn)
    parsed = failed = 0
    cached = list(conn.execute("SELECT tx_hash, raw_json FROM raw_transactions"))
    normalized = []
    for tx_hash, raw in cached:
        try:
            tx = normalize_transaction(json.loads(raw))
            if tx["tx_hash"] != tx_hash:
                raise ValueError("cache key and payload hash differ")
            persist_transaction(conn, tx)
            normalized.append(tx)
            parsed += 1
        except (ValueError, TypeError, json.JSONDecodeError):
            failed += 1
    # A second pass resolves inputs whose previous transaction appeared later
    # in the unordered raw cache iteration.
    newly_resolved = 0
    for tx in normalized:
        newly_resolved += resolve_inputs_from_cells(conn, tx)
        persist_transaction(conn, tx)
    conn.commit()
    return {"parsed": parsed, "failed": failed, "newly_resolved": newly_resolved}


def ratio(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return min(1.0, numerator / denominator)


@dataclass(frozen=True)
class ObservationContract:
    address: Optional[str]
    canonical_lock_identifier: str
    window_start_timestamp: int
    window_end_timestamp: int
    window_start_block: Optional[int] = None
    window_end_block: Optional[int] = None
    boundary_resolution_source: Optional[str] = None
    boundary_resolution_status: str = "unresolved"
    transactions_observed: Optional[int] = None
    lifetime_transaction_count_at_cutoff: Optional[int] = None
    listing_status: str = STATUS_MISSING
    detail_status: str = STATUS_MISSING
    input_resolution_status: str = STATUS_MISSING
    listing_complete: Optional[bool] = None
    detail_complete: Optional[bool] = None
    input_resolution_complete: Optional[bool] = None
    history_censored: bool = True
    listing_coverage_ratio: Optional[float] = None
    detail_coverage_ratio: Optional[float] = None
    input_resolution_ratio: Optional[float] = None
    collection_timestamp: str = ""

    def __post_init__(self) -> None:
        if self.window_end_timestamp - self.window_start_timestamp != OBSERVATION_DAYS * 86400:
            raise ValueError("observation window must be exactly 30 days")
        valid = {STATUS_MISSING, STATUS_FAILED, STATUS_NOT_APPLICABLE,
                 STATUS_INCOMPLETE, STATUS_COMPLETE}
        if any(v not in valid for v in (self.listing_status, self.detail_status,
                                         self.input_resolution_status)):
            raise ValueError("invalid observation status")

    @property
    def observation_id(self) -> str:
        raw = f"{NETWORK}|{self.canonical_lock_identifier}|{self.window_start_timestamp}|{self.window_end_timestamp}|{OBSERVATION_CONTRACT_VERSION}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def as_record(self) -> dict:
        return {**self.__dict__, "observation_id": self.observation_id,
                "network": NETWORK, "source_version": SOURCE_VERSION,
                "parser_version": PARSER_VERSION,
                "observation_contract_version": OBSERVATION_CONTRACT_VERSION,
                "collection_timestamp": self.collection_timestamp or dt.datetime.now(dt.timezone.utc).isoformat()}


def persist_observation(conn: sqlite3.Connection, observation: ObservationContract,
                        transactions: list[dict]) -> None:
    record = observation.as_record()
    columns = list(record)
    conn.execute(f"INSERT OR REPLACE INTO wallet_observations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                 [int(v) if isinstance(v, bool) else v for v in record.values()])
    conn.execute("DELETE FROM wallet_transaction_participation WHERE observation_id = ?",
                 (observation.observation_id,))
    for tx in transactions:
        controlled_inputs = sum(i["target_controls_input"] for i in tx["inputs"])
        controlled_outputs = sum(o["target_controls_output"] for o in tx["outputs"])
        conn.execute("INSERT INTO wallet_transaction_participation VALUES (?, ?, ?, ?, ?, ?)",
                     (observation.observation_id, tx["tx_hash"], bool(controlled_inputs),
                      bool(controlled_outputs), controlled_inputs, controlled_outputs))
