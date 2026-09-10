"""Service orchestration for the current CKB-native V2 behaviour pipeline.

This module deliberately contains no feature formulas and no identity
classification.  It loads frozen observations and delegates all feature and
rule computation to ``classifier-service/wallet_intelligence/features_v2``.
"""
from __future__ import annotations

import sqlite3
import datetime as dt
import os
import tempfile
from pathlib import Path
from typing import Any

from wallet_intelligence.clients import ClientUnavailable, ExplorerClient
from wallet_intelligence.normalization import ObservationContract, install_schema, normalize_transaction, persist_observation, persist_transaction, script_hash
from wallet_intelligence.resolution import resolve_transaction_inputs

REPO_ROOT = Path(__file__).resolve().parents[1]
CKB_DATA = REPO_ROOT / "ckb_data"

from wallet_intelligence.features_v2.pipeline import assess_observation_v2, load_observation_v2  # noqa: E402

V2_VERSION = "wallet-behaviour-v2"
NETWORK = "mainnet"
FAMILIES = ("temporal", "periodicity", "topology", "lifecycle", "templates",
            "scripts", "typed_assets", "capacity", "lineage")


class AnalysisError(Exception):
    """Expected service-level error with a stable status code."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for bit, generator in enumerate(generators):
            if (top >> bit) & 1:
                chk ^= generator
    return chk


def validate_ckb_address(address: str) -> bool:
    """Validate a mainnet CKB bech32 address without network access."""
    if not isinstance(address, str) or not address or address.lower() != address:
        return False
    if not address.startswith("ckb1") or address.count("1") != 1:
        return False
    separator = address.rfind("1")
    data = address[separator + 1:]
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    if len(data) < 7 or any(char not in charset for char in data):
        return False
    values = [charset.index(char) for char in data]
    # CKB mainnet addresses use either the original Bech32 checksum
    # (notably short addresses) or Bech32m (full addresses).
    checksum = _bech32_polymod([ord(char) >> 5 for char in "ckb"] + [0] +
                                [ord(char) & 31 for char in "ckb"] + values)
    return checksum in {1, 0x2BC830A3}


def _observation_status(collection_state: str | None) -> str:
    if collection_state == "FAILED_INVALID_ADDRESS":
        return "INVALID_ADDRESS"
    if collection_state and collection_state.startswith("FAILED_"):
        return "COLLECTION_FAILED"
    if collection_state == "PARTIAL":
        return "PARTIAL"
    return "SUPPORTED"


class V2WalletService:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (CKB_DATA / "ckb_data_v2" / "ckb_explorer.sqlite")

    def analyze_frozen(self, address: str) -> dict[str, Any]:
        if not validate_ckb_address(address):
            raise AnalysisError("INVALID_ADDRESS", "invalid mainnet CKB address")
        if not self.db_path.exists():
            raise AnalysisError("COLLECTION_FAILED", f"database not found: {self.db_path}")

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT observation_id FROM wallet_observations WHERE address=? LIMIT 1",
                (address,),
            ).fetchone()
            state_row = conn.execute(
                "SELECT collection_state FROM wallet_collection_state WHERE address=? LIMIT 1",
                (address,),
            ).fetchone()
            collection_state = state_row[0] if state_row else None
            if not row:
                if collection_state and collection_state.startswith("FAILED_"):
                    raise AnalysisError("COLLECTION_FAILED", collection_state)
                raise AnalysisError("NOT_IN_FROZEN_DATASET", "address is not in the frozen observation set")
            observation = load_observation_v2(conn, row[0], collection_state=collection_state)
            result = assess_observation_v2(observation)

        metadata = observation.get("metadata", {})
        transactions = observation.get("transactions", [])
        evidence = {
            "transactions": len(transactions),
            "inputs": sum(len(tx.get("inputs", [])) for tx in transactions),
            "outputs": sum(len(tx.get("outputs", [])) for tx in transactions),
            "cells": len(observation.get("observed_target_cells", [])),
        }
        return {
            "version": V2_VERSION,
            "address": address,
            "network": NETWORK,
            "observation": {
                "source": metadata.get("source_version", "ckb_explorer_api"),
                "mode": "frozen",
                "window_start": metadata.get("window_start_timestamp"),
                "window_end": metadata.get("window_end_timestamp"),
                "status": _observation_status(collection_state),
            },
            "evidence": evidence,
            "feature_support": {
                family: result["features"][family]["support_state"] for family in FAMILIES
            },
            "features": result["features"],
            "behaviors": result["rules"],
            "limitations": [
                "Observable behaviour only; no identity or ownership attribution.",
                "Results are bounded by the frozen cohort and 30-day observation window.",
            ],
        }

    def analyze(self, address: str, *, live: bool = False) -> dict[str, Any]:
        if not validate_ckb_address(address):
            raise AnalysisError("INVALID_ADDRESS", "invalid mainnet CKB address")
        if live:
            return self.analyze_live(address)
        return self.analyze_frozen(address)

    def analyze_live(self, address: str) -> dict[str, Any]:
        """Collect one explicit rolling 30-day observation without touching frozen SQLite."""
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())
        start, end = now - 30 * 86400, now
        explorer = ExplorerClient()
        try:
            detail = explorer.get_address(address) or {}
            data = detail.get("data", detail)
            if isinstance(data, list): data = data[0] if data else {}
            attrs = (data or {}).get("attributes", {})
            lock_script = attrs.get("lock_script")
            target_lock = (attrs.get("lock_hash") or attrs.get("lock_script_hash") or
                           script_hash(lock_script))
            if not target_lock:
                raise AnalysisError("COLLECTION_FAILED", "Explorer returned no lock identifier")
            summaries, page, total = [], 1, None
            page_size = max(1, int(os.getenv("EXPLORER_LIVE_PAGE_SIZE", "50")))
            while True:
                payload = explorer.get_address_transactions(address, page=page, page_size=page_size) or {}
                items = payload.get("data") or []
                if not items: break
                summaries.extend(items)
                total = (payload.get("meta") or {}).get("total", total)
                if total is not None and len(summaries) >= int(total): break
                # Explorer sorts by time.desc. Once a page reaches before the
                # rolling-window boundary, older pages cannot contain eligible
                # observations and must not be fetched (critical for wallets
                # with millions of historical transactions).
                timestamps = []
                for item in items:
                    try:
                        timestamps.append(int((item.get("attributes") or {}).get("block_timestamp", 0)))
                    except (TypeError, ValueError):
                        continue
                if timestamps and min(timestamps) < start * 1000:
                    break
                if len(items) < page_size: break
                page += 1
            def in_window(item: dict) -> bool:
                try:
                    timestamp = int((item.get("attributes") or {}).get("block_timestamp", 0))
                except (TypeError, ValueError):
                    return False
                return start * 1000 <= timestamp < end * 1000
            summaries = [item for item in summaries if in_window(item)]
            with tempfile.NamedTemporaryFile(prefix="ckb-live-", suffix=".sqlite") as tmp:
                conn = sqlite3.connect(tmp.name)
                install_schema(conn)
                conn.execute("CREATE TABLE raw_transactions (tx_hash TEXT PRIMARY KEY, raw_json TEXT NOT NULL, fetched_at INTEGER NOT NULL, source_kind TEXT NOT NULL)")
                transactions = []
                for item in summaries:
                    item_attrs = item.get("attributes") or {}
                    tx_hash = item_attrs.get("transaction_hash") or item.get("id")
                    if not tx_hash: continue
                    payload = explorer.get_transaction(tx_hash)
                    if not payload: continue
                    tx = normalize_transaction(payload, target_lock_hash=target_lock, target_address=address)
                    conn.execute("INSERT OR REPLACE INTO raw_transactions VALUES (?,?,?,?)", (tx_hash, __import__("json").dumps(payload), now, "ckb_explorer_live"))
                    persist_transaction(conn, tx)
                    resolve_transaction_inputs(conn, tx, explorer=explorer)
                    persist_transaction(conn, tx)
                    transactions.append(tx)
                observation = ObservationContract(
                    address=address, canonical_lock_identifier=target_lock,
                    window_start_timestamp=start, window_end_timestamp=end,
                    boundary_resolution_source="live_utc_rolling_window",
                    boundary_resolution_status="complete", transactions_observed=len(transactions),
                    listing_status="complete", detail_status="complete" if len(transactions) == len(summaries) else "incomplete",
                    input_resolution_status="complete" if all(i.get("resolution_status") in {"complete", "not_applicable"} for tx in transactions for i in tx["inputs"]) else "incomplete",
                    listing_complete=True, detail_complete=len(transactions) == len(summaries),
                    input_resolution_complete=all(i.get("resolution_status") in {"complete", "not_applicable"} for tx in transactions for i in tx["inputs"]),
                    collection_timestamp=dt.datetime.now(dt.timezone.utc).isoformat())
                persist_observation(conn, observation, transactions)
                conn.commit()
                from wallet_intelligence.features_v2.pipeline import load_observation_v2, assess_observation_v2
                normalized = load_observation_v2(conn, observation.observation_id, collection_state="COMPLETE" if observation.detail_complete else "PARTIAL")
                result = assess_observation_v2(normalized)
                metadata = normalized.get("metadata", {})
                evidence = {"transactions": len(transactions), "inputs": sum(len(t["inputs"]) for t in transactions), "outputs": sum(len(t["outputs"]) for t in transactions), "cells": len(normalized.get("observed_target_cells", []))}
                return {"version": V2_VERSION, "address": address, "network": NETWORK,
                        "observation": {"source": "ckb_explorer_mainnet", "mode": "live", "window_start": start, "window_end": end, "status": "SUPPORTED" if observation.detail_complete else "PARTIAL", "collection_timestamp": metadata.get("collection_timestamp")},
                        "evidence": evidence, "feature_support": {family: result["features"][family]["support_state"] for family in FAMILIES},
                        "features": result["features"], "behaviors": result["rules"],
                        "limitations": ["Observable behaviour only; no identity or ownership attribution.", "Live evidence is bounded to the UTC rolling 30-day window."] + ([] if observation.detail_complete else ["Explorer transaction detail collection was incomplete."])}
        except AnalysisError: raise
        except ClientUnavailable as exc:
            raise AnalysisError("COLLECTION_FAILED", str(exc)) from exc
        except Exception as exc:
            raise AnalysisError("COLLECTION_FAILED", f"live Explorer collection failed: {exc}") from exc
