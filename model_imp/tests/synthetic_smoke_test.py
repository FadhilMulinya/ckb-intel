"""
Offline smoke test: fabricates Explorer-shaped raw records for several archetypes
(miner, periodic bot, batch distributor, fan-in collector, normal human, inactive)
and runs them through features -> labeling -> training -> inference, WITHOUT
hitting the network. This validates the pipeline's internal logic; it does not
validate the real Explorer schema assumptions (see README "Validating against
the live API" section for that).
"""

import os
import sys
import json
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import features as feat_mod
import labeling
import pandas as pd

SHANNONS = 10 ** 8
DAY_MS = 24 * 3600 * 1000
random.seed(7)


def make_tx(tx_hash, block_number, ts_ms, inputs, outputs, is_cellbase=False):
    return {
        "transaction_hash": tx_hash,
        "block_number": str(block_number),
        "block_timestamp": str(ts_ms),
        "is_cellbase": is_cellbase,
        "display_inputs": inputs,
        "display_outputs": outputs,
    }


def io(address, capacity_ckb, cell_index=0, from_cellbase=False, since=0, generated_tx_hash=None, cell_type="normal"):
    return {
        "address_hash": address,
        "capacity": str(int(capacity_ckb * SHANNONS)),
        "cell_index": str(cell_index),
        "from_cellbase": from_cellbase,
        "since": since,
        "generated_tx_hash": generated_tx_hash,
        "cell_type": cell_type,
    }


def build_miner(address, n_tx=25, now_ms=None):
    now_ms = now_ms or 1_700_000_000_000
    txs = []
    for i in range(n_tx):
        ts = now_ms - i * 3600_000 * 6
        txs.append(make_tx(f"0xminer{i}", 1000 + i, ts,
                            inputs=[io(address, 500, from_cellbase=True)],
                            outputs=[io(address, 499.9)]))
    return txs, True


def build_bot(address, n_tx=40, now_ms=None):
    now_ms = now_ms or 1_700_000_000_000
    txs = []
    counterparty = "0xcounterpartyBOT"
    for i in range(n_tx):
        ts = now_ms - i * 3600_000  # exactly hourly, very periodic
        txs.append(make_tx(f"0xbot{i}", 2000 + i, ts,
                            inputs=[io(address, 100, since=0x0000000000000005)],
                            outputs=[io(counterparty, 99.9), io(address, 0.0)]))
    return txs, False


def build_batch_distributor(address, n_tx=15, now_ms=None):
    now_ms = now_ms or 1_700_000_000_000
    txs = []
    for i in range(n_tx):
        ts = now_ms - i * 3600_000 * 8
        outs = [io(f"0xrecipient{i}_{j}", 10.0 + j) for j in range(8)]
        txs.append(make_tx(f"0xbatch{i}", 3000 + i, ts, inputs=[io(address, 90)], outputs=outs))
    return txs, False


def build_fan_in_collector(address, n_tx=15, now_ms=None):
    now_ms = now_ms or 1_700_000_000_000
    txs = []
    for i in range(n_tx):
        ts = now_ms - i * 3600_000 * 10
        ins = [io(f"0xsource{i}_{j}", 5.0 + j) for j in range(7)]
        txs.append(make_tx(f"0xfanin{i}", 4000 + i, ts, inputs=ins, outputs=[io(address, 34.5)]))
    return txs, False


def build_normal_human(address, n_tx=6, now_ms=None):
    now_ms = now_ms or 1_700_000_000_000
    txs = []
    gaps_h = [3, 55, 12, 100, 8, 40]
    ts = now_ms
    for i in range(n_tx):
        ts -= gaps_h[i % len(gaps_h)] * 3600_000 + random.randint(0, 5000_000)
        cp = f"0xfriend{i}"
        txs.append(make_tx(f"0xhuman{i}", 5000 + i, ts, inputs=[io(address, 20 + i)], outputs=[io(cp, 19.9 + i)]))
    return txs, False


def wrap(address, txs, window_days=30):
    return {
        "address": address, "window_days": window_days, "transactions": txs,
        "status": "complete", "hit_max_cap": False,
    }


def main():
    builders = {
        "MINER_POOL": build_miner,
        "BOT_AUTOMATION": build_bot,
        "BATCH_DISTRIBUTOR": build_batch_distributor,
        "FAN_IN_COLLECTOR": build_fan_in_collector,
        "NORMAL_HUMAN": build_normal_human,
    }

    rows = []
    for expected_label, builder in builders.items():
        for rep in range(6):  # a few noisy replicas per archetype so training has signal
            addr = f"0x{expected_label}_{rep}"
            txs, is_miner = builder(addr)
            raw = wrap(addr, txs)
            feat, meta = feat_mod.compute_wallet_features(raw, is_known_miner_address=is_miner)
            lbl, conf, reasons = labeling.heuristic_label(feat, meta)
            row = {"address": addr, "expected": expected_label, "heuristic": lbl,
                   "confidence": round(conf, 2), "reasons": reasons}
            row.update(feat)
            row.update(meta)
            row["label"] = lbl
            row["label_confidence"] = conf
            rows.append(row)

    # inactive wallet
    raw = wrap("0xINACTIVE_0", [])
    feat, meta = feat_mod.compute_wallet_features(raw)
    lbl, conf, reasons = labeling.heuristic_label(feat, meta)
    row = {"address": "0xINACTIVE_0", "expected": "INACTIVE", "heuristic": lbl, "confidence": conf, "reasons": reasons}
    row.update(feat); row.update(meta); row["label"] = lbl; row["label_confidence"] = conf
    rows.append(row)

    print("\n=== Heuristic labeling check (expected vs assigned) ===")
    correct = 0
    for r in rows:
        ok = r["expected"] == r["heuristic"]
        correct += ok
        print(f"{'OK ' if ok else 'MISS'} expected={r['expected']:<18} got={r['heuristic']:<18} conf={r['confidence']:.2f} reasons={r['reasons']}")
    print(f"\n{correct}/{len(rows)} heuristic labels matched the synthetic archetype design.")

    df = pd.DataFrame(rows)
    csv_path = os.path.join(os.path.dirname(__file__), "synthetic_dataset.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nWrote synthetic dataset -> {csv_path} ({len(df)} rows)")

    # ---- now actually fit the unsupervised cluster model on this synthetic set ----
    from cluster_model import load_clusterable_frame, fit as fit_clusters, CLUSTER_FEATURE_COLUMNS
    import cluster_model as cm

    # point cluster_model at our synthetic CSV instead of the real dataset path
    cm.DATASET_PATH = csv_path
    clusterable, excluded = load_clusterable_frame(csv_path)
    print(f"\nClusterable wallets: {len(clusterable)}, excluded (inactive/insufficient): {len(excluded)}")

    scaler, km, profiles, sil_scores = cm.fit(k_min=3, k_max=5)

    print("\n=== Discovered clusters ===")
    for cid, p in profiles.items():
        print(f"Cluster {cid} (n={p['n_wallets']}, purity={p['purity']}): {p['suggested_archetype']}")
        print(f"   {p['description']}")

    # inference smoke test: predict on one wallet of each archetype using the saved artifacts
    from infer import predict_address
    import features as feat_mod2

    print("\n=== Cluster assignment sanity check (using in-memory raw records, no network) ===")
    mismatches = 0
    for expected_label, builder in builders.items():
        addr = f"0x{expected_label}_check"
        txs, is_miner = builder(addr)
        raw = wrap(addr, txs)
        # monkeypatch acquisition.pull_wallet_raw for this one call to avoid network/disk
        import acquisition as acq
        orig = acq.pull_wallet_raw
        acq.pull_wallet_raw = lambda *a, **k: raw
        try:
            result = predict_address(addr, scaler=scaler, km=km, profiles=profiles,
                                      feature_columns=cm.CLUSTER_FEATURE_COLUMNS,
                                      known_miner_addresses={addr} if is_miner else set())
        finally:
            acq.pull_wallet_raw = orig
        got = result["cluster"]["suggested_archetype"] if result["cluster"] else result.get("note")
        ok = got == expected_label
        mismatches += (not ok)
        print(f"{'OK ' if ok else 'DIFF'} expected~{expected_label:<18} cluster_suggests={got}")

    print("\nSMOKE TEST PASSED (clustering pipeline ran end-to-end without errors)")


if __name__ == "__main__":
    main()
