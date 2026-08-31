"""Targeted previous-output resolver; never scans beyond requested outpoints."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from ckb_clients import CkbRpcClient, ClientUnavailable, ExplorerClient
from ckb_native import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    STATUS_MISSING,
    _recompute_conservation,
    normalize_transaction,
    resolve_inputs_from_cells,
    script_hash,
)


def _output_from_explorer(payload: dict, index: int) -> Optional[dict]:
    tx = normalize_transaction(payload)
    return next((output for output in tx["outputs"] if output["output_index"] == index), None)


def _output_from_rpc(payload: Optional[dict], index: int) -> Optional[dict]:
    if not payload:
        return None
    transaction = payload.get("transaction", payload)
    outputs = transaction.get("outputs") or []
    data = transaction.get("outputs_data") or []
    if index < 0 or index >= len(outputs):
        return None
    output = outputs[index]
    lock = output.get("lock")
    type_script = output.get("type")
    capacity = output.get("capacity")
    try:
        capacity = int(capacity, 16) if isinstance(capacity, str) and capacity.startswith("0x") else int(capacity)
    except (TypeError, ValueError):
        capacity = None
    return {"capacity": capacity, "lock_script": lock,
            "lock_script_hash": script_hash(lock), "type_script": type_script,
            "type_script_hash": script_hash(type_script),
            "output_data": data[index] if index < len(data) else None}


def _apply(item: dict, output: dict, source: str) -> bool:
    if output.get("capacity") is None or output.get("lock_script_hash") is None:
        return False
    item.update(resolved_capacity=output["capacity"],
                resolved_lock_script=output.get("lock_script"),
                resolved_lock_script_hash=output.get("lock_script_hash"),
                resolved_type_script=output.get("type_script"),
                resolved_type_script_hash=output.get("type_script_hash"),
                resolved_output_data=output.get("output_data"),
                resolution_status=STATUS_COMPLETE,
                resolution_source=source)
    return True


def resolve_transaction_inputs(conn: sqlite3.Connection, tx: dict,
                               rpc: Optional[CkbRpcClient] = None,
                               explorer: Optional[ExplorerClient] = None) -> dict:
    """Resolve only the transaction's missing inputs in the required order."""
    resolve_inputs_from_cells(conn, tx)
    counts = {"normalized_local_cells": 0, "raw_cached_transaction": 0,
              "ckb_rpc": 0, "explorer": 0, "unresolved": 0}
    rpc = rpc or CkbRpcClient.from_env()
    explorer = explorer or ExplorerClient()

    for item in tx["inputs"]:
        if item["resolution_status"] == STATUS_COMPLETE:
            counts[item.get("resolution_source", "normalized_local_cells")] = \
                counts.get(item.get("resolution_source", "normalized_local_cells"), 0) + 1
            continue
        previous_hash, index = item.get("previous_tx_hash"), item.get("previous_output_index")
        if previous_hash is None or index is None:
            item.update(resolution_status=STATUS_MISSING, resolution_source="unresolved")
            counts["unresolved"] += 1
            continue

        try:
            cached = conn.execute("SELECT raw_json FROM raw_transactions WHERE tx_hash = ?",
                                  (previous_hash,)).fetchone()
        except sqlite3.OperationalError:
            cached = None
        if cached:
            try:
                output = _output_from_explorer(json.loads(cached[0]), index)
                if output and _apply(item, output, "raw_cached_transaction"):
                    counts["raw_cached_transaction"] += 1
                    continue
                item["resolution_status"] = STATUS_INCOMPLETE
            except (ValueError, json.JSONDecodeError):
                item["resolution_status"] = STATUS_INCOMPLETE

        fetch_failed = False
        try:
            output = _output_from_rpc(rpc.get_transaction(previous_hash), index)
            if output and _apply(item, output, "ckb_rpc"):
                counts["ckb_rpc"] += 1
                continue
        except ClientUnavailable:
            fetch_failed = True

        try:
            payload = explorer.get_transaction(previous_hash)
            output = _output_from_explorer(payload, index) if payload else None
            if output and _apply(item, output, "explorer"):
                counts["explorer"] += 1
                continue
        except (ClientUnavailable, ValueError):
            fetch_failed = True

        item.update(resolution_status=STATUS_FAILED if fetch_failed else STATUS_MISSING,
                    resolution_source="unresolved")
        counts["unresolved"] += 1

    _recompute_conservation(tx)
    return counts
