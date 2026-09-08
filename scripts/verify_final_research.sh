#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${1:-python3}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/ckb_data"
"$PYTHON_BIN" scripts/verify_final_research.py
