#!/usr/bin/env bats

setup() {
    TEST_TMPDIR=$(mktemp -d)
    export VORTIS_HOME="$TEST_TMPDIR/.vortis"
    mkdir -p "$VORTIS_HOME/.state/models"
    mkdir -p "$VORTIS_HOME/.scripts"
    cat > "$VORTIS_HOME/.scripts/install-rust.sh" <<EOF
#!/usr/bin/env bash
exit 0
EOF
    cat > "$VORTIS_HOME/.scripts/build-extension.sh" <<EOF
#!/usr/bin/env bash
touch "\$VORTIS_HOME/.state/extension-built"
exit 0
EOF
    cat > "$VORTIS_HOME/.scripts/pull-model.sh" <<EOF
#!/usr/bin/env bash
key=\$(printf '%s' "\$1" | (command -v sha256sum >/dev/null && sha256sum || shasum -a 256) | cut -d ' ' -f 1)
mkdir -p "\$VORTIS_HOME/.state/models/v1"
printf '%s\\n' "\$1" > "\$VORTIS_HOME/.state/models/v1/\${key}.ready"
exit 0
EOF
    chmod +x "$VORTIS_HOME/.scripts/"*.sh
    export SCRIPT="$BATS_TEST_DIRNAME/../../../scripts/install/bg-orchestrator.sh"
}

model_marker() {
    local model_id="$1" state="$2" key
    key=$(printf '%s' "$model_id" | (command -v sha256sum >/dev/null && sha256sum || shasum -a 256) | cut -d ' ' -f 1)
    printf '%s/.state/models/v1/%s.%s' "$VORTIS_HOME" "$key" "$state"
}

teardown() {
    [[ -n "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

@test "writes pid file" {
    run bash "$SCRIPT" qwen3.5:9b
    [ "$status" -eq 0 ]
    [ -f "$VORTIS_HOME/.state/bg-orchestrator.log" ]
    grep -q "pid=" "$VORTIS_HOME/.state/bg-orchestrator.log"
}

@test "invokes build-extension after install-rust succeeds" {
    run bash "$SCRIPT" qwen3.5:9b
    [ "$status" -eq 0 ]
    [ -f "$VORTIS_HOME/.state/extension-built" ]
}

@test "invokes pull-model.sh for each model arg" {
    run bash "$SCRIPT" qwen3.5:9b qwen3.5:27b
    [ "$status" -eq 0 ]
    [ -f "$(model_marker qwen3.5:9b ready)" ]
    [ -f "$(model_marker qwen3.5:27b ready)" ]
}

@test "removes pid file when done (via trap)" {
    run bash "$SCRIPT" qwen3.5:9b
    [ "$status" -eq 0 ]
    [ ! -f "$VORTIS_HOME/.state/bg.pid" ]
}
