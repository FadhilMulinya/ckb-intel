from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("preprocess_ckb")

_EDGES_TS_SCALE_INFO: dict = {"multiplier": 1.0, "edges_total_rows": None,
                               "edges_min_ts": None, "edges_max_ts": None,
                               "unit_detected": "unknown"}

SHANNON_PER_CKB = 1e8



def load_address_list(path: Optional[Path]) -> list[str]:
    if path is None:
        return []
    if not path.exists():
        log.warning("address list not found: %s (treating as empty)", path)
        return []
    out, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        addr = line.split("\t", 1)[0].strip()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out



def _safe_filename(address: str) -> str:
    if len(address) <= 150:
        return address
    import hashlib
    h = hashlib.sha1(address.encode()).hexdigest()[:16]
    return f"{address[:100]}__LONG_{h}"


def load_provenance(data_dir: Path, address: str) -> Optional[dict]:
    p = data_dir / "provenance" / f"{_safe_filename(address)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_provenance_frame(addresses: list[str], data_dir: Path) -> pd.DataFrame:
    rows = []
    n_missing = 0
    for addr in addresses:
        prov = load_provenance(data_dir, addr)
        if prov is None:
            n_missing += 1
            rows.append({"address": addr, "has_provenance": False})
            continue

        deepest = prov.get("deepest_block") or {}
        shallowest = prov.get("shallowest_block") or {}
        n_tx = prov.get("n_tx_in_window", 0) or 0
        n_detail = prov.get("n_tx_detail_fetched", 0) or 0

        rows.append({
            "address": addr,
            "has_provenance": True,
            "window_start_epoch": prov.get("window_start_epoch"),
            "window_end_epoch": prov.get("window_end_epoch"),
            "lookback_days": prov.get("lookback_days"),
            "n_tx_in_window": n_tx,
            "n_tx_detail_fetched": n_detail,
            "n_tx_detail_remaining": prov.get("n_tx_detail_remaining", 0),
            "n_tx_detail_remaining_is_exact": prov.get("n_tx_detail_remaining_is_exact", True),
            "fetch_order": prov.get("fetch_order", "sequential"),
            "listing_truncated": bool(prov.get("listing_truncated")),
            "detail_sampled": bool(prov.get("detail_sampled")),
            "n_dao_events_prov": prov.get("n_dao_events", 0),
            "deepest_ts": deepest.get("block_timestamp_epoch"),
            "shallowest_ts": shallowest.get("block_timestamp_epoch"),
            "detail_coverage": (n_detail / n_tx) if n_tx > 0 else np.nan,
        })

    if n_missing:
        log.warning(
            "%d/%d addresses have no provenance file -- they were never "
            "collected by collect_target_wallets.py. They'll pass through "
            "with all behavioral features as NaN; re-run collection before "
            "treating them as 'unused'.",
            n_missing, len(addresses),
        )

    df = pd.DataFrame(rows).set_index("address")

    if "window_start_epoch" in df.columns:
        span = (df["window_end_epoch"] - df["window_start_epoch"]) / 86400.0
        df["window_days"] = span.where(span.notna() & (span > 0), df.get("lookback_days"))
    else:
        df["window_days"] = np.nan

    df["active_span_days"] = (
        (df["shallowest_ts"] - df["deepest_ts"]) / 86400.0
    ).clip(lower=0) if "shallowest_ts" in df.columns else np.nan

    return df



def fetch_timestamps(conn: sqlite3.Connection, address: str) -> tuple[list[int], set]:
    try:
        cur = conn.execute(
            "SELECT tx_hash, MIN(block_timestamp) FROM address_tx_seen "
            "WHERE address = ? AND block_timestamp IS NOT NULL AND tx_hash IS NOT NULL "
            "GROUP BY tx_hash",
            (address,),
        )
        rows = cur.fetchall()
        tx_hashes = {h for h, _ in rows}
        ts_list = sorted(t for _, t in rows)
        return ts_list, tx_hashes
    except sqlite3.OperationalError:
        log.warning(
            "address_tx_seen has no tx_hash column -- can't dedupe timing "
            "events per transaction, and compute_edge_features can't scope "
            "edges to this wallet's own transactions. Timing features may "
            "be inflated and sent/received tx counts may exceed "
            "n_tx_in_window for wallets that are counterparties in other "
            "collected wallets' transactions."
        )
        cur = conn.execute(
            "SELECT block_timestamp FROM address_tx_seen "
            "WHERE address = ? AND block_timestamp IS NOT NULL "
            "ORDER BY block_timestamp ASC",
            (address,),
        )
        return [r[0] for r in cur.fetchall()], set()


def shannon_entropy_normalized(counts: np.ndarray) -> float:
    total = counts.sum()
    if total <= 0:
        return np.nan
    p = counts[counts > 0] / total
    h = -(p * np.log(p)).sum()
    h_max = np.log(len(counts))
    return h / h_max if h_max > 0 else np.nan


def burstiness_index(gaps: np.ndarray) -> float:
    if len(gaps) < 2:
        return np.nan
    mu, sigma = gaps.mean(), gaps.std(ddof=0)
    denom = sigma + mu
    return (sigma - mu) / denom if denom > 0 else np.nan


def compute_timing_features(conn: sqlite3.Connection, address: str) -> tuple[dict, set]:
    ts_list, tx_hashes = fetch_timestamps(conn, address)
    n = len(ts_list)
    feat = {
        "n_timing_events": n,
        "gap_mean_s": np.nan, "gap_median_s": np.nan, "gap_cv": np.nan,
        "burstiness": np.nan,
        "hour_of_day_entropy": np.nan, "day_of_week_entropy": np.nan,
        "tx_per_active_day": np.nan,
    }
    if n == 0:
        return feat, tx_hashes

    ts = np.array(ts_list, dtype=np.int64)
    if n >= 2:
        gaps = np.diff(ts).astype(float)
        gaps = gaps[gaps >= 0]
        if len(gaps) >= 2:
            feat["gap_mean_s"] = float(gaps.mean())
            feat["gap_median_s"] = float(np.median(gaps))
            gmean = gaps.mean()
            feat["gap_cv"] = float(gaps.std(ddof=0) / gmean) if gmean > 0 else np.nan
            feat["burstiness"] = burstiness_index(gaps)

    hours = pd.to_datetime(ts, unit="s", utc=True).hour.to_numpy()
    dows = pd.to_datetime(ts, unit="s", utc=True).dayofweek.to_numpy()
    feat["hour_of_day_entropy"] = shannon_entropy_normalized(np.bincount(hours, minlength=24))
    feat["day_of_week_entropy"] = shannon_entropy_normalized(np.bincount(dows, minlength=7))

    span_days = max((ts.max() - ts.min()) / 86400.0, 1.0)
    feat["tx_per_active_day"] = n / span_days
    return feat, tx_hashes



def resolve_wallet_identifiers(conn: sqlite3.Connection, address: str) -> tuple[Optional[str], list[str]]:
    real_lock_hash = None
    cur = conn.execute(
        "SELECT lock_hash FROM raw_addresses WHERE address = ? AND lock_hash IS NOT NULL",
        (address,),
    )
    row = cur.fetchone()
    if row:
        real_lock_hash = row[0]
    else:
        cur = conn.execute(
            "SELECT lock_hash FROM wallets WHERE address = ? AND lock_hash IS NOT NULL",
            (address,),
        )
        row = cur.fetchone()
        if row:
            real_lock_hash = row[0]

    identifiers, seen = [], set()
    for candidate in (real_lock_hash, address):
        if candidate and candidate not in seen:
            seen.add(candidate)
            identifiers.append(candidate)
    return real_lock_hash, identifiers


def detect_edges_timestamp_scale(conn: sqlite3.Connection) -> dict:
    info = {"multiplier": 1.0, "edges_total_rows": 0,
            "edges_min_ts": None, "edges_max_ts": None, "unit_detected": "unknown"}
    try:
        info["edges_total_rows"] = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        row = conn.execute(
            "SELECT MIN(block_timestamp), MAX(block_timestamp) FROM edges "
            "WHERE block_timestamp IS NOT NULL"
        ).fetchone()
    except sqlite3.OperationalError:
        log.warning("edges table not found or unreadable -- cannot detect timestamp scale.")
        return info
    if not row or row[0] is None:
        return info

    info["edges_min_ts"], info["edges_max_ts"] = row[0], row[1]
    if row[1] > 1e11:
        info["unit_detected"] = "milliseconds"
        info["multiplier"] = 1000.0
        log.warning(
            "edges.block_timestamp looks like MILLISECONDS (max=%s) but "
            "provenance window_start_epoch/window_end_epoch are in SECONDS -- "
            "this alone would make the window filter in compute_edge_features() "
            "match zero rows for every wallet, in both directions, regardless of "
            "real activity. Scaling the window bounds by 1000 before filtering "
            "to correct for this.", row[1],
        )
    else:
        info["unit_detected"] = "seconds"
    return info


def herfindahl_index(values: np.ndarray) -> float:
    total = values.sum()
    if total <= 0:
        return np.nan
    shares = values / total
    return float((shares ** 2).sum())


def compute_edge_features(conn: sqlite3.Connection, address: str, identifiers: list[str],
                           window_start: Optional[int] = None, window_end: Optional[int] = None,
                           timestamp_multiplier: float = 1.0,
                           own_tx_hashes: Optional[set] = None) -> dict:
    feat = {
        "has_lock_hash": bool(identifiers),
        "sent_tx_count": np.nan, "received_tx_count": np.nan,
        "sent_edge_count": np.nan, "received_edge_count": np.nan,
        "sent_total_ckb": np.nan, "received_total_ckb": np.nan,
        "net_flow_ckb": np.nan,
        "sent_mean_ckb": np.nan, "sent_median_ckb": np.nan, "sent_cv": np.nan,
        "received_mean_ckb": np.nan, "received_median_ckb": np.nan, "received_cv": np.nan,
        "unique_counterparties_out": np.nan, "unique_counterparties_in": np.nan,
        "reciprocity_ratio": np.nan,
        "out_value_concentration_hhi": np.nan, "in_value_concentration_hhi": np.nan,
        "max_single_tx_ckb": np.nan,
    }
    if not identifiers:
        return feat

    placeholders = ",".join("?" * len(identifiers))
    window_clause = ""
    window_params: list = []
    if window_start is not None and window_end is not None:
        window_clause = " AND block_timestamp BETWEEN ? AND ?"
        window_params = [window_start * timestamp_multiplier, window_end * timestamp_multiplier]

    out_rows = conn.execute(
        f"SELECT to_lock_hash, value_shannon, tx_hash FROM edges "
        f"WHERE from_lock_hash IN ({placeholders}){window_clause}",
        identifiers + window_params,
    ).fetchall()
    in_rows = conn.execute(
        f"SELECT from_lock_hash, value_shannon, tx_hash FROM edges "
        f"WHERE to_lock_hash IN ({placeholders}){window_clause}",
        identifiers + window_params,
    ).fetchall()

    if own_tx_hashes:
        out_rows = [r for r in out_rows if r[2] in own_tx_hashes]
        in_rows = [r for r in in_rows if r[2] in own_tx_hashes]

    out_vals = np.array([v for _, v, _ in out_rows if v is not None], dtype=float) / SHANNON_PER_CKB
    in_vals = np.array([v for _, v, _ in in_rows if v is not None], dtype=float) / SHANNON_PER_CKB
    out_parties = Counter(h for h, _, _ in out_rows if h)
    in_parties = Counter(h for h, _, _ in in_rows if h)

    feat["sent_tx_count"] = len({t for _, _, t in out_rows if t})
    feat["received_tx_count"] = len({t for _, _, t in in_rows if t})
    feat["sent_edge_count"] = len(out_rows)
    feat["received_edge_count"] = len(in_rows)
    feat["sent_total_ckb"] = float(out_vals.sum()) if len(out_vals) else 0.0
    feat["received_total_ckb"] = float(in_vals.sum()) if len(in_vals) else 0.0
    feat["net_flow_ckb"] = feat["received_total_ckb"] - feat["sent_total_ckb"]

    if len(out_vals):
        feat["sent_mean_ckb"] = float(out_vals.mean())
        feat["sent_median_ckb"] = float(np.median(out_vals))
        feat["sent_cv"] = float(out_vals.std(ddof=0) / out_vals.mean()) if out_vals.mean() > 0 else np.nan
    if len(in_vals):
        feat["received_mean_ckb"] = float(in_vals.mean())
        feat["received_median_ckb"] = float(np.median(in_vals))
        feat["received_cv"] = float(in_vals.std(ddof=0) / in_vals.mean()) if in_vals.mean() > 0 else np.nan

    feat["unique_counterparties_out"] = len(out_parties)
    feat["unique_counterparties_in"] = len(in_parties)

    all_out_set, all_in_set = set(out_parties), set(in_parties)
    union = all_out_set | all_in_set
    if union:
        feat["reciprocity_ratio"] = len(all_out_set & all_in_set) / len(union)

    if len(out_parties):
        out_by_party = np.array(list(
            pd.Series([v for _, v, _ in out_rows if v is not None],
                      index=[h for h, v, _ in out_rows if v is not None])
            .groupby(level=0).sum()
        ), dtype=float)
        feat["out_value_concentration_hhi"] = herfindahl_index(out_by_party)
    if len(in_parties):
        in_by_party = np.array(list(
            pd.Series([v for _, v, _ in in_rows if v is not None],
                      index=[h for h, v, _ in in_rows if v is not None])
            .groupby(level=0).sum()
        ), dtype=float)
        feat["in_value_concentration_hhi"] = herfindahl_index(in_by_party)

    both = np.concatenate([out_vals, in_vals]) if (len(out_vals) or len(in_vals)) else np.array([])
    if len(both):
        feat["max_single_tx_ckb"] = float(both.max())

    return feat



def compute_dao_features(conn: sqlite3.Connection, address: str) -> dict:
    rows = conn.execute(
        "SELECT event_type, capacity FROM dao_events WHERE address = ?",
        (address,),
    ).fetchall()
    n = len(rows)
    caps = np.array([c for _, c in rows if c is not None], dtype=float) / SHANNON_PER_CKB
    types = Counter(t for t, _ in rows if t)
    return {
        "n_dao_events": n,
        "dao_total_ckb": float(caps.sum()) if len(caps) else 0.0,
        "dao_n_distinct_event_types": len(types),
        "has_dao_activity": n > 0,
    }



def assemble_features(addresses: list[str], db_path: Path, data_dir: Path) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA query_only = TRUE;")

    prov_df = build_provenance_frame(addresses, data_dir)

    ts_scale = detect_edges_timestamp_scale(conn)
    if ts_scale["edges_total_rows"] == 0:
        log.warning(
            "edges table has 0 rows (or 0 rows with a non-null block_timestamp) -- "
            "this is an upstream collection/rebuild problem, not something this "
            "script's window filter can fix. Check resolve_transaction_to_edges() "
            "and rebuild_edges_from_cache.py output before rerunning."
        )
    global _EDGES_TS_SCALE_INFO
    _EDGES_TS_SCALE_INFO = ts_scale

    timing_rows, edge_rows, dao_rows = [], [], []
    for addr in addresses:
        timing_feat, own_tx_hashes = compute_timing_features(conn, addr)
        timing_rows.append({"address": addr, **timing_feat})
        _, identifiers = resolve_wallet_identifiers(conn, addr)
        window_start = window_end = None
        if addr in prov_df.index:
            ws = prov_df.at[addr, "window_start_epoch"] if "window_start_epoch" in prov_df.columns else None
            we = prov_df.at[addr, "window_end_epoch"] if "window_end_epoch" in prov_df.columns else None
            window_start = int(ws) if pd.notna(ws) else None
            window_end = int(we) if pd.notna(we) else None
        edge_rows.append({"address": addr,
                           **compute_edge_features(conn, addr, identifiers, window_start, window_end,
                                                    timestamp_multiplier=ts_scale["multiplier"],
                                                    own_tx_hashes=own_tx_hashes)})
        dao_rows.append({"address": addr, **compute_dao_features(conn, addr)})
    conn.close()

    timing_df = pd.DataFrame(timing_rows).set_index("address")
    edge_df = pd.DataFrame(edge_rows).set_index("address")
    dao_df = pd.DataFrame(dao_rows).set_index("address")

    df = prov_df.join(timing_df).join(edge_df).join(dao_df)

    
    df["tx_per_window_day"] = df["n_tx_in_window"] / df["window_days"].replace(0, np.nan)

 
    df["dao_event_rate"] = df["n_dao_events"] / df["n_tx_in_window"].replace(0, np.nan)

    return df


def apply_status_labels(df: pd.DataFrame, active_set: set, unused_set: set) -> pd.DataFrame:
    df = df.copy()
    df["wallet_status"] = np.where(
        df.index.isin(active_set), "active",
        np.where(df.index.isin(unused_set), "unused", "unknown"),
    )
    df["is_active"] = df["wallet_status"] == "active"
    return df


BEHAVIORAL_COLS = [
    "n_tx_in_window", "tx_per_window_day", "active_span_days", "tx_per_active_day",
    "gap_mean_s", "gap_median_s", "gap_cv", "burstiness",
    "hour_of_day_entropy", "day_of_week_entropy",
    "sent_tx_count", "received_tx_count", "sent_edge_count", "received_edge_count",
    "sent_total_ckb", "received_total_ckb", "net_flow_ckb",
    "sent_mean_ckb", "sent_median_ckb", "sent_cv",
    "received_mean_ckb", "received_median_ckb", "received_cv",
    "unique_counterparties_out", "unique_counterparties_in", "reciprocity_ratio",
    "out_value_concentration_hhi", "in_value_concentration_hhi", "max_single_tx_ckb",
    "n_dao_events", "dao_total_ckb", "dao_event_rate", "has_dao_activity",
    "detail_coverage",
]

LOG_TRANSFORM_COLS = [
    "n_tx_in_window", "tx_per_window_day", "tx_per_active_day",
    "gap_mean_s", "gap_median_s",
    "sent_tx_count", "received_tx_count", "sent_edge_count", "received_edge_count",
    "sent_total_ckb", "received_total_ckb",
    "sent_mean_ckb", "sent_median_ckb", "received_mean_ckb", "received_median_ckb",
    "unique_counterparties_out", "unique_counterparties_in",
    "max_single_tx_ckb", "n_dao_events", "dao_total_ckb",
]


def build_clustering_matrix(df: pd.DataFrame, min_detail_coverage: float) -> tuple[pd.DataFrame, dict]:
    """Returns (raw_feature_df_for_active_wallets, audit_dict, imputed_flags)."""
    active = df[df["is_active"]].copy()
    audit = {"n_active": len(active)}
    audit["edges_timestamp_scale"] = dict(_EDGES_TS_SCALE_INFO)

    def signed_log1p(x):
        return np.sign(x) * np.log1p(np.abs(x))

    X = active[BEHAVIORAL_COLS].copy()
    X["has_dao_activity"] = X["has_dao_activity"].astype(float)

    low_coverage = X["detail_coverage"] < min_detail_coverage
    audit["n_low_detail_coverage"] = int(low_coverage.sum())
    audit["pct_low_detail_coverage"] = float(low_coverage.mean()) if len(low_coverage) else 0.0
    audit["low_detail_coverage_threshold"] = min_detail_coverage

    n = len(active)
    audit["pct_no_lock_hash"] = float((~active["has_lock_hash"].fillna(False)).mean()) if n else 0.0
    audit["pct_zero_sent_count"] = float((active["sent_tx_count"].fillna(0) <= 0).mean()) if n else 0.0
    audit["pct_zero_received_count"] = float((active["received_tx_count"].fillna(0) <= 0).mean()) if n else 0.0

    
    if "n_timing_events" in active.columns:
        stale = active["n_timing_events"].fillna(0) != active["n_tx_in_window"].fillna(0)
        audit["n_provenance_stale"] = int(stale.sum())
        audit["pct_provenance_stale"] = float(stale.mean()) if n else 0.0
        if stale.sum():
            log.warning(
                "%d wallet(s) (%.0f%%) have n_timing_events (live, deduped "
                "address_tx_seen count) != n_tx_in_window (static provenance "
                "count) -- provenance is stale relative to the current "
                "database for these wallets. tx_per_active_day and window-based "
                "coverage math use n_tx_in_window, so treat those figures with "
                "caution for the affected wallets until provenance is "
                "regenerated: %s",
                stale.sum(), 100 * stale.mean(), list(active.index[stale][:5]),
            )


    bound_col = active["n_timing_events"] if "n_timing_events" in active.columns else active["n_tx_in_window"]
    tx_count_col = bound_col.fillna(0)
    for count_col in ("sent_tx_count", "received_tx_count"):
        violations = active[count_col].fillna(0) > tx_count_col
        n_violations = int(violations.sum())
        if n_violations:
            log.warning(
                "%d wallet(s) have %s > n_timing_events (this wallet's own live, "
                "deduped transaction count) -- this should now be impossible by "
                "construction (edges are scoped to this wallet's own tx_hash set), "
                "so if it still fires it's a NEW root cause, not the millisecond-"
                "timestamp or cross-wallet-leakage bugs already fixed here. Likely "
                "cause: resolve_wallet_identifiers() returning an identifier "
                "(lock_hash or address string) that's shared by more than one "
                "real-world address in raw_addresses. Inspect features_full.csv "
                "for these wallets, and check for duplicate lock_hash values in "
                "raw_addresses across different addresses: %s",
                n_violations, count_col, list(active.index[violations][:5]),
            )
    audit["sent_tx_count_exceeds_window"] = int((active["sent_tx_count"].fillna(0) > tx_count_col).sum())
    audit["received_tx_count_exceeds_window"] = int((active["received_tx_count"].fillna(0) > tx_count_col).sum())

    EDGE_SAMPLED_COLS = [
        "sent_tx_count", "received_tx_count", "sent_edge_count", "received_edge_count",
        "sent_total_ckb", "received_total_ckb", "net_flow_ckb",
        "sent_mean_ckb", "sent_median_ckb", "sent_cv",
        "received_mean_ckb", "received_median_ckb", "received_cv",
        "unique_counterparties_out", "unique_counterparties_in", "reciprocity_ratio",
        "out_value_concentration_hhi", "in_value_concentration_hhi", "max_single_tx_ckb",
    ]
    X.loc[low_coverage, EDGE_SAMPLED_COLS] = np.nan

    for col in LOG_TRANSFORM_COLS:
        if col == "net_flow_ckb":
            continue
        X[col] = np.log1p(X[col].clip(lower=0))
    if "net_flow_ckb" in X.columns:
        X["net_flow_ckb"] = signed_log1p(X["net_flow_ckb"])

    missing_before = X.isna().sum()
    audit["missing_counts_before_impute"] = {k: int(v) for k, v in missing_before.items() if v > 0}

    imputed_flags = pd.DataFrame(False, index=X.index, columns=X.columns)
    all_nan_cols = []
    for col in X.columns:
        if X[col].isna().any():
            imputed_flags[col] = X[col].isna()
            med = X[col].median()
            if pd.isna(med):
                all_nan_cols.append(col)
                X[col] = 0.0
            else:
                X[col] = X[col].fillna(med)

    audit["columns_with_imputation"] = [c for c in X.columns if imputed_flags[c].any()]
    audit["columns_entirely_nan_filled_with_zero"] = all_nan_cols

    if all_nan_cols:
        causes = []
        if audit["pct_low_detail_coverage"] > 0.5:
            causes.append(
                f"{audit['pct_low_detail_coverage']:.0%} of active wallets fell below the "
                f"--min-detail-coverage threshold ({min_detail_coverage:.0%}) -- their edge-based "
                f"columns were nulled by design. Consider a higher --max-tx-details at collection "
                f"time, or a lower --min-detail-coverage here."
            )
        if audit["pct_no_lock_hash"] > 0.3:
            causes.append(
                f"{audit['pct_no_lock_hash']:.0%} of active wallets have no resolvable lock_hash "
                f"in raw_addresses -- their edges could never be attributed to them regardless of "
                f"coverage. Check whether collect_target_wallets.py's address-detail fetch is "
                f"succeeding for this address format, or re-run with --force to redo it."
            )
        zero_sent_and_high_coverage = (audit["pct_zero_sent_count"] > 0.9
                                        and audit["pct_low_detail_coverage"] < 0.1)
        zero_received_and_high_coverage = (audit["pct_zero_received_count"] > 0.9
                                            and audit["pct_low_detail_coverage"] < 0.1)
        if zero_sent_and_high_coverage or zero_received_and_high_coverage:
            ts_info = _EDGES_TS_SCALE_INFO
            if ts_info.get("edges_total_rows") == 0:
                causes.append(
                    f"{audit['pct_zero_sent_count']:.0%} of active wallets show zero SENT and "
                    f"{audit['pct_zero_received_count']:.0%} zero RECEIVED edges, despite high "
                    f"detail coverage -- CONFIRMED CAUSE: the `edges` table itself has 0 rows (or "
                    f"0 rows with a non-null block_timestamp) in this run's sqlite db. This is an "
                    f"upstream collection/rebuild problem (resolve_transaction_to_edges() or "
                    f"rebuild_edges_from_cache.py produced nothing), not a property of these "
                    f"wallets' real behavior -- do not read it as 'this address set only receives.'"
                )
            elif ts_info.get("unit_detected") == "milliseconds":
                causes.append(
                    f"{audit['pct_zero_sent_count']:.0%} of active wallets show zero SENT and "
                    f"{audit['pct_zero_received_count']:.0%} zero RECEIVED edges, despite high "
                    f"detail coverage -- CONFIRMED CAUSE (now fixed in this run): "
                    f"edges.block_timestamp was stored in milliseconds "
                    f"(max={ts_info.get('edges_max_ts')}) while the provenance window bounds are "
                    f"in seconds. detect_edges_timestamp_scale() detected this and rescaled the "
                    f"window filter automatically, so the edge features in this output should now "
                    f"be populated. If they are still all-zero, the mismatch may be more complex "
                    f"than a flat x1000 (e.g. a mixed-unit edges table) -- inspect "
                    f"`SELECT block_timestamp FROM edges LIMIT 20` directly."
                )
            else:
                causes.append(
                    f"{audit['pct_zero_sent_count']:.0%} of active wallets show zero SENT edges and "
                    f"{audit['pct_zero_received_count']:.0%} zero RECEIVED edges even though detail "
                    f"coverage is high, and edges.block_timestamp units matched the provenance "
                    f"window (both seconds) -- so this is not the timestamp-unit bug this script "
                    f"checks for. It now looks like a genuine data characteristic of this address "
                    f"set, OR a from_lock_hash/to_lock_hash identifier mismatch (e.g. edges keyed "
                    f"by a script hash shape resolve_wallet_identifiers() isn't trying). Run "
                    f"`SELECT DISTINCT from_lock_hash FROM edges LIMIT 5` and compare the shape "
                    f"against a known wallet's lock_hash in raw_addresses to check for a format "
                    f"mismatch before concluding it's genuine."
                )
        if not causes:
            causes.append(
                "no single dominant cause stood out in the coverage/lock_hash/zero-count checks "
                "above -- inspect features_full.csv for these columns directly."
            )

        log.warning(
            "%d column(s) had NO usable value across ANY active wallet, so they were filled "
            "with 0 instead of a median: %s.\n  Likely cause(s):\n  - %s",
            len(all_nan_cols), all_nan_cols, "\n  - ".join(causes),
        )
        audit["all_nan_diagnosis"] = causes

    # Final safety net: whatever the cause, never hand PCA/scaling a NaN.
    remaining = int(X.isna().sum().sum())
    if remaining:
        log.warning("%d stray NaN value(s) remained after imputation -- "
                     "filling with 0 as a last resort.", remaining)
        X = X.fillna(0.0)

    return X, audit, imputed_flags



def scale_and_reduce(X: pd.DataFrame, n_pca: int = 2):
    from sklearn.preprocessing import RobustScaler
    from sklearn.decomposition import PCA

    scaler = RobustScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X), index=X.index, columns=X.columns)

    n_comp = min(n_pca, X_scaled.shape[1], max(X_scaled.shape[0] - 1, 1))
    pca = PCA(n_components=n_comp, random_state=0)
    pcs = pca.fit_transform(X_scaled.values)
    pcs_df = pd.DataFrame(pcs, index=X.index, columns=[f"PC{i+1}" for i in range(n_comp)])

    return X_scaled, scaler, pcs_df, pca


def kmeans_k_sweep(X_scaled: pd.DataFrame, k_min: int, k_max: int):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(X_scaled)
    k_max = min(k_max, n - 1) if n > 2 else 2
    results = []
    for k in range(k_min, max(k_max, k_min) + 1):
        if k < 2 or k >= n:
            continue
        km = KMeans(n_clusters=k, n_init=10, random_state=0)
        labels = km.fit_predict(X_scaled.values)
        inertia = km.inertia_
        try:
            sil = silhouette_score(X_scaled.values, labels)
        except ValueError:
            sil = np.nan
        results.append({"k": k, "inertia": inertia, "silhouette": sil})
    return pd.DataFrame(results)



def make_plots(df: pd.DataFrame, X: pd.DataFrame, X_scaled: pd.DataFrame,
                pcs_df: pd.DataFrame, k_sweep: pd.DataFrame, out_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots_dir = out_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(5, 4))
    df["wallet_status"].value_counts().plot(kind="bar", ax=ax, color="#4C72B0")
    ax.set_title("Wallet status breakdown")
    ax.set_ylabel("count")
    fig.tight_layout()
    fig.savefig(plots_dir / "01_wallet_status_breakdown.png", dpi=140)
    plt.close(fig)

    active = df[df["is_active"]]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(active["detail_coverage"].dropna(), bins=30, color="#DD8452")
    ax.set_title("Detail-fetch coverage per active wallet\n(fraction of in-window tx with full detail)")
    ax.set_xlabel("n_tx_detail_fetched / n_tx_in_window")
    ax.set_ylabel("wallets")
    fig.tight_layout()
    fig.savefig(plots_dir / "02_detail_coverage_distribution.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 5))
    sc = ax.scatter(active["n_tx_in_window"], active["detail_coverage"],
                     c=active["n_tx_in_window"], cmap="viridis", s=18, alpha=0.7)
    ax.set_xscale("log")
    ax.set_xlabel("n_tx_in_window (log scale)")
    ax.set_ylabel("detail_coverage")
    ax.set_title("High-activity wallets get the least detail coverage\n(sampling cap is fixed, activity isn't)")
    fig.tight_layout()
    fig.savefig(plots_dir / "03_coverage_vs_activity.png", dpi=140)
    plt.close(fig)

    show_cols = [c for c in ["n_tx_in_window", "sent_total_ckb", "received_total_ckb",
                              "unique_counterparties_out"] if c in active.columns]
    if show_cols:
        fig, axes = plt.subplots(len(show_cols), 2, figsize=(9, 3 * len(show_cols)))
        if len(show_cols) == 1:
            axes = axes.reshape(1, 2)
        for i, col in enumerate(show_cols):
            raw = active[col].dropna()
            axes[i, 0].hist(raw, bins=30, color="#4C72B0")
            axes[i, 0].set_title(f"{col} (raw)")
            axes[i, 1].hist(np.log1p(raw.clip(lower=0)), bins=30, color="#55A868")
            axes[i, 1].set_title(f"{col} (log1p)")
        fig.tight_layout()
        fig.savefig(plots_dir / "04_raw_vs_log_distributions.png", dpi=140)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 9))
    corr = X.corr()
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(corr.columns)))
    ax.set_yticklabels(corr.columns, fontsize=7)
    ax.set_title("Feature correlation (post log-transform, active wallets)")
    fig.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    fig.savefig(plots_dir / "05_feature_correlation_heatmap.png", dpi=140)
    plt.close(fig)

    if pcs_df.shape[1] >= 2:
        fig, ax = plt.subplots(figsize=(6.5, 5.5))
        sc = ax.scatter(pcs_df["PC1"], pcs_df["PC2"],
                         c=np.log1p(active["n_tx_in_window"]), cmap="plasma", s=18, alpha=0.8)
        ax.set_xlabel("PC1")
        ax.set_ylabel("PC2")
        ax.set_title("PCA projection of scaled features\n(color = log tx count)")
        fig.colorbar(sc, ax=ax, label="log1p(n_tx_in_window)")
        fig.tight_layout()
        fig.savefig(plots_dir / "06_pca_projection.png", dpi=140)
        plt.close(fig)

    if not k_sweep.empty:
        fig, ax1 = plt.subplots(figsize=(7, 4.5))
        ax1.plot(k_sweep["k"], k_sweep["inertia"], "o-", color="#4C72B0", label="inertia")
        ax1.set_xlabel("k")
        ax1.set_ylabel("inertia (elbow)", color="#4C72B0")
        ax2 = ax1.twinx()
        ax2.plot(k_sweep["k"], k_sweep["silhouette"], "s--", color="#C44E52", label="silhouette")
        ax2.set_ylabel("silhouette score", color="#C44E52")
        ax1.set_title("KMeans k-selection sweep")
        fig.tight_layout()
        fig.savefig(plots_dir / "07_kmeans_k_selection.png", dpi=140)
        plt.close(fig)

    return plots_dir



def write_report(out_dir: Path, df: pd.DataFrame, audit: dict, k_sweep: pd.DataFrame,
                  min_detail_coverage: float):
    active = df[df["is_active"]]
    unused = df[df["wallet_status"] == "unused"]
    unknown = df[df["wallet_status"] == "unknown"]

    best_k_row = k_sweep.loc[k_sweep["silhouette"].idxmax()] if not k_sweep.empty and k_sweep["silhouette"].notna().any() else None

    lines = []
    lines.append("# CKB Wallet Preprocessing Report\n")
    lines.append("## 0. Input counts\n")
    lines.append(f"- Active wallets (clustering population): **{len(active)}**")
    lines.append(f"- Unused wallets (kept, labeled, excluded from clustering matrix): **{len(unused)}**")
    if len(unknown):
        lines.append(f"- Wallets in neither list (no status label; excluded): **{len(unknown)}** -- "
                      f"check these were classified/collected.")
    lines.append("- Malformed wallets: dropped upstream by classify_wallet_status.py, "
                  "not read by this script at all.\n")

    lines.append("## 1. Data-quality audit (read this before trusting monetary features)\n")
    lines.append(f"- {audit['n_low_detail_coverage']} of {audit['n_active']} active wallets "
                 f"({audit.get('pct_low_detail_coverage', 0):.0%}) fell below the detail-coverage "
                 f"threshold of {min_detail_coverage:.0%} (n_tx_detail_fetched / n_tx_in_window). "
                 f"For these wallets, edge-derived monetary/graph features (sent/received totals, "
                 f"counterparty counts, concentration indices) were set to NaN and then "
                 f"median-imputed -- **do not read cluster assignments for these wallets as "
                 f"monetary behavior conclusions**, only as timing/rhythm conclusions, which "
                 f"remain reliable regardless of coverage. DAO features are exact regardless of "
                 f"coverage (separate, uncapped collection) and were not affected by this.")
    if audit.get("columns_with_imputation"):
        lines.append(f"- Columns that required imputation for at least one wallet: "
                     f"{', '.join(audit['columns_with_imputation'])}.")
    if audit.get("columns_entirely_nan_filled_with_zero"):
        lines.append(
            f"- ** {len(audit['columns_entirely_nan_filled_with_zero'])} column(s) had NO usable "
            f"value across ANY active wallet and were filled with 0, not a median**: "
            f"{', '.join(audit['columns_entirely_nan_filled_with_zero'])}. "
            f"**These columns currently carry zero clustering signal.** Likely cause(s), based on "
            f"what this run's data actually shows (not assumed):")
        for cause in audit.get("all_nan_diagnosis", []):
            lines.append(f"  - {cause}")
        lines.append(
            f"  - Diagnostic numbers for this run: {audit.get('pct_low_detail_coverage', 0):.0%} "
            f"of active wallets below the {min_detail_coverage:.0%} coverage threshold, "
            f"{audit.get('pct_no_lock_hash', 0):.0%} with no resolvable lock_hash, "
            f"{audit.get('pct_zero_sent_count', 0):.0%} with zero sent edges, "
            f"{audit.get('pct_zero_received_count', 0):.0%} with zero received edges."
        )
    for col, n in audit.get("missing_counts_before_impute", {}).items():
        lines.append(f"  - `{col}`: {n} wallet(s) missing before imputation")
    lines.append("")

    lines.append("## 2. Feature engineering summary\n")
    lines.append("**Timing features** (from `address_tx_seen`, exact unless `listing_truncated`):")
    lines.append("- `n_tx_in_window`, `tx_per_window_day`, `active_span_days`, `tx_per_active_day`")
    lines.append("- `gap_mean_s`, `gap_median_s`, `gap_cv` (inter-transaction gap statistics)")
    lines.append("- `burstiness` (Goh–Barabási index: -1 periodic/bot-like, 0 memoryless, +1 human-bursty)")
    lines.append("- `hour_of_day_entropy`, `day_of_week_entropy` (0 = concentrated/scripted, 1 = uniform)\n")
    lines.append("**Monetary / graph features** (from `edges`, sample-limited -- see audit above):")
    lines.append("- `sent_tx_count`/`received_tx_count` (distinct transactions -- commensurate with "
                 "`n_tx_in_window`), `sent_edge_count`/`received_edge_count` (raw edge rows -- can "
                 "exceed the transaction count for wallets with many distinct counterparties per "
                 "transaction; see the note below), `sent_total_ckb`, `received_total_ckb`, `net_flow_ckb`")
    lines.append("- `sent_mean_ckb`/`median`/`cv`, `received_mean_ckb`/`median`/`cv`")
    lines.append("- `unique_counterparties_out`/`in`, `reciprocity_ratio`")
    lines.append("- `out_value_concentration_hhi`/`in_value_concentration_hhi` (Herfindahl index -- "
                 "1 wallet dominating flow vs. many small counterparties)")
    lines.append("- `max_single_tx_ckb`\n")
    lines.append("**DAO features** (from `dao_events`, exact):")
    lines.append("- `n_dao_events`, `dao_total_ckb`, `dao_event_rate`, `has_dao_activity`\n")
    lines.append("**Known heuristic bias**: `edges.value_shannon` splits a transaction's output "
                 "value proportionally across every distinct input lock_hash, without knowing "
                 "each input's real contribution. Multi-input transactions therefore inflate "
                 "summed sent/received volume, and the inflation scales with each wallet's "
                 "average input-fan-in, which isn't itself measured here. Value features should "
                 "be read as **relative, within-dataset signals**, not audited CKB amounts.\n")
    lines.append("**Edge count vs. transaction count**: `resolve_transaction_to_edges` produces "
                 "one edge per (transaction, distinct counterparty) pair, not one per transaction. "
                 "A single transaction paying out to many distinct addresses -- or receiving from "
                 "many distinct senders in one consolidation transaction -- can generate far more "
                 "edges than the wallet had actual transactions (this is exactly what a wallet with "
                 "38,029 edges against 5,553 real transactions looked like: a consolidation-style "
                 "address). `sent_tx_count`/`received_tx_count` are the distinct-transaction counts "
                 "and are bounded by `n_tx_in_window` by construction; "
                 "`sent_edge_count`/`received_edge_count` are the raw edge counts and are NOT "
                 "bounded by it -- use the `_tx_count` columns for anything meant to represent "
                 "\"how many transactions,\" and the `_edge_count` columns only for fan-out/graph "
                 "analysis where the distinction matters.")
    if audit.get("n_provenance_stale"):
        lines.append(
            f"\n Provenance staleness: {audit.get('n_provenance_stale', 0)} wallet(s) "
            f"({audit.get('pct_provenance_stale', 0):.0%}) have a live, deduped "
            f"address_tx_seen transaction count (`n_timing_events`) that differs from the "
            f"static `n_tx_in_window` recorded in their provenance JSON -- provenance is out "
            f"of sync with the current database for these wallets. `tx_per_active_day` and "
            f"detail_coverage math key off `n_tx_in_window`, so treat those figures with "
            f"caution for the affected wallets until provenance is regenerated.")
    if audit.get("sent_tx_count_exceeds_window") or audit.get("received_tx_count_exceeds_window"):
        lines.append(
            f"\n Sanity-check violation: {audit.get('sent_tx_count_exceeds_window', 0)} wallet(s) "
            f"have `sent_tx_count` exceeding their own live transaction count and "
            f"{audit.get('received_tx_count_exceeds_window', 0)} have `received_tx_count` doing "
            f"the same. This is checked against each wallet's own deduped `n_timing_events`, not "
            f"the potentially-stale `n_tx_in_window`, and should now be impossible by construction "
            f"since edges are scoped to each wallet's own recorded tx_hashes -- if it still fires, "
            f"it's a distinct, not-yet-diagnosed root cause (see the console warning for a specific "
            f"hypothesis and which addresses are affected) -- treat their transaction-count "
            f"features with caution until investigated.")
    lines.append("")

    lines.append("## 3. Transforms applied\n")
    lines.append(f"- Log1p on heavy-tailed counts/amounts: {', '.join(LOG_TRANSFORM_COLS)}")
    lines.append("- Signed-log1p on `net_flow_ckb` (can be negative)")
    lines.append("- RobustScaler (median/IQR) on the full active feature matrix -- chosen over "
                 "StandardScaler because whale wallets remain outliers even after log-transform "
                 "and would otherwise dominate a mean/std scaling.\n")

    lines.append("## 4. Suggested k for KMeans (from elbow + silhouette sweep)\n")
    if best_k_row is not None:
        lines.append(f"- Silhouette-best k = **{int(best_k_row['k'])}** "
                     f"(silhouette = {best_k_row['silhouette']:.3f}). Cross-check against the "
                     f"elbow in `plots/07_kmeans_k_selection.png` -- silhouette alone can favor "
                     f"a trivially small k.")
    else:
        lines.append("- Not enough active wallets to run a meaningful k-sweep.")
    lines.append("- KMeans assumes spherical, similarly-sized clusters. Given how skewed wallet "
                 "activity typically is (a few whales/bots, many quiet-but-active wallets), also "
                 "try **GMM** (soft cluster boundaries) or **HDBSCAN** (no k required, and "
                 "explicitly labels wallets that don't fit any cluster as noise instead of "
                 "forcing them into the nearest one -- often the more honest choice here).\n")

    lines.append("## 5. Output files\n")
    lines.append("- `features_full.csv` -- every wallet (active + unused + unknown), all raw "
                 "features + status/QC columns, nothing scaled or imputed. Use this for reporting "
                 "and for keeping the unused group as a labeled third class.")
    lines.append("- `features_for_clustering.csv` -- active wallets only, log-transformed, "
                 "low-coverage value features nulled + median-imputed, RobustScaler-scaled. "
                 "Feed this directly into KMeans/GMM/HDBSCAN.")
    lines.append("- `feature_manifest.json` -- column lists, transform choices, imputation audit, "
                 "scaler parameters (so the exact same transform can be re-applied to newly "
                 "collected wallets later without refitting from scratch).")
    lines.append("- `plots/` -- 01 status breakdown, 02 detail-coverage distribution, "
                 "03 coverage-vs-activity (shows the sampling bias directly), "
                 "04 raw-vs-log distributions, 05 correlation heatmap, 06 PCA projection, "
                 "07 KMeans k-selection sweep.\n")

    (out_dir / "PREPROCESSING_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--data-dir", type=Path, required=True,
                   help="ckb_data_v2-style directory containing ckb_explorer.sqlite and provenance/")
    p.add_argument("--active-list", type=Path, required=True,
                   help="wallets_active.txt from classify_wallet_status.py")
    p.add_argument("--unused-list", type=Path, default=None,
                   help="wallets_unused.txt from classify_wallet_status.py (optional, but keep it "
                        "-- unused wallets are valid data, not noise)")
    p.add_argument("--out-dir", type=Path, default=Path("./ckb_features"))
    p.add_argument("--min-detail-coverage", type=float, default=0.3,
                   help="Below this fraction of tx-with-detail/tx-in-window, monetary/graph "
                        "features for that wallet are treated as unreliable (nulled + imputed) "
                        "rather than trusted. Default: 0.3")
    p.add_argument("--k-min", type=int, default=2)
    p.add_argument("--k-max", type=int, default=10)
    p.add_argument("--pca-components", type=int, default=2)
    args = p.parse_args()

    db_path = args.data_dir / "ckb_explorer.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")

    active_list = load_address_list(args.active_list)
    unused_list = load_address_list(args.unused_list)
    if not active_list:
        raise SystemExit("no addresses in --active-list -- nothing to do")

    all_addrs = list(dict.fromkeys(active_list + unused_list))
    log.info("assembling features for %d wallets (%d active, %d unused)",
             len(all_addrs), len(active_list), len(unused_list))

    df = assemble_features(all_addrs, db_path, args.data_dir)
    df = apply_status_labels(df, set(active_list), set(unused_list))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out_dir / "features_full.csv", encoding="utf-8")
    log.info("wrote %s (%d rows)", args.out_dir / "features_full.csv", len(df))

    X, audit, imputed_flags = build_clustering_matrix(df, args.min_detail_coverage)
    X_scaled, scaler, pcs_df, pca = scale_and_reduce(X, n_pca=args.pca_components)
    X_scaled.to_csv(args.out_dir / "features_for_clustering.csv", encoding="utf-8")
    log.info("wrote %s (%d rows, %d features)",
             args.out_dir / "features_for_clustering.csv", X_scaled.shape[0], X_scaled.shape[1])

    k_sweep = kmeans_k_sweep(X_scaled, args.k_min, args.k_max)
    if not k_sweep.empty:
        k_sweep.to_csv(args.out_dir / "kmeans_k_sweep.csv", index=False, encoding="utf-8")

    manifest = {
        "n_wallets_total": len(df),
        "n_active": int((df["wallet_status"] == "active").sum()),
        "n_unused": int((df["wallet_status"] == "unused").sum()),
        "n_unknown": int((df["wallet_status"] == "unknown").sum()),
        "behavioral_columns": BEHAVIORAL_COLS,
        "log_transformed_columns": LOG_TRANSFORM_COLS,
        "min_detail_coverage_threshold": args.min_detail_coverage,
        "audit": {k: v for k, v in audit.items() if k != "missing_counts_before_impute"} | {
            "missing_counts_before_impute": audit.get("missing_counts_before_impute", {})
        },
        "scaler": {
            "type": "RobustScaler",
            "center_": scaler.center_.tolist(),
            "scale_": scaler.scale_.tolist(),
            "columns": list(X.columns),
        },
        "pca_explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
    }
    (args.out_dir / "feature_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    make_plots(df, X, X_scaled, pcs_df, k_sweep, args.out_dir)
    write_report(args.out_dir, df, audit, k_sweep, args.min_detail_coverage)

    log.info("done. See %s for the full written report.", args.out_dir / "PREPROCESSING_REPORT.md")


if __name__ == "__main__":
    main()