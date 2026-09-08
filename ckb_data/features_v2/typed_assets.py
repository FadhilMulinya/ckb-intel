from __future__ import annotations

from collections import Counter, defaultdict

from .config import MINIMUM_SAMPLES
from .scripts import XUDT_CODE_HASH
from .stats import normalized_entropy
from .support import FeatureResultV2, SupportState, empty_result, family_support

FEATURES = ["typed_asset_count", "asset_diversity", "typed_cell_ratio", "token_input_total",
            "token_output_total", "net_token_delta", "token_turnover",
            "repeated_token_amount_ratio", "token_amount_entropy", "token_fanout_ratio",
            "token_fanin_ratio"]


def _decode(cell: dict, resolved: bool) -> dict | None:
    prefix = "resolved_" if resolved else ""
    script = cell.get(prefix + "type_script")
    if not script or (script.get("code_hash"), script.get("hash_type")) != (XUDT_CODE_HASH, "data1"):
        return None
    data = cell.get(prefix + "output_data")
    if not isinstance(data, str) or len(data.removeprefix("0x")) < 32:
        return {"asset_identifier": cell.get(prefix + "type_script_hash"), "amount": None,
                "decode_status": "MISSING_16_BYTE_AMOUNT"}
    try:
        amount = int.from_bytes(bytes.fromhex(data.removeprefix("0x")[:32]), "little")
    except (TypeError, ValueError):
        return {"asset_identifier": cell.get(prefix + "type_script_hash"), "amount": None,
                "decode_status": "INVALID_AMOUNT_ENCODING"}
    raw = cell.get("raw") or {}
    raw_amount = ((raw.get("xudt_info") or {}).get("amount") or
                  (raw.get("extra_info") or {}).get("amount"))
    mismatch = raw_amount is not None and int(raw_amount) != amount
    return {"asset_identifier": cell.get(prefix + "type_script_hash"), "amount": amount,
            "decode_status": "METADATA_MISMATCH" if mismatch else "DECODED",
            "metadata_amount": int(raw_amount) if raw_amount is not None else None}


def extract(observation: dict) -> FeatureResultV2:
    minimum = MINIMUM_SAMPLES["typed_assets"]
    requirements = {"minimum_supported_typed_cells": minimum,
                    "verified_code_hash": XUDT_CODE_HASH, "hash_type": "data1",
                    "amount_encoding": "first_16_bytes_unsigned_little_endian"}
    decoded, tx_rows, target_cells = [], [], 0
    for tx in observation.get("transactions", []):
        ins, outs = [], []
        for cell in tx.get("inputs", []):
            if cell.get("target_controls_input"):
                target_cells += 1
                item = _decode(cell, True)
                if item: ins.append(item); decoded.append(item)
        for cell in tx.get("outputs", []):
            if cell.get("target_controls_output"):
                target_cells += 1
                item = _decode(cell, False)
                if item: outs.append(item); decoded.append(item)
        tx_rows.append((tx.get("tx_hash"), ins, outs))
    valid = [item for item in decoded if item["amount"] is not None]
    if len(valid) < minimum:
        state = SupportState.PARTIAL if decoded else SupportState.INSUFFICIENT_EVIDENCE
        return empty_result("typed_assets", state, requirements, len(valid), FEATURES,
                            {"decoded_cells": decoded},
                            {"decoded_typed_cell_ratio": len(valid) / len(decoded) if decoded else None})
    input_total = sum(item["amount"] for _, ins, _ in tx_rows for item in ins if item["amount"] is not None)
    output_total = sum(item["amount"] for _, _, outs in tx_rows for item in outs if item["amount"] is not None)
    assets = Counter(item["asset_identifier"] for item in valid)
    amounts = [item["amount"] for item in valid]
    amount_counts = Counter(amounts)
    typed_txs = [(ins, outs) for _, ins, outs in tx_rows if ins or outs]
    values = {"typed_asset_count": len(assets), "asset_diversity": normalized_entropy(list(assets.elements())),
              "typed_cell_ratio": len(decoded) / target_cells if target_cells else None,
              "token_input_total": input_total, "token_output_total": output_total,
              "net_token_delta": output_total - input_total, "token_turnover": input_total + output_total,
              "repeated_token_amount_ratio": sum(count for count in amount_counts.values() if count > 1) / len(amounts),
              "token_amount_entropy": normalized_entropy(amounts),
              "token_fanout_ratio": sum(len(outs) > len(ins) and len(ins) > 0 for ins, outs in typed_txs) /
                                    len(typed_txs) if typed_txs else None,
              "token_fanin_ratio": sum(len(ins) > len(outs) and len(outs) > 0 for ins, outs in typed_txs) /
                                   len(typed_txs) if typed_txs else None}
    complete = all(item["decode_status"] == "DECODED" for item in decoded)
    support = family_support(observation, len(valid), minimum, require_inputs=True,
                             coverage_complete=complete)
    return FeatureResultV2("typed_assets", support, requirements, len(valid),
                           {"decoded_typed_cell_ratio": len(valid) / len(decoded),
                            "typed_target_cell_ratio": len(decoded) / target_cells if target_cells else None},
                           values, {"decoded_cells": decoded,
                                    "supporting_transaction_hashes": [tx for tx, ins, outs in tx_rows if ins or outs]})

