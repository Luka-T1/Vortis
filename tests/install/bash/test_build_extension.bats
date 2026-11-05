#!/usr/bin/env bats

setup() {
    TEST_TMPDIR=$(mktemp -d)
    export VORTIS_HOME="$TEST_TMPDIR/.vortis"
    mkdir -p "$VORTIS_HOME/.state"
    mkdir -p "$VORTIS_HOME/src/rust/crates/vortis-python"
    touch "$VORTIS_HOME/src/rust/crates/vortis-python/Cargo.toml"
    export UV_STUB_LOG="$TEST_TMPDIR/uv.log"
    : > "$UV_STUB_LOG"
    export PYTHON_STUB_LOG="$TEST_TMPDIR/python.log"
    : > "$PYTHON_STUB_LOG"
    mkdir -p "$VORTIS_HOME/.venv/bin"
    cat > "$VORTIS_HOME/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
echo "$0 $*" >> "$PYTHON_STUB_LOG"
exit "${PYTHON_STUB_EXIT:-0}"
EOF
    chmod +x "$VORTIS_HOME/.venv/bin/python"
    export UVX_STUB="$BATS_TEST_DIRNAME/stubs/uvx"
    uvx() { "$UVX_STUB" "$@"; }
    export -f uvx
    export PATH="$BATS_TEST_DIRNAME/stubs:$PATH"
    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/build-extension.sh"
}

teardown() {
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

@test "writes extension-built marker on success" {
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    [ -f "$VORTIS_HOME/.state/extension-built" ]
}

@test "writes extension-failed marker on failure" {
    UV_STUB_EXIT=1 run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [ -f "$VORTIS_HOME/.state/extension-failed" ]
    [ -s "$VORTIS_HOME/.state/extension-failed" ]
}

@test "removes prior failed marker on success" {
    touch "$VORTIS_HOME/.state/extension-failed"
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    [ ! -f "$VORTIS_HOME/.state/extension-failed" ]
    [ -f "$VORTIS_HOME/.state/extension-built" ]
}

@test "builds and verifies the extension in the runtime venv" {
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    grep -Fx "VIRTUAL_ENV=$VORTIS_HOME/.venv" "$UV_STUB_LOG"
    grep -Fx "maturin develop --uv -m $VORTIS_HOME/src/rust/crates/vortis-python/Cargo.toml" "$UV_STUB_LOG"
    grep -Fx "$VORTIS_HOME/.venv/bin/python -c import vortis_rust" "$PYTHON_STUB_LOG"
    [ ! -d "$VORTIS_HOME/src/.venv" ]
}

@test "reports a failed runtime import and preserves its exit code" {
    touch "$VORTIS_HOME/.state/extension-built"
    PYTHON_STUB_EXIT=7 run bash "$SCRIPT"
    [ "$status" -eq 7 ]
    [ ! -f "$VORTIS_HOME/.state/extension-built" ]
    grep -q "failed in the serving venv ($VORTIS_HOME/.venv)" "$VORTIS_HOME/.state/extension-failed"
    grep -q 'exit=7' "$VORTIS_HOME/.state/extension-failed"
}

@test "fails before compilation when the runtime venv is missing" {
    touch "$VORTIS_HOME/.state/extension-built"
    rm -f "$VORTIS_HOME/.venv/bin/python"
    run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [ ! -s "$UV_STUB_LOG" ]
    [ ! -f "$VORTIS_HOME/.state/extension-built" ]
    grep -q "runtime venv not found" "$VORTIS_HOME/.state/extension-failed"
}

@test "fails before compilation when the manifest is missing" {
    touch "$VORTIS_HOME/.state/extension-built"
    rm -f "$VORTIS_HOME/src/rust/crates/vortis-python/Cargo.toml"
    run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [ ! -s "$UV_STUB_LOG" ]
    [ ! -f "$VORTIS_HOME/.state/extension-built" ]
    grep -q "manifest not found" "$VORTIS_HOME/.state/extension-failed"
}

@test "atomic rename — no .tmp file left behind" {
    UV_STUB_EXIT=0 run bash "$SCRIPT"
    leftover=$(find "$VORTIS_HOME/.state" -name "*.tmp" 2>/dev/null | wc -l)
    [ "$leftover" -eq 0 ]
}
