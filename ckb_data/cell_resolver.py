from __future__ import annotations

"""
Phase 1 of the gap-closure plan: resolve genuine Cells -- lock/type scripts,
previous-outpoint provenance for inputs, and `since` -- from cached CKB
Explorer transaction detail (`raw_transactions.raw_json`), instead of the
flat address-pair edges the pipeline has used until now.

Why this file is defensive about field names
----------------------------------------------
This project has already been burned once by a silent, wrong field-name
assumption: rebuild_edges_from_cache.py's whole existence is because the
original `int(capacity)` parse silently returned None for every cell and
nobody noticed until someone went looking. Cell resolution touches several
Explorer fields (previous-outpoint, type script, `since`) that nothing in
this codebase has ever read before, and this environment has no network
access to the Explorer API to confirm their exact shape empirically ahead
of time.

So every extractor below:
  1. Tries several candidate field-name shapes, in priority order.
  2. Reports which one matched (or that none did) via a `match_method`
     string, instead of silently returning a maybe-wrong value.
  3. Never guesses a numeric/hash value when no candidate matched -- it
     returns None/"unresolved" so the audit counts in build_cell_graph.py's
     `--diagnose` make the gap visible before `--rebuild` commits to it.

Run `build_cell_graph.py --diagnose` against your real cached database
FIRST. If `match_method` distributions there look wrong (e.g. everything
falling back to "unresolved"), fix the candidate lists here before trusting
`--rebuild`'s output.
"""

import json
from pathlib import Path
from typing import Any, Optional

_CKB_HASH_TYPE_BYTE = {"data": 0, "type": 1, "data1": 2, "data2": 4}


def ckb_script_hash(code_hash_hex: str, hash_type: str, args_hex: str) -> Optional[str]:
    """Identical algorithm to collect_target_wallets.py / rebuild_edges_from_cache.py's
    ckb_script_hash -- duplicated on purpose so this module has no dependency
    on the rest of the pipeline and can be run standalone (same rationale
    rebuild_edges_from_cache.py already documents for its own copy)."""
    try:
        code_hash = bytes.fromhex(code_hash_hex[2:] if code_hash_hex.startswith("0x") else code_hash_hex)
        args = bytes.fromhex(args_hex[2:] if args_hex.startswith("0x") else args_hex)
        hash_type_byte = _CKB_HASH_TYPE_BYTE[hash_type]
    except (AttributeError, ValueError, KeyError):
        return None

    args_encoded = len(args).to_bytes(4, "little") + args
    header_len = 4 + 4 * 3
    off0 = header_len
    off1 = off0 + len(code_hash)
    off2 = off1 + 1
    total_size = off2 + len(args_encoded)

    buf = bytearray()
    buf += total_size.to_bytes(4, "little")
    buf += off0.to_bytes(4, "little")
    buf += off1.to_bytes(4, "little")
    buf += off2.to_bytes(4, "little")
    buf += code_hash
    buf += bytes([hash_type_byte])
    buf += args_encoded

    digest = __import__("hashlib").blake2b(bytes(buf), digest_size=32, person=b"ckb-default-hash").digest()
    return "0x" + digest.hex()


def _to_int(v: Any) -> Optional[int]:
    """Same int-or-Decimal defensive parse as rebuild_edges_from_cache.py --
    Explorer sometimes returns numeric fields as decimal-point strings
    (e.g. capacity as "1502912399995344.0")."""
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        from decimal import Decimal, InvalidOperation
        return int(Decimal(str(v)))
    except (InvalidOperation, ValueError, TypeError, Exception):
        return None


# ---------------------------------------------------------------------------
# Lock / type script extraction
# ---------------------------------------------------------------------------

LOCK_KEY_CANDIDATES = ("lock", "lock_script")
TYPE_KEY_CANDIDATES = ("type", "type_script", "type_id_script")


def _extract_script_dict(cell: dict, key_candidates: tuple) -> tuple[Optional[dict], Optional[str]]:
    """Look for a nested {code_hash, hash_type, args} dict under any of
    key_candidates. Returns (script_dict_or_None, matched_key_or_None)."""
    for key in key_candidates:
        val = cell.get(key)
        if isinstance(val, dict) and val.get("code_hash") and val.get("hash_type"):
            return val, key
    return None, None


def extract_lock(cell: dict) -> dict:
    """Best-effort resolution of a cell's lock script.

    Priority order:
      1. A nested lock/lock_script dict with code_hash+hash_type+args ->
         compute the real hash ourselves (most trustworthy).
      2. A flat pre-computed hash field, if Explorer ever supplies one.
      3. address_hash/address, as a last resort (this is the CURRENT
         pipeline's only fallback -- see Data_Aquisition.md's documented
         "edges are keyed by address" quirk). Kept so this module degrades
         to the existing behavior rather than failing outright when a cell
         genuinely doesn't carry script data.
    """
    script, matched_key = _extract_script_dict(cell, LOCK_KEY_CANDIDATES)
    if script:
        code_hash, hash_type, args = script.get("code_hash"), script.get("hash_type"), script.get("args")
        lock_hash = None
        if code_hash and hash_type and args is not None:
            lock_hash = ckb_script_hash(code_hash, hash_type, args)
        if lock_hash:
            return {
                "lock_hash": lock_hash, "lock_code_hash": code_hash,
                "lock_hash_type": hash_type, "lock_args": args,
                "address_hash": cell.get("address_hash") or cell.get("address"),
                "match_method": f"nested_script:{matched_key}",
            }

    for key in ("lock_hash", "code_hash_hash"):
        h = cell.get(key)
        if h:
            return {
                "lock_hash": h, "lock_code_hash": None, "lock_hash_type": None,
                "lock_args": None, "address_hash": cell.get("address_hash") or cell.get("address"),
                "match_method": f"flat_field:{key}",
            }

    addr = cell.get("address_hash") or cell.get("address")
    if addr:
        return {
            "lock_hash": None, "lock_code_hash": None, "lock_hash_type": None,
            "lock_args": None, "address_hash": addr, "match_method": "address_fallback",
        }

    return {
        "lock_hash": None, "lock_code_hash": None, "lock_hash_type": None,
        "lock_args": None, "address_hash": None, "match_method": "unresolved",
    }


_NON_TYPE_CELL_TYPE_VALUES = {"normal", "capacity", "", None}


def extract_type(cell: dict) -> dict:
    """Best-effort resolution of a cell's type script (xUDT, NFT, DAO, etc.).
    Returns has_type_script=False (not unresolved) when the evidence
    genuinely points to no type script -- an ordinary capacity-only cell is
    common and legitimate, not missing data."""
    script, matched_key = _extract_script_dict(cell, TYPE_KEY_CANDIDATES)
    if script:
        code_hash, hash_type, args = script.get("code_hash"), script.get("hash_type"), script.get("args")
        type_hash = None
        if code_hash and hash_type and args is not None:
            type_hash = ckb_script_hash(code_hash, hash_type, args)
        return {
            "type_hash": type_hash, "type_code_hash": code_hash,
            "type_hash_type": hash_type, "type_args": args,
            "has_type_script": True, "match_method": f"nested_script:{matched_key}",
        }

    cell_type = cell.get("cell_type")
    if cell_type is not None and str(cell_type).lower() not in _NON_TYPE_CELL_TYPE_VALUES:
        return {
            "type_hash": None, "type_code_hash": None, "type_hash_type": None,
            "type_args": None, "has_type_script": True,
            "match_method": f"cell_type_flag:{cell_type}",
        }

    return {
        "type_hash": None, "type_code_hash": None, "type_hash_type": None,
        "type_args": None, "has_type_script": False, "match_method": "no_type_script",
    }


def extract_capacity(cell: dict) -> Optional[int]:
    return _to_int(cell.get("capacity"))


def is_cellbase_input(cell: dict) -> bool:
    """Explorer sometimes flags this directly; fall back to False (never
    guess a cell IS cellbase without explicit evidence -- a false positive
    here would corrupt miner-detection downstream, which is already the
    hardest of the four target classes per the gap-closure plan)."""
    for key in ("from_cellbase", "is_cellbase"):
        v = cell.get(key)
        if v is not None:
            return bool(v)
    return False


# ---------------------------------------------------------------------------
# Previous-outpoint (input Cell provenance) extraction
# ---------------------------------------------------------------------------

# Candidate (tx_hash_field, index_field) pairs, priority order. The first
# entry is this module's best guess at CKB Explorer's actual shape based on
# how its display_inputs are known to reference the cell's creating
# transaction; the rest are defensive fallbacks. --diagnose reports the
# real distribution so this list can be corrected against your live data.
PREV_OUTPOINT_FLAT_CANDIDATES = (
    ("generated_tx_hash", "cell_index"),
    ("previous_cell_output_tx_hash", "previous_cell_output_index"),
    ("previous_tx_hash", "previous_index"),
)


def extract_previous_outpoint(input_cell: dict) -> dict:
    """Best-effort extraction of which prior output this input Cell consumed.
    Returns match_method="unresolved" (not a guessed value) when nothing
    matches -- an unresolved input Cell should show up as a gap in
    --diagnose, not as silently-wrong data feeding the feature layer."""
    nested = input_cell.get("previous_output")
    if isinstance(nested, dict) and nested.get("tx_hash") is not None:
        return {
            "prev_tx_hash": nested.get("tx_hash"),
            "prev_index": _to_int(nested.get("index")),
            "match_method": "nested_previous_output",
        }
    for tx_key, idx_key in PREV_OUTPOINT_FLAT_CANDIDATES:
        tx_hash = input_cell.get(tx_key)
        idx = input_cell.get(idx_key)
        if tx_hash and idx is not None:
            return {
                "prev_tx_hash": tx_hash, "prev_index": _to_int(idx),
                "match_method": f"flat_fields:{tx_key}+{idx_key}",
            }
    return {"prev_tx_hash": None, "prev_index": None, "match_method": "unresolved"}


# ---------------------------------------------------------------------------
# `since` decoding (RFC 0017 -- Transaction valid since)
# ---------------------------------------------------------------------------

SINCE_METRIC_BLOCK_NUMBER = "block_number"
SINCE_METRIC_EPOCH = "epoch"
SINCE_METRIC_TIMESTAMP = "timestamp"
SINCE_METRIC_UNKNOWN = "unknown"

SINCE_FIELD_CANDIDATES = ("since",)


def extract_since_raw(input_cell: dict) -> Optional[Any]:
    for key in SINCE_FIELD_CANDIDATES:
        if key in input_cell and input_cell[key] not in (None, ""):
            return input_cell[key]
    return None


def decode_since(since_raw: Any) -> Optional[dict]:
    """Decode a CKB `since` value per RFC 0017:
      - bit 63: 0 = absolute, 1 = relative
      - bits 61-62: metric flag -- 00 block number, 01 epoch, 10 timestamp
      - remaining bits: the value in that metric's units

    `since == 0` conventionally means "no time-lock constraint" and is
    treated as None (the feature genuinely doesn't apply, not a missing
    value). Epoch's internal number/index/length sub-packing is not fully
    unpacked here -- the behavioral signal this project needs is repetition
    (same since value recurring across transactions), which the raw 56-bit
    value already supports; full epoch-fraction decoding can be added later
    if a feature specifically needs it.
    """
    n = _to_int(since_raw)
    if not n:
        return None
    n &= 0xFFFFFFFFFFFFFFFF
    if n == 0:
        return None

    is_relative = bool((n >> 63) & 0x1)
    metric_flag = (n >> 61) & 0x3
    metric = {
        0: SINCE_METRIC_BLOCK_NUMBER,
        1: SINCE_METRIC_EPOCH,
        2: SINCE_METRIC_TIMESTAMP,
    }.get(metric_flag, SINCE_METRIC_UNKNOWN)
    raw_value = n & ((1 << 56) - 1)
    return {"relative": is_relative, "metric": metric, "raw_value": raw_value}


# ---------------------------------------------------------------------------
# Lock-family classification (registry-driven, not hardcoded in logic)
# ---------------------------------------------------------------------------

def load_lock_registry(path: Optional[Path] = None) -> dict:
    path = path or (Path(__file__).parent / "lock_script_registry.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def classify_lock_family(code_hash: Optional[str], hash_type: Optional[str], registry: dict) -> str:
    """Returns a family name from the registry, "unrecognized" if code_hash
    is present but not in the registry, or "unknown" if there's no code_hash
    to classify at all (e.g. address-fallback-only resolution)."""
    if not code_hash:
        return "unknown"
    key = code_hash.lower()
    for family, entries in registry.items():
        if family.startswith("_"):
            continue
        for entry in entries:
            entry_hash = (entry.get("code_hash") or "").lower()
            if entry_hash and entry_hash == key and (
                not entry.get("hash_type") or entry.get("hash_type") == hash_type
            ):
                return family
    return "unrecognized"
