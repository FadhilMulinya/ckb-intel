#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${1:-python3}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
<<<<<<< HEAD
export PYTHONPATH="$ROOT_DIR/ckb_data"
=======
export PYTHONPATH="$ROOT_DIR/classifier-service:$ROOT_DIR/ckb_data:$ROOT_DIR"
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6
"$PYTHON_BIN" scripts/verify_final_research.py
