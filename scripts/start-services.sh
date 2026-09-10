#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLASSIFIER_PYTHON="${CLASSIFIER_PYTHON:-python3}"
REGISTRY_COMMAND="${REGISTRY_COMMAND:-}"

if ! command -v "$CLASSIFIER_PYTHON" >/dev/null 2>&1; then
  echo "Classifier Python executable not found: $CLASSIFIER_PYTHON" >&2
  exit 1
fi

if [[ -z "$REGISTRY_COMMAND" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    REGISTRY_COMMAND="pnpm run dev"
  elif command -v npm >/dev/null 2>&1; then
    REGISTRY_COMMAND="npm run dev"
  else
    echo "Neither pnpm nor npm is installed." >&2
    exit 1
  fi
fi

classifier_pid=""
registry_pid=""
cleanup() {
  trap - TERM INT EXIT
  [[ -n "$registry_pid" ]] && kill "$registry_pid" 2>/dev/null || true
  [[ -n "$classifier_pid" ]] && kill "$classifier_pid" 2>/dev/null || true
  wait "$registry_pid" 2>/dev/null || true
  wait "$classifier_pid" 2>/dev/null || true
}
trap cleanup TERM INT EXIT

echo "Starting classifier-service on http://127.0.0.1:8000"
(
  cd "$ROOT_DIR/classifier-service"
  PYTHONPATH=. "$CLASSIFIER_PYTHON" -m uvicorn app:app --host "${CLASSIFIER_HOST:-127.0.0.1}" --port "${CLASSIFIER_PORT:-8000}"
) &
classifier_pid=$!

echo "Starting registry-service on http://127.0.0.1:3000"
(
  cd "$ROOT_DIR/registry-service"
  CLASSIFIER_SERVICE_URL="${CLASSIFIER_SERVICE_URL:-http://127.0.0.1:8000}" \
    API_HOST="${API_HOST:-127.0.0.1}" API_PORT="${API_PORT:-3000}" \
    bash -c "$REGISTRY_COMMAND"
) &
registry_pid=$!

echo "Both services are running. Press Ctrl-C to stop them."
while kill -0 "$classifier_pid" 2>/dev/null && kill -0 "$registry_pid" 2>/dev/null; do
  sleep 1
done
