from __future__ import annotations

"""
Phase 2 of the gap-closure plan (see CKB_Wallet_Classifier_Gap_Closure_Plan.md,
section 3, Phase 2): build the Cell-level feature families that address-pair
`edges` and the existing preprocess_ckb_wallets.py can't produce -- Cell
topology, Cell lifecycle, lock identity/reuse, type/asset presence, `since`,
and lock-hash-aware network features.

This is ADDITIVE, not a replacement for preprocess_ckb_wallets.py. That
script's temporal features (gap/burstiness/hour-of-day entropy) and DAO
features are already solid and are left alone -- run both and join the two
CSVs on `address` (see the bottom of this docstring).

Every feature family that depends on data Phase 1 confirmed is INCOMPLETE
at real-world scale (Cell lifecycle -- only ~10% of previous-outpoints were
locally materialized per the July diagnose run) carries an explicit
`..._support_n` count and `..._state` column (OK / INSUFFICIENT_EVIDENCE),
per the plan's Phase 2 support-condition design. Nothing here silently
turns "we don't know" into a value that looks like a real zero.

Identity note: wherever a real lock_hash is available (from Phase 1's
--backfill-from-addresses), features here use it instead of the raw
address_hash string. This is a genuine fix for the "edges keyed by
address" limitation Data_Aquisition.md documented -- CKB addresses have
more than one valid string encoding for the same lock script, so
address-string matching can undercount how often two wallets actually
interacted with each other. Where lock_hash isn't available (mostly
external counterparties Phase 1 never fetched address detail for),
this falls back to address_hash, same as the current edges table.

Usage:
    python3 preprocess_cell_features.py --data-dir ./ckb_data_v2 \
        --addresses ./ckb_data_v2/wallets_active.txt \
        --out-dir ./ckb_features

Then join with the existing pipeline's output:
    import pandas as pd
    a = pd.read_csv("ckb_features/features_full.csv", index_col="address")
    b = pd.read_csv("ckb_features/features_cell_layer.csv", index_col="address")
    combined = a.join(b, how="left")
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("preprocess_cell_features")

SHANNON_PER_CKB = 1e8
MULTISIG_FAMILY = "secp256k1_blake160_multisig_all"

# Minimum-observation thresholds per feature family (Phase 2 support-condition
# design). Below these, the family's derived stats are reported but flagged
# INSUFFICIENT_EVIDENCE rather than treated as trustworthy zeros/values.
MIN_OBS = {
    "lifecycle": 5,
    "since": 3,
    "topology": 1,
    "network": 1,
    "lock": 1,
}


def load_address_list(path: Path) -> list[str]:
    addrs, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line in seen:
            continue
        seen.add(line)
        addrs.append(line.split("\t", 1)[0].strip())
    return [a for a in addrs if a]


def herfindahl_index(values: np.ndarray) -> float:
    total = values.sum()
    if total <= 0:
        return np.nan
    shares = values / total
    return float((shares ** 2).sum())


def shannon_entropy_normalized(counts: np.ndarray) -> float:
    total = counts.sum()
    if total <= 0 or len(counts) <= 1:
        return np.nan
    p = counts[counts > 0] / total
    h = -(p * np.log(p)).sum()
    h_max = np.log(len(counts))
    return h / h_max if h_max > 0 else np.nan


# ---------------------------------------------------------------------------
# Load core Phase 1 tables
# ---------------------------------------------------------------------------

def load_core_tables(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    for table in ("tx_inputs", "cells"):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"no '{table}' table found -- run build_cell_graph.py --rebuild first.")

    log.info("loading tx_inputs...")
    tx_inputs = pd.read_sql_query(
        "SELECT tx_hash, input_index, prev_tx_hash, prev_index, lock_hash, lock_family, "
        "address_hash, capacity, since_raw_value, is_cellbase, block_timestamp FROM tx_inputs",
        conn,
    )
    log.info("loading cells...")
    cells = pd.read_sql_query(
        "SELECT out_tx_hash, out_index, lock_hash, lock_family, has_type_script, type_hash, "
        "capacity, address_hash, created_block_timestamp FROM cells",
        conn,
    )
    log.info("loaded %d tx_input row(s), %d cell row(s)", len(tx_inputs), len(cells))

    # Resolved identity: prefer real lock_hash, fall back to address_hash --
    # see module docstring.
    tx_inputs["identity"] = tx_inputs["lock_hash"].fillna(tx_inputs["address_hash"])
    cells["identity"] = cells["lock_hash"].fillna(cells["address_hash"])
    return tx_inputs, cells


def build_wallet_identity_map(addresses: list[str], tx_inputs: pd.DataFrame, cells: pd.DataFrame) -> dict:
    """address -> resolved identity (real lock_hash if any row for this
    address carries one, else the address itself)."""
    addr_set = set(addresses)
    id_map: dict[str, str] = {a: a for a in addresses}
    for df, col in ((tx_inputs, "address_hash"), (cells, "address_hash")):
        sub = df[df[col].isin(addr_set) & df["lock_hash"].notna()][[col, "lock_hash"]].drop_duplicates()
        for addr, lock_hash in sub.itertuples(index=False):
            id_map[addr] = lock_hash
    return id_map


# ---------------------------------------------------------------------------
# Transaction shape (Cell topology) -- computed over ALL participants, not
# just the target wallet, since shape is a property of the whole transaction.
# ---------------------------------------------------------------------------

def compute_tx_shape(tx_inputs: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    n_in = tx_inputs.groupby("tx_hash").size().rename("n_inputs")
    n_out = cells.groupby("out_tx_hash").size().rename("n_outputs")
    shape = pd.concat([n_in, n_out], axis=1)
    shape["n_inputs"] = shape["n_inputs"].fillna(0)
    shape["n_outputs"] = shape["n_outputs"].fillna(0)

    def _label(row):
        i, o = row["n_inputs"], row["n_outputs"]
        if i <= 1 and o <= 1:
            return "1_to_1"
        if i <= 1 and o > 1:
            return "1_to_n"
        if i > 1 and o <= 1:
            return "n_to_1"
        return "n_to_n"

    shape["shape"] = shape.apply(_label, axis=1)
    return shape  # indexed by tx_hash


def per_wallet_topology(addresses: list[str], tx_inputs: pd.DataFrame, cells: pd.DataFrame,
                         tx_shape: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    sent = tx_inputs[tx_inputs["address_hash"].isin(addr_set)][["address_hash", "tx_hash"]].drop_duplicates()
    recv = (cells[cells["address_hash"].isin(addr_set)][["address_hash", "out_tx_hash"]]
            .rename(columns={"out_tx_hash": "tx_hash"}).drop_duplicates())
    all_tx = pd.concat([sent, recv], ignore_index=True).drop_duplicates()
    all_tx = all_tx.merge(tx_shape[["shape"]], left_on="tx_hash", right_index=True, how="left")

    rows = []
    for addr, grp in all_tx.groupby("address_hash"):
        n = len(grp)
        counts = grp["shape"].value_counts()
        rows.append({
            "address": addr,
            "n_tx_cell_layer": n,
            "shape_1_to_1_ratio": counts.get("1_to_1", 0) / n if n else np.nan,
            "shape_1_to_n_ratio": counts.get("1_to_n", 0) / n if n else np.nan,
            "shape_n_to_1_ratio": counts.get("n_to_1", 0) / n if n else np.nan,
            "shape_n_to_n_ratio": counts.get("n_to_n", 0) / n if n else np.nan,
            "topology_state": "OK" if n >= MIN_OBS["topology"] else "INSUFFICIENT_EVIDENCE",
        })
    out = pd.DataFrame(rows).set_index("address") if rows else pd.DataFrame(
        columns=["n_tx_cell_layer", "shape_1_to_1_ratio", "shape_1_to_n_ratio",
                 "shape_n_to_1_ratio", "shape_n_to_n_ratio", "topology_state"]).rename_axis("address")
    return out.reindex(addresses)


# ---------------------------------------------------------------------------
# Cell lifecycle: how long a spent Cell existed before this wallet spent it.
# Only resolvable where the creating transaction is locally materialized --
# per Phase 1's real diagnose run, this is a MINORITY of inputs. Reported
# with an explicit support fraction, never silently imputed.
# ---------------------------------------------------------------------------

def per_wallet_lifecycle(addresses: list[str], tx_inputs: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    own_inputs = tx_inputs[tx_inputs["address_hash"].isin(addr_set)].copy()

    merged = own_inputs.merge(
        cells[["out_tx_hash", "out_index", "created_block_timestamp"]],
        left_on=["prev_tx_hash", "prev_index"], right_on=["out_tx_hash", "out_index"], how="left",
    )
    merged["cell_lifetime_s"] = merged["block_timestamp"] - merged["created_block_timestamp"]
    # Guard against bad/inconsistent timestamps rather than silently keeping a
    # nonsensical negative lifetime.
    merged.loc[merged["cell_lifetime_s"] < 0, "cell_lifetime_s"] = np.nan

    rows = []
    for addr, grp in merged.groupby("address_hash"):
        n_total = len(grp)
        resolved = grp["cell_lifetime_s"].dropna()
        n_resolved = len(resolved)
        row = {
            "address": addr,
            "n_inputs_total": n_total,
            "cell_lifetime_support_n": n_resolved,
            "cell_lifetime_support_ratio": n_resolved / n_total if n_total else np.nan,
            "cell_lifetime_mean_s": np.nan, "cell_lifetime_median_s": np.nan,
            "cell_lifetime_cv": np.nan, "same_block_spend_ratio": np.nan,
            "lifecycle_state": "OK" if n_resolved >= MIN_OBS["lifecycle"] else "INSUFFICIENT_EVIDENCE",
        }
        if n_resolved:
            row["cell_lifetime_mean_s"] = float(resolved.mean())
            row["cell_lifetime_median_s"] = float(resolved.median())
            m = resolved.mean()
            row["cell_lifetime_cv"] = float(resolved.std(ddof=0) / m) if m > 0 else np.nan
            row["same_block_spend_ratio"] = float((resolved == 0).mean())
        rows.append(row)

    out = pd.DataFrame(rows).set_index("address") if rows else pd.DataFrame(
        columns=["n_inputs_total", "cell_lifetime_support_n", "cell_lifetime_support_ratio",
                 "cell_lifetime_mean_s", "cell_lifetime_median_s", "cell_lifetime_cv",
                 "same_block_spend_ratio", "lifecycle_state"]).rename_axis("address")
    return out.reindex(addresses)


# ---------------------------------------------------------------------------
# Lock identity / reuse
# ---------------------------------------------------------------------------

def per_wallet_lock(addresses: list[str], tx_inputs: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    own_in = tx_inputs[tx_inputs["address_hash"].isin(addr_set)][["address_hash", "lock_hash", "lock_family"]]
    own_out = cells[cells["address_hash"].isin(addr_set)][["address_hash", "lock_hash", "lock_family"]]
    own = pd.concat([own_in, own_out], ignore_index=True)

    rows = []
    for addr, grp in own.groupby("address_hash"):
        n = len(grp)
        n_lock_known = grp["lock_hash"].notna().sum()
        n_distinct_locks = grp["lock_hash"].dropna().nunique()
        fam_counts = grp["lock_family"].value_counts()
        primary_family = fam_counts.index[0] if len(fam_counts) else "unknown"
        n_multisig = int((grp["lock_family"] == MULTISIG_FAMILY).sum())
        rows.append({
            "address": addr,
            "lock_hash_known_ratio": n_lock_known / n if n else np.nan,
            "n_distinct_lock_hashes": int(n_distinct_locks),
            "lock_family_primary": primary_family,
            "multisig_usage_ratio": n_multisig / n if n else np.nan,
            "lock_state": "OK" if n >= MIN_OBS["lock"] else "INSUFFICIENT_EVIDENCE",
        })
    out = pd.DataFrame(rows).set_index("address") if rows else pd.DataFrame(
        columns=["lock_hash_known_ratio", "n_distinct_lock_hashes", "lock_family_primary",
                 "multisig_usage_ratio", "lock_state"]).rename_axis("address")
    return out.reindex(addresses)


# ---------------------------------------------------------------------------
# Type script / asset presence (reliable regardless of Phase 1's lock-backfill
# gap -- has_type_script is read directly off each output's own record, not
# dependent on resolving a previous transaction).
# ---------------------------------------------------------------------------

def per_wallet_type_presence(addresses: list[str], cells: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    own_out = cells[cells["address_hash"].isin(addr_set)][["address_hash", "has_type_script", "type_hash"]]
    rows = []
    for addr, grp in own_out.groupby("address_hash"):
        n = len(grp)
        rows.append({
            "address": addr,
            "has_type_script_ratio": float(grp["has_type_script"].fillna(0).mean()) if n else np.nan,
            "n_distinct_type_hashes": int(grp["type_hash"].dropna().nunique()),
        })
    out = pd.DataFrame(rows).set_index("address") if rows else pd.DataFrame(
        columns=["has_type_script_ratio", "n_distinct_type_hashes"]).rename_axis("address")
    return out.reindex(addresses)


# ---------------------------------------------------------------------------
# `since` usage -- automation signal. Sentinel relative-0 values (raw_value
# == 0) are excluded from "meaningful" per Phase 1's finding.
# ---------------------------------------------------------------------------

def per_wallet_since(addresses: list[str], tx_inputs: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    own = tx_inputs[tx_inputs["address_hash"].isin(addr_set)][["address_hash", "since_raw_value"]]
    rows = []
    for addr, grp in own.groupby("address_hash"):
        n = len(grp)
        meaningful = grp["since_raw_value"].dropna()
        meaningful = meaningful[meaningful > 0]
        n_meaningful = len(meaningful)
        repeated_ratio = np.nan
        if n_meaningful:
            top_count = meaningful.value_counts().iloc[0]
            repeated_ratio = float(top_count / n_meaningful)
        rows.append({
            "address": addr,
            "uses_since_ratio": n_meaningful / n if n else np.nan,
            "since_support_n": n,
            "repeated_since_value_ratio": repeated_ratio,
            "since_state": "OK" if n >= MIN_OBS["since"] else "INSUFFICIENT_EVIDENCE",
        })
    out = pd.DataFrame(rows).set_index("address") if rows else pd.DataFrame(
        columns=["uses_since_ratio", "since_support_n", "repeated_since_value_ratio",
                 "since_state"]).rename_axis("address")
    return out.reindex(addresses)


# ---------------------------------------------------------------------------
# Network (lock-hash-aware fan-in/fan-out + capacity-weighted entropy)
# ---------------------------------------------------------------------------

def per_wallet_network(addresses: list[str], tx_inputs: pd.DataFrame, cells: pd.DataFrame,
                        id_map: dict) -> pd.DataFrame:
    addr_set = set(addresses)

    # Per-transaction participant identity sets (over ALL participants, so a
    # wallet's counterparties in a shared tx are visible).
    tx_out_identities = cells.groupby("out_tx_hash")["identity"].apply(set)
    tx_in_identities = tx_inputs.groupby("tx_hash")["identity"].apply(set)
    tx_out_capacity_by_identity = cells.groupby(["out_tx_hash", "identity"])["capacity"].sum()

    sent_tx = tx_inputs[tx_inputs["address_hash"].isin(addr_set)][["address_hash", "tx_hash"]].drop_duplicates()
    recv_tx = (cells[cells["address_hash"].isin(addr_set)][["address_hash", "out_tx_hash"]]
               .rename(columns={"out_tx_hash": "tx_hash"}).drop_duplicates())

    rows = []
    for addr in addresses:
        self_identity = id_map.get(addr, addr)
        out_counterparties: set = set()
        out_capacity_by_party: dict = {}
        for tx_hash in sent_tx.loc[sent_tx["address_hash"] == addr, "tx_hash"]:
            parties = tx_out_identities.get(tx_hash, set()) - {self_identity}
            out_counterparties |= parties
            for party in parties:
                cap = tx_out_capacity_by_identity.get((tx_hash, party), 0) or 0
                out_capacity_by_party[party] = out_capacity_by_party.get(party, 0) + cap

        in_counterparties: set = set()
        for tx_hash in recv_tx.loc[recv_tx["address_hash"] == addr, "tx_hash"]:
            in_counterparties |= (tx_in_identities.get(tx_hash, set()) - {self_identity})

        union = out_counterparties | in_counterparties
        reciprocity = (len(out_counterparties & in_counterparties) / len(union)) if union else np.nan
        cap_values = np.array(list(out_capacity_by_party.values()), dtype=float)
        entropy = shannon_entropy_normalized(cap_values) if len(cap_values) else np.nan
        hhi = herfindahl_index(cap_values) if len(cap_values) else np.nan

        n_tx = len(sent_tx.loc[sent_tx["address_hash"] == addr]) + len(recv_tx.loc[recv_tx["address_hash"] == addr])
        rows.append({
            "address": addr,
            "unique_counterparties_out_cell": len(out_counterparties),
            "unique_counterparties_in_cell": len(in_counterparties),
            "reciprocity_ratio_cell": reciprocity,
            "out_capacity_concentration_hhi_cell": hhi,
            "out_capacity_entropy_cell": entropy,
            "network_state": "OK" if n_tx >= MIN_OBS["network"] else "INSUFFICIENT_EVIDENCE",
        })

    return pd.DataFrame(rows).set_index("address").reindex(addresses)


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

def per_wallet_capacity(addresses: list[str], tx_inputs: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    sent = tx_inputs[tx_inputs["address_hash"].isin(addr_set)].groupby("address_hash")["capacity"].sum()
    received = cells[cells["address_hash"].isin(addr_set)].groupby("address_hash")["capacity"].sum()

    df = pd.DataFrame(index=pd.Index(addresses, name="address"))
    df["sent_capacity_ckb_cell"] = (sent.reindex(addresses).fillna(0) / SHANNON_PER_CKB)
    df["received_capacity_ckb_cell"] = (received.reindex(addresses).fillna(0) / SHANNON_PER_CKB)
    df["net_capacity_delta_ckb_cell"] = df["received_capacity_ckb_cell"] - df["sent_capacity_ckb_cell"]
    return df


# ---------------------------------------------------------------------------
# Cellbase touch (lower bound for miner detection -- see plan Phase 5 note)
# ---------------------------------------------------------------------------

def per_wallet_cellbase_touch(addresses: list[str], tx_inputs: pd.DataFrame) -> pd.DataFrame:
    addr_set = set(addresses)
    own = tx_inputs[tx_inputs["address_hash"].isin(addr_set)][["address_hash", "is_cellbase"]]
    touched = own[own["is_cellbase"] == 1].groupby("address_hash").size()
    df = pd.DataFrame(index=pd.Index(addresses, name="address"))
    df["n_cellbase_inputs_direct"] = touched.reindex(addresses).fillna(0).astype(int)
    df["touches_cellbase_directly"] = df["n_cellbase_inputs_direct"] > 0
    return df


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def assemble(addresses: list[str], db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA query_only = TRUE;")
    tx_inputs, cells = load_core_tables(conn)
    conn.close()

    id_map = build_wallet_identity_map(addresses, tx_inputs, cells)

    log.info("computing transaction shapes...")
    tx_shape = compute_tx_shape(tx_inputs, cells)

    log.info("computing per-wallet topology...")
    topo = per_wallet_topology(addresses, tx_inputs, cells, tx_shape)

    log.info("computing per-wallet Cell lifecycle...")
    lifecycle = per_wallet_lifecycle(addresses, tx_inputs, cells)

    log.info("computing per-wallet lock identity/reuse...")
    lock = per_wallet_lock(addresses, tx_inputs, cells)

    log.info("computing per-wallet type/asset presence...")
    type_presence = per_wallet_type_presence(addresses, cells)

    log.info("computing per-wallet since usage...")
    since = per_wallet_since(addresses, tx_inputs)

    log.info("computing per-wallet network (lock-hash-aware)...")
    network = per_wallet_network(addresses, tx_inputs, cells, id_map)

    log.info("computing per-wallet capacity...")
    capacity = per_wallet_capacity(addresses, tx_inputs, cells)

    log.info("computing per-wallet cellbase touch...")
    cellbase = per_wallet_cellbase_touch(addresses, tx_inputs)

    df = topo.join([lifecycle, lock, type_presence, since, network, capacity, cellbase], how="outer")
    df.index.name = "address"
    return df


def print_support_summary(df: pd.DataFrame) -> None:
    print("\n=== Phase 2 support/evidence summary ===")
    for state_col, label in (
        ("topology_state", "Cell topology"),
        ("lifecycle_state", "Cell lifecycle"),
        ("lock_state", "Lock identity"),
        ("since_state", "since usage"),
        ("network_state", "Network (cell-based)"),
    ):
        if state_col not in df.columns:
            continue
        counts = df[state_col].value_counts()
        n_ok = counts.get("OK", 0)
        n_insufficient = counts.get("INSUFFICIENT_EVIDENCE", 0)
        n_total = n_ok + n_insufficient
        pct_ok = 100 * n_ok / n_total if n_total else 0.0
        print(f"  {label:<24s} OK: {n_ok:5d}  INSUFFICIENT_EVIDENCE: {n_insufficient:5d}  ({pct_ok:.1f}% usable)")

    if "cell_lifetime_support_ratio" in df.columns:
        mean_support = df["cell_lifetime_support_ratio"].mean()
        print(f"\n  Mean Cell-lifecycle support ratio across all wallets: {mean_support:.1%}")
        print("  (this is scoped to YOUR OWN wallets' own spends, not the global tx_inputs "
              "population -- a wallet's own cell is usually created by an earlier transaction "
              "involving that same wallet, which your own collection already cached. This is "
              "typically much HIGHER than Phase 1's global previous-outpoint materialization "
              "figure (~10% in one real run), which included many other addresses' unrelated "
              "inputs. A low number here specifically -- for your own wallet population -- would "
              "be the one worth investigating; a low GLOBAL figure from build_cell_graph.py's "
              "--rebuild log is normal and not something --fetch-missing needs to fix for this "
              "feature family.)")

    if "lock_hash_known_ratio" in df.columns:
        mean_lock = df["lock_hash_known_ratio"].mean()
        print(f"\n  Mean lock_hash-known ratio across all wallets: {mean_lock:.1%}")
        print("  (own-wallet rows should be ~100% after --backfill-from-addresses; "
              "a lower number here means the counterparty side of a wallet's own "
              "transactions still relies on address-hash identity, which is expected.)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, required=True,
                   help="ckb_data_v2-style directory containing ckb_explorer.sqlite")
    p.add_argument("--addresses", type=Path, required=True,
                   help="Wallet list to featurize, e.g. wallets_active.txt")
    p.add_argument("--out-dir", type=Path, default=Path("./ckb_features"))
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    addresses = load_address_list(args.addresses)
    if not addresses:
        raise SystemExit("no addresses in --addresses -- nothing to do")
    log.info("featurizing %d wallet(s)...", len(addresses))

    df = assemble(addresses, db_path)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / "features_cell_layer.csv"
    df.to_csv(out_path, encoding="utf-8")
    log.info("wrote %s (%d rows, %d columns)", out_path, len(df), len(df.columns))

    print_support_summary(df)

    print(f"\nNext: join with features_full.csv from preprocess_ckb_wallets.py on 'address' "
          f"to combine temporal/DAO features with these Cell-layer features -- see this "
          f"script's module docstring for the two-line join. Do this BEFORE re-clustering "
          f"(plan Phase 4) or building archetype rules (plan Phase 3).")


if __name__ == "__main__":
    main()
