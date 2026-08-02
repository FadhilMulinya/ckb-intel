"""
Behavioral feature extraction shared by the training pipeline
(extract_features_real.py) and live inference (predict.py).

Turns an address's raw NDJSON transaction log into a fixed-length
behavioral feature vector. Features are chosen to be scale-agnostic
(ratios, coefficients of variation, entropy) rather than raw absolute
values like "70 CKB" or "1200 shannon fee", so the model learns behavioral
shape rather than memorizing magnitudes.
"""
import math
import statistics as stats
from collections import Counter


def shannon_entropy(counts):
    total = sum(counts)
    if total == 0:
        return 0.0
    probs = [c / total for c in counts if c > 0]
    return -sum(p * math.log2(p) for p in probs)


def extract_features(bot, txs):
    addr = bot["address"]
    ts = sorted(int(t["block_timestamp"]) for t in txs)
    intervals = [(ts[i + 1] - ts[i]) / 1000.0 for i in range(len(ts) - 1)]

    caps, n_outputs_per_tx, counterparty_counter, fees = [], [], Counter(), []
    for t in txs:
        fees.append(float(t["transaction_fee"]))
        outs = [o for o in t["display_outputs"] if o["address_hash"] != addr]
        n_outputs_per_tx.append(len(outs))
        for o in outs:
            caps.append(float(o["capacity"]) / 1e8)  # shannon -> CKB
            counterparty_counter[o["address_hash"]] += 1

    def safe_cv(vals):
        if len(vals) < 2:
            return 0.0
        m = stats.mean(vals)
        return (stats.stdev(vals) / m) if m else 0.0

    def safe_mean(vals):
        return stats.mean(vals) if vals else 0.0

    # pure-receive txs: this address appears only as a recipient, sends nothing
    # externally in that tx. High values here are the custodial/cold-storage
    # "quiet bot" signature (huge n_tx, near-zero external fan-out) that
    # mean_outputs_per_tx alone blurs together with a bot that sends small,
    # frequent amounts.
    n_pure_receive_tx = sum(1 for n in n_outputs_per_tx if n == 0)
    inbound_only_tx_frac = (n_pure_receive_tx / len(txs)) if txs else 0.0

    # max (not mean) outputs in a single tx: a payroll/batch-payer shows up as
    # ONE tx with dozens of outputs; a bot with a similar *mean* usually gets
    # there via many separate small-fanout sends instead. Mean conflates the
    # two shapes, max/mean tells them apart.
    max_outputs_per_tx = max(n_outputs_per_tx) if n_outputs_per_tx else 0
    mean_outs = safe_mean(n_outputs_per_tx)
    max_over_mean_outputs = (max_outputs_per_tx / mean_outs) if mean_outs else 0.0

    n_unique_counterparties = len(counterparty_counter)
    # how skewed is the counterparty distribution (0 = perfectly even rotation,
    # higher = concentrated on one/few counterparties, e.g. market_maker/fan_in sink)
    cp_entropy = shannon_entropy(list(counterparty_counter.values()))
    max_possible_entropy = math.log2(n_unique_counterparties) if n_unique_counterparties > 1 else 1.0
    cp_entropy_norm = cp_entropy / max_possible_entropy if max_possible_entropy else 0.0

    feats = {
        "address": addr,
        "archetype": bot["archetype"],
        # timing regularity -- the core "bot smell": how close to a metronome is this?
        "interval_cv": safe_cv(intervals),
        "interval_mean_log": math.log1p(safe_mean(intervals)),
        # amount regularity
        "capacity_cv": safe_cv(caps),
        # fee regularity (less discriminating here since fee is fixed by tx size,
        # but included since a real dataset might vary it)
        "fee_cv": safe_cv(fees),
        # fan-out / fan-in shape
        "n_unique_counterparties": n_unique_counterparties,
        "counterparty_entropy_norm": cp_entropy_norm,
        "mean_outputs_per_tx": safe_mean(n_outputs_per_tx),
        # burstiness: ratio of max to mean interval (metronomic sends -> ~1.0)
        "interval_max_over_mean": (max(intervals) / safe_mean(intervals)) if intervals and safe_mean(intervals) else 0.0,
        # targets the custodial/cold-storage "quiet bot" vs. batch-payer
        # "structural bot" confusion seen in held-out errors (see
        # eval_results.json's feature_importance / confusion matrix).
        "inbound_only_tx_frac": inbound_only_tx_frac,
        "max_over_mean_outputs": max_over_mean_outputs,
        "n_tx": len(txs),
    }
    return feats
