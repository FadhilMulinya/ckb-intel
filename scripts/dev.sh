#!/usr/bin/env bash
# Starts the whole local stack: registry-service (Node, port 3000), and
# classifier-service's classification API (Python/FastAPI, port 8000), wired
# together via REGISTRY_SERVICE_URL. Ctrl-C stops everything it started.
#
# Usage:
#   ./scripts/dev.sh
#
# Requires: mongod on PATH, Node.js + npm, a Python 3 with
# classifier-service/requirements.txt installed (this script creates
# ./venv/ on first run if it doesn't exist yet).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/.data"
MONGO_DBPATH="$DATA_DIR/mongo"
MONGO_LOG="$DATA_DIR/mongod.log"
MONGO_PIDFILE="$DATA_DIR/mongod.pid"
REGISTRY_LOG="$DATA_DIR/registry-service.log"
CLASSIFIER_LOG="$DATA_DIR/classifier-service.log"

mkdir -p "$MONGO_DBPATH"

PIDS=()
MONGO_STARTED_BY_SCRIPT=0

cleanup() {
  echo
  echo "Shutting down..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  if [ "$MONGO_STARTED_BY_SCRIPT" = "1" ] && [ -f "$MONGO_PIDFILE" ]; then
    mongo_pid="$(cat "$MONGO_PIDFILE")"
    kill "$mongo_pid" 2>/dev/null || true
    # Wait for it to actually exit before moving on -- firing the signal
    # and not confirming shutdown left it running in earlier versions of
    # this script.
    for _ in $(seq 1 20); do
      kill -0 "$mongo_pid" 2>/dev/null || break
      sleep 0.5
    done
    kill -9 "$mongo_pid" 2>/dev/null || true
    rm -f "$MONGO_PIDFILE"
  fi
  echo "Stopped."
}
trap cleanup EXIT INT TERM

# --- MongoDB -----------------------------------------------------------
if ! mongosh --quiet --eval "db.runCommand({ping:1})" >/dev/null 2>&1; then
  echo "[dev] starting mongod (dbpath: $MONGO_DBPATH)..."
  mongod --dbpath "$MONGO_DBPATH" --port 27017 --bind_ip 127.0.0.1 \
    --logpath "$MONGO_LOG" --pidfilepath "$MONGO_PIDFILE" --fork
  MONGO_STARTED_BY_SCRIPT=1
else
  echo "[dev] mongod already running, reusing it"
fi

# --- registry-service (Node) ---------------------------------------------
# Runs the local tsx binary directly (not `npm start` or `npx tsx`, both of
# which insert an extra wrapper process that doesn't always forward
# signals) so the PID captured below is the actual server process --
# otherwise `kill` in cleanup() can leave it running behind a dead parent.
echo "[dev] starting registry-service on :3000 (log: $REGISTRY_LOG)..."
(cd "$ROOT_DIR/registry-service" && exec ./node_modules/.bin/tsx src/index.ts) > "$REGISTRY_LOG" 2>&1 &
PIDS+=($!)

echo -n "[dev] waiting for registry-service health..."
for _ in $(seq 1 30); do
  if curl -s -o /dev/null http://localhost:3000/api/v1/health; then
    echo " up"
    break
  fi
  echo -n "."
  sleep 1
done

# --- classifier-service (Python/FastAPI) ----------------------------------
if [ ! -d "$ROOT_DIR/venv" ]; then
  echo "[dev] no ./venv found, creating one and installing dependencies..."
  python3 -m venv "$ROOT_DIR/venv"
  "$ROOT_DIR/venv/bin/pip" install -q -r "$ROOT_DIR/classifier-service/requirements.txt"
fi

echo "[dev] starting classifier-service API on :8000 (log: $CLASSIFIER_LOG)..."
(
  cd "$ROOT_DIR/classifier-service"
  export REGISTRY_SERVICE_URL="http://localhost:3000"
  "$ROOT_DIR/venv/bin/uvicorn" app:app --host 127.0.0.1 --port 8000
) > "$CLASSIFIER_LOG" 2>&1 &
PIDS+=($!)

echo -n "[dev] waiting for classifier-service health..."
for _ in $(seq 1 30); do
  if curl -s -o /dev/null http://localhost:8000/health; then
    echo " up"
    break
  fi
  echo -n "."
  sleep 1
done

# --- banner --------------------------------------------------------------
cat <<'BANNER'

╔══════════════════════════════════════════════════════════════════╗
║   CKB Wallet Behaviour Intelligence -- dev stack running          ║
╠══════════════════════════════════════════════════════════════════╣
║   registry-service     docs   http://localhost:3000/api/v1/docs   ║
║   classifier-service   docs   http://localhost:8000/api/v1/docs   ║
╚══════════════════════════════════════════════════════════════════╝

Full endpoint reference lives in each service's docs page above.
BANNER
echo "Logs: $DATA_DIR/*.log -- Ctrl-C to stop."

wait
