#!/usr/bin/env bats

setup() {
    export VORTIS_TEST_PYTHON="${VORTIS_TEST_PYTHON:-$(command -v python3)}"
    export PYTHONPATH="$BATS_TEST_DIRNAME/../../../src"
    unset VORTIS_CONFIG XDG_DATA_HOME
    TEST_TMPDIR=$(mktemp -d)
    export FAKE_HOME="$TEST_TMPDIR/home"
    mkdir -p "$FAKE_HOME"
    export HOME="$FAKE_HOME"
    export VORTIS_HOME="$FAKE_HOME/.vortis"

    export STUBS_DIR="$BATS_TEST_DIRNAME/stubs"
    export PATH="$STUBS_DIR:/usr/bin:/bin"

    export GIT_STUB_LOG="$TEST_TMPDIR/git.log"
    export OLLAMA_STUB_LOG="$TEST_TMPDIR/ollama.log"
    export UV_STUB_LOG="$TEST_TMPDIR/uv.log"
    export CURL_STUB_LOG="$TEST_TMPDIR/curl.log"
    export JARVIS_STUB_LOG="$TEST_TMPDIR/jarvis.log"
    : > "$GIT_STUB_LOG"
    : > "$OLLAMA_STUB_LOG"
    : > "$UV_STUB_LOG"
    : > "$CURL_STUB_LOG"

    export PER_TEST_STUBS="$TEST_TMPDIR/stubs"
    mkdir -p "$PER_TEST_STUBS"
    cat "$STUBS_DIR/uv" > "$PER_TEST_STUBS/uv"
    chmod +x "$PER_TEST_STUBS/uv"
    cat > "$PER_TEST_STUBS/uv" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "\$UV_STUB_LOG"
case "\$1" in
    venv)
        for a in "\$@"; do
            if [[ "\$a" != --* ]] && [[ "\$a" != -* ]] && [[ "\$a" != "venv" ]] && [[ ! "\$a" =~ ^[0-9]+\\.[0-9]+\$ ]]; then
                venv_path="\$a"
            fi
        done
        if [[ -n "\$venv_path" ]]; then
            mkdir -p "\$venv_path/bin"
            cat > "\$venv_path/bin/vortis" <<'EOJ'
#!/usr/bin/env bash
echo "\$@" >> "\$JARVIS_STUB_LOG"
echo "fake jarvis: \$@"
exit 0
EOJ
            chmod +x "\$venv_path/bin/vortis"
            cat > "\$venv_path/bin/python" <<'EOJ'
#!/usr/bin/env bash
exec "\$VORTIS_TEST_PYTHON" "\$@"
EOJ
            chmod +x "\$venv_path/bin/python"
        fi
        ;;
esac
exit 0
EOF
    chmod +x "$PER_TEST_STUBS/uv"

    cp "$STUBS_DIR"/{git,curl,ollama,cargo,rustup} "$PER_TEST_STUBS/"
    chmod +x "$PER_TEST_STUBS"/*

    export PATH="$PER_TEST_STUBS:/usr/bin:/bin"

    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/install.sh"
}

teardown() {
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

@test "install never sends analytics or creates an anon id" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    ! grep -q 'sslip.io' "$CURL_STUB_LOG"
    [ ! -f "$VORTIS_HOME/anon_id" ]
}

@test "legacy analytics flags are accepted and ignored" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --analytics
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
    [ ! -f "$VORTIS_HOME/anon_id" ]
    run bash "$SCRIPT" --no-bg-orchestrator --minimal --no-analytics
    [ "$status" -eq 0 ]
    ! grep -q '/i/v0/e/' "$CURL_STUB_LOG"
}

@test "installer contains no analytics endpoint" {
    ! grep -qiE 'posthog|sslip\.io|phc_' "$SCRIPT"
}

@test "refuses to run as root" {
    local root_stubs="$TEST_TMPDIR/root_stubs"
    mkdir -p "$root_stubs"
    cp "$PER_TEST_STUBS"/* "$root_stubs/"
    cat > "$root_stubs/id" <<'IDEOF'
#!/usr/bin/env bash
if [[ "$1" == "-u" ]]; then echo 0; else echo "uid=0(root) gid=0(root) groups=0(root)"; fi
IDEOF
    chmod +x "$root_stubs/id"
    PATH="$root_stubs:/usr/bin:/bin" run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -ne 0 ]
    echo "$output" | grep -qi "root"
}

@test "creates ~/.vortis directory tree" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -d "$VORTIS_HOME/src" ]
    [ -d "$VORTIS_HOME/.state" ]
    [ -d "$VORTIS_HOME/.scripts" ]
}

@test "writes install-state.json on success" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -f "$VORTIS_HOME/.state/install-state.json" ]
}

@test "calls git clone for the Vortis repo" {
    run bash "$SCRIPT" --no-bg-orchestrator
    grep -q "clone" "$GIT_STUB_LOG"
}

@test "creates jarvis symlink in ~/.local/bin" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    [ -L "$FAKE_HOME/.local/bin/vortis" ] || [ -f "$FAKE_HOME/.local/bin/vortis" ]
}

@test "is idempotent — second run skips completed steps" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    : > "$GIT_STUB_LOG"
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    ! grep -q "clone" "$GIT_STUB_LOG"
}

@test "detects WSL2 and writes platform note to install-state" {
    VORTIS_FORCE_WSL=1 run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    grep -q "wsl" "$VORTIS_HOME/.state/install-state.json"
}

@test "fails loudly when git is missing" {
    local no_git_stubs="$TEST_TMPDIR/no_git_stubs"
    mkdir -p "$no_git_stubs"
    for f in curl uv ollama cargo rustup; do
        cp "$PER_TEST_STUBS/$f" "$no_git_stubs/"
        chmod +x "$no_git_stubs/$f"
    done
    cat > "$no_git_stubs/id" <<'IDEOF'
#!/bin/bash
echo "1000"
IDEOF
    chmod +x "$no_git_stubs/id"
    ln -sf /bin/cat "$no_git_stubs/cat"
    ln -sf /bin/bash "$no_git_stubs/bash"
    PATH="$no_git_stubs" run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -ne 0 ]
    echo "$output" | grep -qi "git"
}

@test "--force re-runs completed steps" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    : > "$GIT_STUB_LOG"
    run bash "$SCRIPT" --no-bg-orchestrator --force
    [ "$status" -eq 0 ]
    grep -q "clone" "$GIT_STUB_LOG"
}

@test "--minimal skips foreground model pull" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    if [ -s "$OLLAMA_STUB_LOG" ]; then
        ! grep -q "^pull " "$OLLAMA_STUB_LOG"
    fi
}

@test "install succeeds with no system Python on PATH (#484)" {
    local no_py_stubs="$TEST_TMPDIR/no_py_stubs"
    mkdir -p "$no_py_stubs"
    for f in git curl uv ollama cargo rustup; do
        cp "$PER_TEST_STUBS/$f" "$no_py_stubs/"
        chmod +x "$no_py_stubs/$f"
    done
    for util in id cat bash sh head tail awk sed grep od tr cut mv rm mkdir cp chmod ln test pgrep date sleep ps; do
        if [[ -x "/usr/bin/$util" ]]; then
            ln -sf "/usr/bin/$util" "$no_py_stubs/$util"
        elif [[ -x "/bin/$util" ]]; then
            ln -sf "/bin/$util" "$no_py_stubs/$util"
        fi
    done
    if [[ ! -x "$no_py_stubs/pgrep" ]]; then
        printf '#!/bin/sh\nexit 1\n' > "$no_py_stubs/pgrep"
        chmod +x "$no_py_stubs/pgrep"
    fi
    PATH="$no_py_stubs" run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    [ -f "$VORTIS_HOME/.state/install-state.json" ]
    grep -q '"install_uv":' "$VORTIS_HOME/.state/install-state.json"
}

@test "mark_done is idempotent — second mark of same key doesn't duplicate" {
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    local first_count
    first_count="$(grep -c '"install_uv":' "$VORTIS_HOME/.state/install-state.json")"
    [ "$first_count" -eq 1 ]
    run bash "$SCRIPT" --no-bg-orchestrator
    [ "$status" -eq 0 ]
    local second_count
    second_count="$(grep -c '"install_uv":' "$VORTIS_HOME/.state/install-state.json")"
    [ "$second_count" -eq 1 ]
}

@test "create_venv picks newest in requires-python range, not hardcoded 3.11 (#476)" {
    run bash "$SCRIPT" --no-bg-orchestrator --minimal
    [ "$status" -eq 0 ]
    grep -q '^venv --python 3.13' "$UV_STUB_LOG"
}
