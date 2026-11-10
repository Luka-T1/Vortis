#!/usr/bin/env bash

set -euo pipefail

VORTIS_HOME="${VORTIS_HOME:-$HOME/.vortis}"
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
SRC_DIR="$VORTIS_HOME/src"
VENV_DIR="$VORTIS_HOME/.venv"
STATE_DIR="$VORTIS_HOME/.state"
LOG="$STATE_DIR/extension-build.log"
BUILT="$STATE_DIR/extension-built"
FAILED="$STATE_DIR/extension-failed"
MANIFEST="$SRC_DIR/rust/crates/vortis-python/Cargo.toml"

mkdir -p "$STATE_DIR"

if [[ ! -f "$MANIFEST" ]]; then
    echo "build-extension.sh: manifest not found at $MANIFEST" > "$FAILED"
    rm -f "$BUILT"
    exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "build-extension.sh: runtime venv not found at $VENV_DIR" > "$FAILED"
    rm -f "$BUILT"
    exit 1
fi

cd "$SRC_DIR"
if VIRTUAL_ENV="$VENV_DIR" uvx maturin develop --uv -m "$MANIFEST" >>"$LOG" 2>&1; then
    if "$VENV_DIR/bin/python" -c "import vortis_rust" >>"$LOG" 2>&1; then
        :
    else
        rc=$?
        {
            echo "build-extension.sh: maturin succeeded but 'import vortis_rust'"
            echo "failed in the serving venv ($VENV_DIR) — the extension was"
            echo "not installed where the server runs. (exit=$rc)"
            tail -n 50 "$LOG" 2>/dev/null || true
        } > "$FAILED"
        rm -f "$BUILT"
        exit "$rc"
    fi
    tmp="$BUILT.tmp"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$tmp"
    mv "$tmp" "$BUILT"
    rm -f "$FAILED"
    exit 0
else
    rc=$?
    {
        echo "build-extension.sh failed (exit=$rc)"
        tail -n 50 "$LOG" 2>/dev/null || true
    } > "$FAILED"
    rm -f "$BUILT"
    exit "$rc"
fi
