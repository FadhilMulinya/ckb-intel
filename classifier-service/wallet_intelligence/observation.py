from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

FEATURE_SCHEMA_VERSION = "ckb-behaviour-features-v1"
OBSERVATION_CONTRACT_VERSION = "wallet-observation-30d-v1"


class SupportState(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class FeatureResult:
    feature_family: str
    support_state: SupportState
    values: dict[str, Any]
    requirements: dict[str, Any]
    evidence: dict[str, Any]
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    observation_contract_version: str = OBSERVATION_CONTRACT_VERSION

    def as_dict(self) -> dict:
        result = asdict(self)
        result["support_state"] = self.support_state.value
        return result


def observation_support(observation: dict, *, minimum_transactions: int,
                        require_details: bool = True,
                        require_inputs: bool = False) -> SupportState:
    txs = observation.get("transactions") or []
    if len(txs) < minimum_transactions:
        return SupportState.INSUFFICIENT_EVIDENCE
    metadata = observation.get("metadata") or {}
    if require_details and metadata.get("detail_complete") is False:
        return SupportState.PARTIAL
    if require_inputs and metadata.get("input_resolution_complete") is False:
        return SupportState.PARTIAL
    return SupportState.SUPPORTED


def load_normalized_observation(conn, observation_id: str) -> dict:
    """Load the pure-dict feature input from the normalized SQLite schema."""
    conn.row_factory = __import__("sqlite3").Row
    observation = conn.execute(
        "SELECT * FROM wallet_observations WHERE observation_id = ?", (observation_id,)
    ).fetchone()
    if not observation:
        raise KeyError(f"observation not found: {observation_id}")
    metadata = dict(observation)
    target = metadata["canonical_lock_identifier"]
    tx_rows = conn.execute(
        """SELECT t.* FROM transactions t
           JOIN wallet_transaction_participation p ON p.tx_hash=t.tx_hash
           WHERE p.observation_id=? ORDER BY t.block_timestamp,t.transaction_index""",
        (observation_id,),
    ).fetchall()

    def script(table: str, digest: str | None):
        if not digest:
            return None
        row = conn.execute(f"SELECT code_hash,hash_type,args FROM {table} WHERE script_hash=?",
                           (digest,)).fetchone()
        return dict(row) if row else None

    transactions = []
    for tx_row in tx_rows:
        tx = dict(tx_row)
        tx["inputs"] = []
        for row in conn.execute("SELECT * FROM transaction_inputs WHERE tx_hash=? ORDER BY input_index",
                                (tx["tx_hash"],)):
            item = dict(row)
            item["resolved_capacity"] = item.pop("resolved_capacity_shannon")
            item["resolved_lock_script"] = script("lock_scripts", item["resolved_lock_script_hash"])
            item["resolved_type_script"] = script("type_scripts", item["resolved_type_script_hash"])
            item["resolved_lock_script_hash"] = (item.get("resolved_lock_script_hash") or
                                                  item.get("resolved_lock_identifier"))
            item["target_controls_input"] = item["resolved_lock_script_hash"] == target
            tx["inputs"].append(item)
        tx["outputs"] = []
        for row in conn.execute("SELECT * FROM cells WHERE creating_tx_hash=? ORDER BY output_index",
                                (tx["tx_hash"],)):
            item = dict(row)
            item["capacity"] = item.pop("capacity_shannon")
            item["lock_script"] = script("lock_scripts", item["lock_script_hash"])
            item["type_script"] = script("type_scripts", item["type_script_hash"])
            item["lock_script_hash"] = item.get("lock_script_hash") or item.get("lock_identifier")
            item["target_controls_output"] = item["lock_script_hash"] == target
            tx["outputs"].append(item)
        transactions.append(tx)
    return {"metadata": metadata, "transactions": transactions}
