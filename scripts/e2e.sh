#!/usr/bin/env bash
# Starts the full stack (isolated test MongoDB + both services), runs
# tests/e2e_test.py against them, tears everything down, and exits with
# the test suite's exit code -- so this is safe to wire into CI as a
# single command.
#
# Usage:
#   ./scripts/e2e.sh
#
# Uses its own MongoDB dbpath (.data-e2e/) so this never touches or is
# affected by a developer's ./scripts/dev.sh dataset -- and refuses to run
# if ports 3000/8000/27017 are already in use, rather than silently
# testing against someone else's already-running instance.

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/.data-e2e"
MONGO_DBPATH="$DATA_DIR/mongo"
MONGO_PIDFILE="$DATA_DIR/mongod.pid"

for port in 3000 8000 27017; do
  if curl -s -o /dev/null "http://localhost:$port" 2>/dev/null || nc -z localhost "$port" 2>/dev/null; then
    echo "[e2e] ERROR: port $port is already in use -- stop whatever's running there first (this script needs a clean slate, not an existing dev.sh session)." >&2
    exit 1
  fi
done

rm -rf "$DATA_DIR"
mkdir -p "$MONGO_DBPATH"

PIDS=()
MONGO_STARTED=0

cleanup() {
  local exit_code=$?
  echo
  echo "[e2e] tearing down..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  if [ "$MONGO_STARTED" = "1" ] && [ -f "$MONGO_PIDFILE" ]; then
    mongo_pid="$(cat "$MONGO_PIDFILE")"
    kill "$mongo_pid" 2>/dev/null || true
    # Wait for it to actually exit (WiredTiger shutdown isn't instant)
    # before deleting its data directory out from under it -- firing the
    # signal and immediately rm -rf'ing raced mongod's shutdown and left
    # it running in earlier versions of this script.
    for _ in $(seq 1 20); do
      kill -0 "$mongo_pid" 2>/dev/null || break
      sleep 0.5
    done
    kill -9 "$mongo_pid" 2>/dev/null || true
  fi
  rm -rf "$DATA_DIR"
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

echo "[e2e] starting mongod (dbpath: $MONGO_DBPATH)..."
mongod --dbpath "$MONGO_DBPATH" --port 27017 --bind_ip 127.0.0.1 \
  --logpath "$DATA_DIR/mongod.log" --pidfilepath "$MONGO_PIDFILE" --fork
MONGO_STARTED=1

echo "[e2e] starting registry-service on :3000..."
(cd "$ROOT_DIR/registry-service" && exec ./node_modules/.bin/tsx src/index.ts) > "$DATA_DIR/registry-service.log" 2>&1 &
PIDS+=($!)

echo -n "[e2e] waiting for registry-service health..."
for _ in $(seq 1 30); do
  curl -s -o /dev/null http://localhost:3000/api/v1/health && { echo " up"; break; }
  echo -n "."
  sleep 1
done

if [ ! -d "$ROOT_DIR/venv" ]; then
  echo "[e2e] no ./venv found, creating one and installing dependencies..."
  python3 -m venv "$ROOT_DIR/venv"
  "$ROOT_DIR/venv/bin/pip" install -q -r "$ROOT_DIR/classifier-service/requirements.txt"
fi

echo "[e2e] starting classifier-service on :8000..."
(
  cd "$ROOT_DIR/classifier-service"
  export REGISTRY_SERVICE_URL="http://localhost:3000"
  "$ROOT_DIR/venv/bin/uvicorn" app:app --host 127.0.0.1 --port 8000
) > "$DATA_DIR/classifier-service.log" 2>&1 &
PIDS+=($!)

echo -n "[e2e] waiting for classifier-service health..."
for _ in $(seq 1 30); do
  curl -s -o /dev/null http://localhost:8000/health && { echo " up"; break; }
  echo -n "."
  sleep 1
done

echo
echo "[e2e] running end-to-end suite..."
echo
"$ROOT_DIR/venv/bin/python3" "$ROOT_DIR/tests/e2e_test.py"
