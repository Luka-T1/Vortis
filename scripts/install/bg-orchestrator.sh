#!/usr/bin/env bash

set -euo pipefail

VORTIS_HOME="${VORTIS_HOME:-$HOME/.vortis}"
STATE_DIR="$VORTIS_HOME/.state"
SCRIPTS_DIR="$VORTIS_HOME/.scripts"
PID_FILE="$STATE_DIR/bg.pid"
LOG="$STATE_DIR/bg-orchestrator.log"

mkdir -p "$STATE_DIR"
echo "$$" > "$PID_FILE"

cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT

echo "[$(date -u +%FT%TZ)] bg-orchestrator started, pid=$$" >> "$LOG"

(
    "$SCRIPTS_DIR/install-rust.sh" >> "$LOG" 2>&1 \
        && "$SCRIPTS_DIR/build-extension.sh" >> "$LOG" 2>&1
) &
RUST_PID=$!

MODEL_PIDS=()
for model in "$@"; do
    "$SCRIPTS_DIR/pull-model.sh" "$model" >> "$LOG" 2>&1 &
    MODEL_PIDS+=($!)
done

wait "$RUST_PID" || true
for pid in "${MODEL_PIDS[@]}"; do
    wait "$pid" || true
done

echo "[$(date -u +%FT%TZ)] bg-orchestrator done" >> "$LOG"
