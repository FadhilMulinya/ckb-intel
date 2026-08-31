"""Reusable standard-library clients for CKB Node, Indexer, and Explorer."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import statistics
from dataclasses import dataclass
from typing import Any, Optional


class ClientUnavailable(RuntimeError):
    pass


_BOUNDARY_CACHE: dict[tuple[int, int], dict] = {}


def hex_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class JsonRpcClient:
    url: str
    timeout: float = 3.0

    def call(self, method: str, params: list) -> Any:
        body = json.dumps({"id": 1, "jsonrpc": "2.0", "method": method,
                           "params": params}).encode()
        request = urllib.request.Request(self.url, data=body,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ClientUnavailable(f"{self.url}: {exc}") from exc
        if payload.get("error"):
            raise ClientUnavailable(f"{method}: {payload['error']}")
        return payload.get("result")


class CkbRpcClient(JsonRpcClient):
    @classmethod
    def from_env(cls) -> "CkbRpcClient":
        return cls(os.getenv("CKB_RPC_URL", "http://127.0.0.1:8114"))

    def get_transaction(self, tx_hash: str) -> Optional[dict]:
        return self.call("get_transaction", [tx_hash, "0x2", True])

    def get_block_by_number(self, block_number: int) -> Optional[dict]:
        return self.call("get_block_by_number", [hex(block_number)])

    def get_tip_block_number(self) -> int:
        value = hex_int(self.call("get_tip_block_number", []))
        if value is None:
            raise ClientUnavailable("node returned no tip block number")
        return value

    def resolve_block_for_timestamp(self, timestamp_s: int, *, side: str) -> int:
        return binary_search_block(self, timestamp_s, side=side)


class CkbIndexerClient(JsonRpcClient):
    @classmethod
    def from_env(cls) -> "CkbIndexerClient":
        default = os.getenv("CKB_RPC_URL", "http://127.0.0.1:8114")
        return cls(os.getenv("CKB_INDEXER_URL", default))

    def get_transactions_for_lock(self, lock_script: dict, start_block: int,
                                  end_block: int, limit: int = 100) -> dict:
        search = {"script": lock_script, "script_type": "lock",
                  "filter": {"block_range": [hex(start_block), hex(end_block + 1)]}}
        return self.call("get_transactions", [search, "asc", hex(limit)])

    def get_cells_for_lock(self, lock_script: dict, start_block: int,
                           end_block: int, limit: int = 100) -> dict:
        search = {"script": lock_script, "script_type": "lock",
                  "filter": {"block_range": [hex(start_block), hex(end_block + 1)]}}
        return self.call("get_cells", [search, "asc", hex(limit)])


class ExplorerClient:
    def __init__(self, url: Optional[str] = None, timeout: float = 5.0):
        self.url = (url or os.getenv("EXPLORER_API_URL") or
                    "https://mainnet-api.explorer.nervos.org/api/v1").rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        from urllib.parse import urlencode
        query = "?" + urlencode(params) if params else ""
        request = urllib.request.Request(self.url + path + query,
                                         headers={"Accept": "application/vnd.api+json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise ClientUnavailable(f"Explorer {path}: {exc}") from exc

    def get_transaction(self, tx_hash: str) -> Optional[dict]:
        return self._get(f"/transactions/{tx_hash}", {"display_cells": "true"})

    def get_tip_block_number(self) -> int:
        payload = self._get("/statistics/tip_block_number")
        return int(payload["data"]["attributes"]["tip_block_number"])

    def get_block_by_number(self, number: int) -> dict:
        return self._get(f"/blocks/{number}")

    def resolve_block_for_timestamp(self, timestamp_s: int, *, side: str) -> int:
        return binary_search_block(self, timestamp_s, side=side)


def block_timestamp_seconds(payload: Optional[dict]) -> Optional[int]:
    if not payload:
        return None
    data = payload.get("data", payload)
    if isinstance(data, list):
        data = data[0] if data else {}
    header = data.get("header", data.get("attributes", data))
    parsed = hex_int(header.get("timestamp") or header.get("block_timestamp"))
    if parsed is None:
        return None
    return parsed // 1000 if parsed > 100_000_000_000 else parsed


def binary_search_block(client, timestamp_s: int, *, side: str) -> int:
    """Search CKB's non-decreasing consensus median-time metric."""
    if side not in {"start", "end"}:
        raise ValueError("side must be start or end")
    low, high = 0, client.get_tip_block_number()
    candidate = None
    while low <= high:
        middle = (low + high) // 2
        timestamp = consensus_median_time(client, middle)
        if side == "start":
            if timestamp >= timestamp_s:
                candidate, high = middle, middle - 1
            else:
                low = middle + 1
        else:
            if timestamp <= timestamp_s:
                candidate, low = middle, middle + 1
            else:
                high = middle - 1
    if candidate is None:
        raise ClientUnavailable(f"timestamp {timestamp_s} is outside canonical chain time")
    return candidate


def consensus_median_time(client, block_number: int) -> int:
    """Median timestamp of up to 37 blocks preceding `block_number`.

    RFC 0017 defines this timestamp metric and states that it never decreases.
    Genesis uses its own timestamp because no preceding header exists.
    """
    cache = getattr(client, "_median_time_cache", None)
    if cache is None:
        cache = {}
        setattr(client, "_median_time_cache", cache)
    if block_number in cache:
        return cache[block_number]
    if block_number == 0:
        values = [block_timestamp_seconds(client.get_block_by_number(0))]
    else:
        values = [block_timestamp_seconds(client.get_block_by_number(height))
                  for height in range(max(0, block_number - 37), block_number)]
    values = [value for value in values if value is not None]
    if not values:
        raise ClientUnavailable(f"no timestamps available before block {block_number}")
    value = int(statistics.median_low(values))
    cache[block_number] = value
    return value


def resolve_observation_boundaries(start_timestamp: int, end_timestamp: int,
                                   rpc: Optional[CkbRpcClient] = None,
                                   explorer: Optional[ExplorerClient] = None) -> dict:
    cache_key = (start_timestamp, end_timestamp)
    if rpc is None and explorer is None and cache_key in _BOUNDARY_CACHE:
        return dict(_BOUNDARY_CACHE[cache_key])
    for source, client in (("ckb_rpc", rpc or CkbRpcClient.from_env()),
                           ("explorer", explorer or ExplorerClient())):
        try:
            result = {"window_start_block": client.resolve_block_for_timestamp(start_timestamp, side="start"),
                    "window_end_block": client.resolve_block_for_timestamp(end_timestamp, side="end"),
                    "boundary_resolution_source": source,
                    "boundary_resolution_status": "complete"}
            if rpc is None and explorer is None:
                _BOUNDARY_CACHE[cache_key] = dict(result)
            return result
        except ClientUnavailable:
            continue
    result = {"window_start_block": None, "window_end_block": None,
            "boundary_resolution_source": None,
            "boundary_resolution_status": "unresolved"}
    if rpc is None and explorer is None:
        _BOUNDARY_CACHE[cache_key] = dict(result)
    return result
