#!/usr/bin/env python3
"""Verify the frozen research dataset and every indexed derived artifact."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

EXPECTED_MANIFEST = "6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe"
EXPECTED_DATABASE = "e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322"
EXPECTED_WALLETS = 1172
EXPECTED_TRANSACTIONS = 51816


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def row_count(path: Path):
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return max(0, sum(1 for _ in csv.reader(handle)) - 1)
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    return None


def check_artifact_index(root: Path) -> None:
    index = json.loads((root / "artifacts/artifact-index.json").read_text(encoding="utf-8"))
    if not index:
        raise RuntimeError("artifact index is empty")
    for record in index:
        path = root / record["path"]
        if not path.is_file():
            raise RuntimeError(f"indexed artifact is missing: {record['path']}")
        actual_digest = digest(path)
        if actual_digest != record["sha256"]:
            raise RuntimeError(f"artifact hash mismatch: {record['path']}")
        expected_rows = record.get("row_count")
        actual_rows = row_count(path)
        if expected_rows is not None and actual_rows != expected_rows:
            raise RuntimeError(f"artifact row-count mismatch: {record['path']}")


def check_source_integrity(root: Path) -> None:
    phase_dir = root / "ckb_data/exploratory_ml_phase2_v1"
    contract = json.loads((phase_dir / "experiment_contract.json").read_text(encoding="utf-8"))
    recorded = json.loads((phase_dir / "source_integrity_after.json").read_text(encoding="utf-8"))
    if contract["source_integrity"] != recorded:
        raise RuntimeError("Phase 2 source-integrity records disagree")
    for relative_path, expected_digest in recorded["artifacts"].items():
        path = root / relative_path
        if digest(path) != expected_digest:
            raise RuntimeError(f"Phase 2 source artifact hash mismatch: {relative_path}")
    database = root / recorded["database"]["path"]
    if database.stat().st_size != recorded["database"]["bytes"]:
        raise RuntimeError("Phase 2 database size mismatch")
    if digest(database) != recorded["database"]["sha256"]:
        raise RuntimeError("Phase 2 database hash mismatch")


def main(root: Path) -> None:
    data = root / "ckb_data"
    contract = json.loads(
        (data / "feature_engineering_v2/dataset_v1_snapshot/dataset_contract_v1.json").read_text(
            encoding="utf-8"
        )
    )
    if contract["total_wallets"] != EXPECTED_WALLETS:
        raise RuntimeError("frozen wallet count changed")
    if contract["transaction_count"] != EXPECTED_TRANSACTIONS:
        raise RuntimeError("frozen transaction count changed")
    if contract["manifest_hash"] != EXPECTED_MANIFEST:
        raise RuntimeError("frozen manifest hash changed")

    database = root / "ckb_data/ckb_data_v2/ckb_explorer.sqlite"
    source = contract["source_database"]
    actual_size = database.stat().st_size
    if actual_size != source["bytes"]:
        raise RuntimeError(
            "frozen database mismatch: "
            f"expected {source['bytes']} bytes / {EXPECTED_DATABASE}, "
            f"got {actual_size} bytes / size differs"
        )
    actual_digest = digest(database)
    if actual_digest != EXPECTED_DATABASE:
        raise RuntimeError(
            "frozen database mismatch: "
            f"expected {source['bytes']} bytes / {EXPECTED_DATABASE}, "
            f"got {actual_size} bytes / {actual_digest}"
        )
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")

    check_artifact_index(root)
    check_source_integrity(root)
<<<<<<< HEAD
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "ckb_data", "-p", "test_*.py"],
        cwd=root,
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)
=======
    # Discover both the authoritative service tests and research-only tests.
    for test_dir in ("classifier-service/tests", "ckb_data/tests"):
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", test_dir, "-p", "test_*.py"],
            cwd=root,
            check=False,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6
    print("Frozen contracts, hashes, indexed artifacts, SQLite integrity, and tests: OK")
    print("FINAL_RESEARCH_OFFLINE_VERIFICATION_OK")


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[1])
