"""Build the label-safe manifest for the existing local CKB wallet population."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


MANIFEST_VERSION = "ckb-wallet-research-manifest-v1"
STRATA = (
    (1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"),
    (201, 500, "201-500"), (501, 1000, "501-1000"),
    (1001, 5000, "1001-5000"), (5001, None, "5000+"),
)


def sampling_stratum(value) -> str:
    if value is None:
        return "unknown"
    try:
        count = int(value)
    except (TypeError, ValueError):
        return "unknown"
    for low, high, label in STRATA:
        if count >= low and (high is None or count <= high):
            return label
    return "unknown"


def _json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _addresses(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip().startswith("ckb1")]


def build_manifest(repo_root: Path, db_path: Path | None = None) -> tuple[list[dict], dict]:
    ckb_dir = repo_root / "ckb_data"
    records: dict[str, dict] = {}
    occurrences = Counter()
    lifetime_candidates: dict[str, list[tuple[int, str]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)
    raw_paths: dict[str, list[str]] = defaultdict(list)

    def add(address: str, dataset: str, run: str | None = None) -> dict | None:
        if not isinstance(address, str) or not address.startswith("ckb1"):
            return None
        address = address.strip()
        occurrences[address] += 1
        row = records.setdefault(address, {
            "manifest_version": MANIFEST_VERSION,
            "canonical_lock_hash": None,
            "address": address,
            "source_dataset": set(),
            "source_run": set(),
        })
        row["source_dataset"].add(dataset)
        if run:
            row["source_run"].add(run)
        return row

    for path in [ckb_dir / "addresses.txt", *sorted((ckb_dir / "ckb_data_v2").glob("wallets_*.txt"))]:
        for address in _addresses(path):
            add(address, str(path.relative_to(repo_root)), "legacy-ckb-data-v2")

    provenance_dir = ckb_dir / "ckb_data_v2" / "provenance"
    provenance: dict[str, dict] = {}
    for path in sorted(provenance_dir.glob("*.json")):
        item = _json(path, {})
        address = item.get("address")
        if add(address, "ckb_data/ckb_data_v2/provenance", item.get("collected_at_utc")):
            provenance[address] = item

    feature_path = ckb_dir / "ckb_features" / "features_full.csv"
    if feature_path.exists():
        with feature_path.open(newline="") as handle:
            for item in csv.DictReader(handle):
                add(item.get("address"), str(feature_path.relative_to(repo_root)),
                    "legacy-feature-export")

    real_dir = repo_root / "data" / "real"
    checkpoint = _json(real_dir / "checkpoint.json", {})
    for address in checkpoint.get("discovered", []):
        add(address, "data/real/checkpoint.json", "legacy-discovery-run")
    for address, item in checkpoint.get("classified", {}).items():
        add(address, "data/real/checkpoint.json", "legacy-classification-run")
        if isinstance(item, dict) and item.get("tx_count") is not None:
            lifetime_candidates[address].append((int(item["tx_count"]), "checkpoint"))
        label = item.get("bucket") if isinstance(item, dict) else item
        if label in {"human_like", "bot_like"}:
            labels[address].add(label)

    stats_path = real_dir / "lifetime_stats.jsonl"
    if stats_path.exists():
        for line in stats_path.read_text().splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            address = item.get("address")
            add(address, "data/real/lifetime_stats.jsonl", "legacy-lifetime-count-run")
            if item.get("tx_count") is not None and not item.get("error"):
                lifetime_candidates[address].append((int(item["tx_count"]), "lifetime_stats"))
            if item.get("original_label") in {"human_like", "bot_like"}:
                labels[address].add(item["original_label"])

    for bucket in ("human_like", "bot_like"):
        bucket_dir = real_dir / bucket
        for item in _json(bucket_dir / "manifest.json", []):
            address = item.get("address")
            add(address, f"data/real/{bucket}/manifest.json", "legacy-real-wallet-run")
            if item.get("tx_count") is not None:
                lifetime_candidates[address].append((int(item["tx_count"]), "real_manifest"))
            labels[address].add(bucket)
            raw = bucket_dir / f"addr_{item.get('index')}.json"
            if raw.exists() and raw.stat().st_size:
                raw_paths[address].append(str(raw.relative_to(repo_root)))

    normalized_addresses: set[str] = set()
    raw_db_addresses: set[str] = set()
    lock_hashes: dict[str, str] = {}
    if db_path and db_path.exists() and db_path.stat().st_size:
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "raw_addresses" in tables:
            for address, lock_hash in conn.execute("SELECT address,lock_hash FROM raw_addresses"):
                raw_db_addresses.add(address)
                if lock_hash:
                    lock_hashes[address] = lock_hash
        if "wallet_observations" in tables:
            normalized_addresses.update(row[0] for row in conn.execute(
                "SELECT DISTINCT address FROM wallet_observations WHERE address IS NOT NULL"))
        conn.close()

    output = []
    for address in sorted(records):
        row = records[address]
        candidates = lifetime_candidates.get(address, [])
        counts = {value for value, _ in candidates}
        lifetime = (next(value for value, source in candidates if source == "lifetime_stats")
                    if any(source == "lifetime_stats" for value, source in candidates)
                    else candidates[0][0] if candidates else None)
        legacy_labels = sorted(labels.get(address, set()))
        label = legacy_labels[0] if len(legacy_labels) == 1 else "UNKNOWN" if legacy_labels else None
        prov = provenance.get(address)
        has_raw = bool(raw_paths.get(address)) or address in raw_db_addresses
        has_normalized = address in normalized_addresses
        tier = "A" if has_raw and has_normalized else "B" if has_raw else "C"
        row.update({
            "canonical_lock_hash": lock_hashes.get(address),
            "source_dataset": sorted(row["source_dataset"]),
            "source_run": sorted(row["source_run"]),
            "legacy_proxy_label": label,
            "legacy_proxy_label_conflict": len(legacy_labels) > 1,
            "lifetime_tx_count": lifetime,
            "lifetime_count_status": ("NOT_ESTABLISHED" if lifetime is None else
                                      "CONFLICT" if len(counts) > 1 else "ESTABLISHED"),
            "sampling_stratum": sampling_stratum(lifetime),
            "existing_raw_data": has_raw,
            "existing_raw_paths": sorted(raw_paths.get(address, [])),
            "existing_normalized_data": has_normalized,
            "evidence_tier": tier,
            "observation_status": "LEGACY_WINDOW_ONLY" if prov else "NOT_ESTABLISHED",
            "provenance_status": "AVAILABLE" if prov else "NOT_ESTABLISHED",
            "source_occurrences": occurrences[address],
        })
        output.append(row)

    strata = Counter(item["sampling_stratum"] for item in output)
    tiers = Counter(item["evidence_tier"] for item in output)
    label_counts = Counter(item["legacy_proxy_label"] or "null" for item in output)
    summary = {
        "manifest_version": MANIFEST_VERSION,
        "unique_wallets": len(output),
        "source_occurrences": sum(occurrences.values()),
        "duplicate_occurrences": sum(value - 1 for value in occurrences.values()),
        "wallets_appearing_multiple_times": sum(value > 1 for value in occurrences.values()),
        "missing_lifetime_counts": strata["unknown"],
        "sampling_strata": {name: {"wallets": strata[name],
                                     "percentage": round(100 * strata[name] / len(output), 2) if output else 0,
                                     "provisionally_sufficient": (strata[name] >= 10
                                                                  if name != "unknown" else None)}
                             for name in [label for _, _, label in STRATA] + ["unknown"]},
        "evidence_tiers": dict(sorted(tiers.items())),
        "legacy_proxy_labels": dict(sorted(label_counts.items())),
        "raw_wallets": sum(item["existing_raw_data"] for item in output),
        "normalized_wallets": sum(item["existing_normalized_data"] for item in output),
        "provenance_wallets": sum(item["provenance_status"] == "AVAILABLE" for item in output),
    }
    return output, summary


def write_manifest(records: list[dict], summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "wallet_manifest_v1.jsonl").open("w") as handle:
        for item in records:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    (out_dir / "wallet_inventory_v1.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--db", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "research_validation")
    args = parser.parse_args()
    records, summary = build_manifest(args.repo_root, args.db)
    write_manifest(records, summary, args.out_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
