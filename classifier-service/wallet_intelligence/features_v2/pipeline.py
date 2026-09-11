from __future__ import annotations

import json

from . import capacity, lifecycle, lineage, periodicity, scripts, templates, temporal, topology, typed_assets
from .rules import evaluate


def _raw(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def load_observation_v2(conn, observation_id: str, collection_state: str | None = None,
                        transaction_timing: dict | None = None) -> dict:
    from wallet_intelligence.observation import load_normalized_observation
    observation = load_normalized_observation(conn, observation_id)
    observation["metadata"]["collection_state"] = collection_state
    transaction_by_hash = {tx["tx_hash"]: tx for tx in observation["transactions"]}
    for tx in observation["transactions"]:
        for item in tx.get("inputs", []):
            raw = _raw(item.get("raw_json")); item["raw"] = raw
            item["previous_tx_hash"] = item.get("previous_tx_hash") or raw.get("generated_tx_hash")
            index = item.get("previous_output_index")
            if index is None:
                index = raw.get("cell_index")
            try: item["previous_output_index"] = int(index) if index is not None else None
            except (TypeError, ValueError): item["previous_output_index"] = None
        for item in tx.get("outputs", []):
            item["raw"] = _raw(item.get("raw_json"))
    start = observation["metadata"]["window_start_timestamp"]
    end = observation["metadata"]["window_end_timestamp"]
    lifecycles, observed, spent = [], set(), set()
    for tx in observation["transactions"]:
        for cell in tx.get("inputs", []):
            point = (cell.get("previous_tx_hash"), cell.get("previous_output_index"))
            if cell.get("target_controls_input") and all(value is not None for value in point):
                observed.add(point); spent.add(point)
                creation = ((transaction_timing or {}).get(point[0]) if transaction_timing is not None
                            else conn.execute("SELECT block_timestamp,block_number FROM transactions WHERE tx_hash=?",
                                              (point[0],)).fetchone())
                if (creation and creation[0] is not None and
                        tx.get("block_timestamp") is not None and
                        start <= tx["block_timestamp"] < end):
                    lifecycles.append({"creating_tx_hash": point[0], "output_index": point[1],
                                       "consuming_tx_hash": tx["tx_hash"],
                                       "creation_timestamp": creation[0],
                                       "consumption_timestamp": tx["block_timestamp"],
                                       "creation_block": creation[1], "consumption_block": tx.get("block_number"),
                                       "cell_lifetime_seconds": tx["block_timestamp"] - creation[0],
                                       "cell_lifetime_blocks": tx["block_number"] - creation[1]
                                       if creation[1] is not None and tx.get("block_number") is not None else None})
        for cell in tx.get("outputs", []):
            if cell.get("target_controls_output"):
                observed.add((tx["tx_hash"], cell.get("output_index")))
    observation["lifecycle_records"] = lifecycles
    observation["observed_target_cells"] = sorted(observed)
    observation["right_censored_target_cells"] = sorted(observed - spent)
    return observation


def assess_observation_v2(observation: dict) -> dict:
    results = {}
    results["temporal"] = temporal.extract(observation)
    results["periodicity"] = periodicity.extract(observation)
    results["topology"] = topology.extract(observation)
    results["lifecycle"] = lifecycle.extract(observation)
    results["templates"] = templates.extract(observation, results["periodicity"])
    results["scripts"] = scripts.extract(observation)
    results["typed_assets"] = typed_assets.extract(observation)
    results["capacity"] = capacity.extract(observation)
    results["lineage"] = lineage.extract(observation)
    rules = evaluate(observation, results)
    return {"features": {name: result.as_dict() for name, result in results.items()},
            "rules": [rule.as_dict() for rule in rules]}
