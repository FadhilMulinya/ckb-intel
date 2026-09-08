import re
import config

SHANNONS_PER_CKB = 10 ** 8


def to_ckb(capacity):
    """Explorer returns capacity as a shannon-denominated string/int."""
    if capacity in (None, ""):
        return 0.0
    try:
        return int(capacity) / SHANNONS_PER_CKB
    except (TypeError, ValueError):
        return 0.0


def decode_since(since_field):
    """Decode a `since` value per RFC 0017: highest bit = relative flag,
    next 2 bits of the top byte = metric (block/epoch/timestamp), low 56 bits = value.
    Accepts: None, int, hex string, or an already-parsed dict from Explorer."""
    if since_field is None:
        return {"present": False, "relative": None, "metric": None, "value": None}

    if isinstance(since_field, dict):
        return {
            "present": True,
            "relative": since_field.get("relative"),
            "metric": since_field.get("metric") or since_field.get("type"),
            "value": since_field.get("value"),
        }

    raw = since_field
    if isinstance(raw, str):
        raw = int(raw, 16) if raw.lower().startswith("0x") else int(raw)
    if not isinstance(raw, int) or raw == 0:
        return {"present": raw != 0, "relative": False, "metric": "none", "value": 0}

    flag_byte = (raw >> 56) & 0xFF
    relative = bool(flag_byte & 0x80)
    metric_bits = flag_byte & 0x60
    metric = {0x00: "block_number", 0x20: "epoch", 0x40: "timestamp"}.get(metric_bits, "unknown")
    value = raw & 0x00FFFFFFFFFFFFFF
    return {"present": True, "relative": relative, "metric": metric, "value": value}


def classify_cell_type(cell_type_str):
    """Map Explorer's `cell_type` string to a coarse type-script bucket."""
    if not cell_type_str:
        return "normal"
    s = cell_type_str.lower()
    if "dao" in s:
        return "dao"
    if "udt" in s or "sudt" in s or "xudt" in s:
        return "udt"
    if "nft" in s or "cota" in s or "spore" in s or "dob" in s:
        return "nft_state"
    if s in ("normal", "normal_address"):
        return "normal"
    return "other"


def resolve_transaction(tx: dict, target_address: str):
    """Convert one Explorer transaction dict into a normalized record centered
    on `target_address`'s participation."""
    inputs = tx.get("display_inputs") or []
    outputs = tx.get("display_outputs") or []

    def _cell(io, index, direction):
        since_info = decode_since(io.get("since")) if direction == "input" else {"present": False}
        return {
            "address": io.get("address_hash"),
            "capacity_ckb": to_ckb(io.get("capacity")),
            "cell_type": classify_cell_type(io.get("cell_type")),
            "raw_cell_type": io.get("cell_type"),
            "from_cellbase": bool(io.get("from_cellbase")),
            "index": index,
            "since": since_info,
            "is_target": io.get("address_hash") == target_address,
        }

    in_cells = [_cell(io, i, "input") for i, io in enumerate(inputs)]
    out_cells = [_cell(io, i, "output") for i, io in enumerate(outputs)]

    return {
        "tx_hash": tx.get("transaction_hash"),
        "block_number": int(tx.get("block_number", 0) or 0),
        "block_timestamp": int(tx.get("block_timestamp", 0) or 0),
        "is_cellbase": bool(tx.get("is_cellbase")),
        "inputs": in_cells,
        "outputs": out_cells,
        "n_inputs": len(in_cells),
        "n_outputs": len(out_cells),
        "target_input_cells": [c for c in in_cells if c["is_target"]],
        "target_output_cells": [c for c in out_cells if c["is_target"]],
        "counterparty_input_addrs": {c["address"] for c in in_cells if not c["is_target"] and c["address"]},
        "counterparty_output_addrs": {c["address"] for c in out_cells if not c["is_target"] and c["address"]},
    }


def resolve_wallet_transactions(raw_record: dict):
    """Resolve every cached transaction for a wallet raw record (see acquisition.pull_wallet_raw)."""
    address = raw_record["address"]
    resolved = [resolve_transaction(tx, address) for tx in raw_record.get("transactions", [])]
    resolved.sort(key=lambda t: t["block_timestamp"])
    return resolved
