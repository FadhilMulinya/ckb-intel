import json
import logging
import argparse

import numpy as np

import config
import acquisition
import features as feat_mod
import labeling
from cluster_model import load_artifacts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("ckb_wallet_intel.infer")


def _distance_to_centroids(x_scaled, km):
    centroids = km.cluster_centers_
    dists = np.linalg.norm(centroids - x_scaled, axis=1)
    return dists


def _pull_until_complete(address, force_refresh=False, max_seconds_per_wallet=None, max_attempts=6):
    """A single infer.py call is usually a one-off interactive request, so
    unlike dataset.py's batch mode (which happily leaves wallets partial across
    a run), we keep resuming the SAME wallet a few times in a row to try to
    reach status=complete before answering. Each attempt reuses the on-disk
    checkpoint, so this is just "try again" - never re-fetches finished pages."""
    record = None
    for attempt in range(1, max_attempts + 1):
        record = acquisition.pull_wallet_raw(address, force=(force_refresh and attempt == 1),
                                              max_seconds=max_seconds_per_wallet)
        if record["status"] == "complete":
            return record
        logger.info("Wallet still partial after attempt %d/%d (%d tx collected so far); retrying...",
                    attempt, max_attempts, len(record.get("transactions", [])))
    return record


def predict_address(address: str, scaler=None, km=None, profiles=None, feature_columns=None,
                     force_refresh: bool = False, known_miner_addresses: set = None,
                     max_seconds_per_wallet: int = None):
    if scaler is None:
        scaler, km, profiles, feature_columns = load_artifacts()
    known_miner_addresses = known_miner_addresses or set()

    logger.info("Pulling %d-day observation window for %s ...", config.OBSERVATION_WINDOW_DAYS, address)
    raw_record = _pull_until_complete(address, force_refresh=force_refresh,
                                       max_seconds_per_wallet=max_seconds_per_wallet)
    feat, meta = feat_mod.compute_wallet_features(
        raw_record, address_info=raw_record.get("address_info"),
        is_known_miner_address=address in known_miner_addresses,
    )

    heuristic_lbl, heuristic_conf, heuristic_reasons = labeling.heuristic_label(feat, meta)

    result = {
        "address": address,
        "evidence_state": meta["evidence_state"],
        "transactions_observed": meta["transactions_observed"],
        "observation_window_days": meta["window_days"],
        "pull_status": raw_record["status"],
        "heuristic_hint": heuristic_lbl,
        "heuristic_confidence": round(heuristic_conf, 3),
        "heuristic_reason_codes": heuristic_reasons,
    }
    if raw_record["status"] != "complete":
        result["note_pull_incomplete"] = (
            "Could not finish pulling this wallet's full observation window (network issues or a very "
            "large history). The result below is based on partial data; re-run this same command to "
            "continue from where it left off - already-fetched pages are cached and won't be re-fetched."
        )

    if meta["transactions_observed"] == 0:
        result["cluster"] = None
        result["note"] = "Wallet has no transactions in the observation window (INACTIVE)."
        return result

    if meta["evidence_state"] == "INSUFFICIENT_EVIDENCE":
        result["cluster"] = None
        result["note"] = (
            "Too few in-window transactions to trust a behavioural cluster assignment; "
            "returning the evidence-gated heuristic hint only."
        )
        return result

    x = np.array([[feat.get(c, 0.0) for c in feature_columns]])
    x_scaled = scaler.transform(x)
    cluster_id = int(km.predict(x_scaled)[0])
    dists = _distance_to_centroids(x_scaled[0], km)
    own_dist = dists[cluster_id]
    sorted_dists = np.sort(dists)
    margin = (sorted_dists[1] - sorted_dists[0]) if len(sorted_dists) > 1 else 0.0

    profile = profiles[str(cluster_id)]
    result["cluster"] = {
        "cluster_id": cluster_id,
        "suggested_archetype": profile["suggested_archetype"],
        "cluster_purity": profile["purity"],
        "description": profile["description"],
        "distance_to_cluster_center": round(float(own_dist), 3),
        "assignment_margin": round(float(margin), 3),
        "cluster_size_in_training_sample": profile["n_wallets"],
    }
    if heuristic_lbl != profile["suggested_archetype"]:
        result["cluster"]["note"] = (
            f"This wallet's own heuristic hint ({heuristic_lbl}) differs from its cluster's "
            f"majority archetype ({profile['suggested_archetype']}) - worth a manual look."
        )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Assign a CKB wallet to a discovered behaviour cluster.")
    p.add_argument("address", help="CKB address (ckb1... mainnet / ckt1... testnet, matching EXPLORER_BASE_URL)")
    p.add_argument("--force-refresh", action="store_true")
    p.add_argument("--max-seconds-per-wallet", type=int, default=config.MAX_SECONDS_PER_WALLET,
                   help="Per-attempt time budget before checkpointing and retrying.")
    args = p.parse_args()

    out = predict_address(args.address, force_refresh=args.force_refresh,
                           max_seconds_per_wallet=args.max_seconds_per_wallet)
    print(json.dumps(out, indent=2))
