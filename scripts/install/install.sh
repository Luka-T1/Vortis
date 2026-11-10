#!/usr/bin/env bash

set -euo pipefail

SKIP_BG=0
MINIMAL=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --no-bg-orchestrator) SKIP_BG=1 ;;
        --minimal) MINIMAL=1 ;;
        --force) FORCE=1 ;;
        --analytics|--no-analytics) ;;  # analytics removed; flag ignored
        *) echo "install.sh: unknown arg: $arg" >&2; exit 2 ;;
    esac
done

case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*)
        cat >&2 <<'EOF'
install.sh: native Windows (Git Bash / MSYS2 / Cygwin) is not supported.

Vortis runs on Windows via WSL2. Two paths:

  1. WSL2 (recommended for the CLI). One-time setup in an admin PowerShell:

       wsl --install -d Ubuntu-24.04

     Open the Ubuntu shell that gets installed, then re-run:

       curl -fsSL https://raw.githubusercontent.com/Luka-T1/Vortis/main/scripts/install/install.sh | bash

  2. Desktop app — download the .exe from the Releases page:
     https://github.com/Luka-T1/Vortis/releases

See the WSL2 install guide for the full walkthrough:
  https://github.com/Luka-T1/Vortis
EOF
        exit 1
        ;;
esac

if [[ "$(id -u)" -eq 0 ]]; then
    cat >&2 <<'EOF'
install.sh: don't run as root.

Vortis installs to $HOME/.vortis, not /usr/local. Re-run as your
regular user (without sudo).
EOF
    exit 1
fi

need() {
    if command -v "$1" >/dev/null 2>&1; then
        return 0
    fi
    case "$(uname -s)" in
        Darwin)  bootstrap_macos_tool "$1" ;;
        Linux)   bootstrap_linux_tool "$1" ;;
        *)       fail_missing_tool "$1" ;;
    esac
}

bootstrap_macos_tool() {
    local tool="$1"
    if [[ -z "${SSH_TTY:-}${SSH_CONNECTION:-}" ]]; then
        :  # local GUI session — proceed
    else
        cat >&2 <<EOF
install.sh: '$tool' not found, and this looks like a headless SSH session
(SSH_CONNECTION is set). The xcode-select GUI installer can't run here.

Install '$tool' over SSH with one of:
  - From a GUI login: 'xcode-select --install' (then re-run this script)
  - Or: a third-party manager — Homebrew / MacPorts / nix

Re-run this script once '$tool' is on PATH.
EOF
        exit 1
    fi
    echo "install.sh: '$tool' not found — installing Xcode Command Line Tools (provides git + curl)..."
    echo "  A system dialog will open. Click 'Install' and accept the license."
    xcode-select --install 2>/dev/null || true
    local waited=0
    while ! command -v "$tool" >/dev/null 2>&1; do
        if (( waited >= 600 )); then  # 10 minutes
            echo "install.sh: timed out waiting for Xcode Command Line Tools."
            echo "  Finish the install via the dialog, then re-run this command."
            exit 1
        fi
        sleep 5
        waited=$((waited + 5))
        if (( waited % 60 == 0 )); then
            echo "  …still waiting for '$tool' to appear (${waited}s)"
        fi
    done
    echo "  '$tool' installed."
}

bootstrap_linux_tool() {
    local tool="$1"
    if [[ "$(id -u)" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
        cat >&2 <<EOF
install.sh: '$tool' is not installed, and we need sudo to install it via
the system package manager — but sudo would prompt for a password and
stdin is occupied by the curl pipe.

Two ways forward:

  1. Install '$tool' yourself, then re-run this installer:
       Debian/Ubuntu: sudo apt install -y $tool
       Fedora/RHEL:   sudo dnf install -y $tool
       Arch:          sudo pacman -S $tool

  2. Pre-authenticate sudo before piping (caches credentials for 5 min):
       sudo -v && curl -fsSL https://raw.githubusercontent.com/Luka-T1/Vortis/main/scripts/install/install.sh | bash
EOF
        exit 1
    fi
    local sudo=""
    [[ "$(id -u)" -ne 0 ]] && sudo="sudo"
    echo "install.sh: '$tool' not found — installing via the system package manager..."
    if command -v apt-get >/dev/null 2>&1; then
        $sudo apt-get update -q || true
        $sudo apt-get install -y "$tool"
    elif command -v dnf >/dev/null 2>&1; then
        $sudo dnf install -y "$tool"
    elif command -v yum >/dev/null 2>&1; then
        $sudo yum install -y "$tool"
    elif command -v pacman >/dev/null 2>&1; then
        $sudo pacman -S --noconfirm "$tool"
    elif command -v zypper >/dev/null 2>&1; then
        $sudo zypper install -y "$tool"
    elif command -v apk >/dev/null 2>&1; then
        $sudo apk add --no-cache "$tool"
    else
        fail_missing_tool "$tool"
    fi
    if ! command -v "$tool" >/dev/null 2>&1; then
        fail_missing_tool "$tool"
    fi
}

fail_missing_tool() {
    cat >&2 <<EOF
install.sh: '$1' is required but not found and we couldn't install it automatically.

Install hints:
  macOS:         xcode-select --install (provides git, curl)
  Debian/Ubuntu: sudo apt install $1
  Fedora/RHEL:   sudo dnf install $1
  Arch:          sudo pacman -S $1

Re-run this script once '$1' is on PATH.
EOF
    exit 1
}

need git
need curl

PY_CMD="python3"
if ! command -v python3 >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PY_CMD="python"
    fi
fi

VORTIS_HOME="${VORTIS_HOME:-$HOME/.vortis}"
VORTIS_REPO_URL="${VORTIS_REPO_URL:-https://github.com/Luka-T1/Vortis.git}"
SRC_DIR="$VORTIS_HOME/src"
VENV_DIR="$VORTIS_HOME/.venv"
STATE_DIR="$VORTIS_HOME/.state"
SCRIPTS_DIR="$VORTIS_HOME/.scripts"
STATE_FILE="$STATE_DIR/install-state.json"

mkdir -p "$VORTIS_HOME" "$STATE_DIR" "$SCRIPTS_DIR"

WSL=0
if [[ "${VORTIS_FORCE_WSL:-0}" == "1" ]]; then
    WSL=1
elif [[ -f /proc/sys/kernel/osrelease ]] && grep -qi "microsoft" /proc/sys/kernel/osrelease 2>/dev/null; then
    WSL=1
fi

INSTALL_START_EPOCH="$(date +%s)"
CURRENT_STAGE=""

_on_install_error() {
    local exit_code=$?
    echo "install.sh: failed during stage '${CURRENT_STAGE:-startup}' (exit $exit_code)" >&2
    exit "$exit_code"
}
trap _on_install_error ERR

state_done() {
    [[ -f "$STATE_FILE" ]] && grep -q "\"$1\":[[:space:]]*true" "$STATE_FILE"
}

mark_done() {
    local key="$1"
    if [[ ! -f "$STATE_FILE" ]] || [[ ! -s "$STATE_FILE" ]]; then
        echo '{}' > "$STATE_FILE"
    fi

    if grep -q "\"$key\":[[:space:]]*true" "$STATE_FILE"; then
        return 0
    fi

    local wsl_bool
    wsl_bool="$([[ $WSL -eq 1 ]] && echo true || echo false)"

    local tmp="${STATE_FILE}.tmp.$$"
    awk -v new_key="$key" -v wsl="$wsl_bool" '
    /"[^"]+":[[:space:]]*true/ {
        match($0, /"[^"]+"/)
        k = substr($0, RSTART + 1, RLENGTH - 2)
        if (k != "wsl") keys[++n] = k
    }
    END {
        keys[++n] = new_key
        print "{"
        for (i = 1; i <= n; i++) {
            printf "  \"%s\": true,\n", keys[i]
        }
        printf "  \"wsl\": %s\n", wsl
        print "}"
    }
    ' "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
}

step() {
    local name="$1" desc="$2"; shift 2
    CURRENT_STAGE="$name"
    if [[ "$FORCE" -ne 1 ]] && state_done "$name"; then
        echo "[ok] $desc (already done)"
        return 0
    fi
    echo "[..] $desc"
    local stage_start_epoch stage_elapsed_ms
    stage_start_epoch="$(date +%s)"
    "$@"
    mark_done "$name"
    stage_elapsed_ms=$(( ( $(date +%s) - stage_start_epoch ) * 1000 ))
    echo "[ok] $desc"
}

install_uv() {
    if command -v uv >/dev/null 2>&1; then
        echo "    uv already installed"
        return 0
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if ! command -v uv >/dev/null 2>&1; then
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
}

clone_repo() {
    if [[ "$FORCE" -ne 1 ]] && [[ -d "$SRC_DIR/.git" ]]; then
        echo "    repo already at $SRC_DIR"
        return 0
    fi
    if [[ "$VORTIS_REPO_URL" == file://* || -e "$VORTIS_REPO_URL" ]]; then
        git clone "$VORTIS_REPO_URL" "$SRC_DIR"
    else
        git clone --filter=blob:none "$VORTIS_REPO_URL" "$SRC_DIR"
    fi
}

copy_scripts() {
    cp -f "$SRC_DIR"/scripts/install/*.sh "$SCRIPTS_DIR/"
    chmod +x "$SCRIPTS_DIR"/*.sh
}

parse_requires_python() {
    local pyproject="$1"
    local fallback="3.11"
    if [[ ! -f "$pyproject" ]]; then
        echo "$fallback"
        return 0
    fi
    local spec
    spec="$(grep '^requires-python' "$pyproject" | head -1)"
    if [[ -z "$spec" ]]; then
        echo "$fallback"
        return 0
    fi
    local max_incl
    max_incl="$(echo "$spec" | sed -n 's/.*<=\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)"
    if [[ -n "$max_incl" ]]; then
        echo "$max_incl"
        return 0
    fi
    local max
    max="$(echo "$spec" | sed -n 's/.*<\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)"
    if [[ -z "$max" ]]; then
        echo "$fallback"
        return 0
    fi
    local major minor
    major="${max%.*}"
    minor="${max#*.}"
    minor=$((minor - 1))
    if (( minor < 11 )); then
        echo "$fallback"
    else
        echo "${major}.${minor}"
    fi
}

create_venv() {
    local py_version
    py_version="$(parse_requires_python "$SRC_DIR/pyproject.toml")"
    echo "    Target Python: $py_version (from pyproject.toml requires-python)"

    local err_log="$STATE_DIR/venv-create.err"
    if ! uv venv --python "$py_version" "$VENV_DIR" 2>"$err_log"; then
        echo "    No system Python $py_version — uv will download a managed one..."
        uv python install "$py_version"
        if ! uv venv --python "$py_version" "$VENV_DIR"; then
            echo "    venv creation failed. First attempt's stderr:"
            sed 's/^/      /' "$err_log" >&2
            return 1
        fi
    fi
    rm -f "$err_log"
}

editable_install() {
    cd "$SRC_DIR"
    uv pip install --python "$VENV_DIR/bin/python" -e .
}

install_ollama() {
    if command -v ollama >/dev/null 2>&1; then
        echo "    ollama already installed"
        return 0
    fi
    curl -fsSL https://ollama.com/install.sh | sh
}

start_ollama() {
    if pgrep -f "ollama serve" >/dev/null 2>&1; then
        echo "    ollama serve already running"
        wait_for_ollama || true
        return 0
    fi
    if [[ "$WSL" -eq 1 ]] || ! command -v systemctl >/dev/null 2>&1; then
        nohup ollama serve > "$STATE_DIR/ollama.log" 2>&1 &
    else
        systemctl --user start ollama 2>/dev/null \
            || nohup ollama serve > "$STATE_DIR/ollama.log" 2>&1 &
    fi
    wait_for_ollama || true
}

wait_for_ollama() {
    local waited=0
    while ! ollama list >/dev/null 2>&1; do
        if (( waited >= 60 )); then
            echo "    warning: ollama daemon not responding after 60s — check $STATE_DIR/ollama.log"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

MODEL_PULL_OK=0

pull_default_model() {
    if [[ "$MINIMAL" -eq 1 ]]; then
        echo "    --minimal set; skipping model pull"
        MODEL_PULL_OK=1  # nothing to pull → not a failure
        return 0
    fi
    if ollama pull qwen3.5:2b; then
        MODEL_PULL_OK=1
    else
        echo "    warning: ollama pull failed; bg-orchestrator will retry in the background"
    fi
}

write_config() {
    "$VENV_DIR/bin/vortis" _bootstrap --write-config \
        --engine ollama --model qwen3.5:2b \
        --prefer-cloud-when-available
}

install_symlinks() {
    mkdir -p "$HOME/.local/bin"
    ln -sf "$SCRIPTS_DIR/vortis-wrapper.sh" "$HOME/.local/bin/vortis"
    ln -sf "$SCRIPTS_DIR/vortis-uninstall.sh" "$HOME/.local/bin/vortis-uninstall"
}

PATH_MODIFIED=0

ensure_path() {
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) return 0 ;;
    esac
    local rc=""
    if [[ "$SHELL" == */zsh ]]; then
        rc="$HOME/.zshrc"
    else
        rc="$HOME/.bashrc"
    fi
    if grep -q "Vortis" "$rc" 2>/dev/null; then
        PATH_MODIFIED=1
        PATH_MODIFIED_RC="$rc"
        return 0
    fi
    {
        echo ''
        echo '# Vortis'
        echo 'export PATH="$HOME/.local/bin:$PATH"'
    } >> "$rc"
    PATH_MODIFIED=1
    PATH_MODIFIED_RC="$rc"
}

detach_bg_orchestrator() {
    if [[ "$SKIP_BG" -eq 1 ]]; then
        echo "    --no-bg-orchestrator set; skipping detach"
        return 0
    fi
    local models
    models=$("$VENV_DIR/bin/python" - <<'PYEOF' 2>/dev/null || true
from vortis.core.config import detect_hardware, recommend_model
hw = detect_hardware()
tier = recommend_model(hw, "ollama")
TIERS = ["qwen3.5:2b", "qwen3.5:4b", "qwen3.5:9b", "qwen3.5:27b"]
out = set([tier]) if tier else set()
if tier in TIERS:
    idx = TIERS.index(tier)
    if idx + 1 < len(TIERS):
        out.add(TIERS[idx + 1])
print(" ".join(sorted(out)))
PYEOF
    )
    if [[ -z "$models" ]]; then
        models=""
    fi
    nohup "$SCRIPTS_DIR/bg-orchestrator.sh" $models \
        > "$STATE_DIR/bg-orchestrator.log" 2>&1 &
    disown
}

echo "Vortis installer"
echo "  install dir: $VORTIS_HOME"
echo "  WSL2:        $WSL"
echo

step install_uv         "Install uv"            install_uv
step clone_repo         "Clone Vortis repo" clone_repo
step copy_scripts       "Copy install scripts"  copy_scripts
step create_venv        "Create venv"           create_venv
step editable_install   "Install Vortis"    editable_install
step install_ollama     "Install Ollama"        install_ollama
step start_ollama       "Start Ollama daemon"   start_ollama
step pull_default_model "Pull qwen3.5:2b"       pull_default_model
step write_config       "Write config.toml"     write_config
step install_symlinks   "Install symlinks"      install_symlinks
step ensure_path        "Ensure PATH"           ensure_path
step detach_bg_orchestrator "Detach background work" detach_bg_orchestrator

INSTALL_TOTAL_MS=$(( ( $(date +%s) - INSTALL_START_EPOCH ) * 1000 ))
trap - ERR

echo
echo "Done."
echo

NEXT_CMD="vortis"
if [[ "$MODEL_PULL_OK" -ne 1 ]]; then
    NEXT_CMD="vortis doctor"
fi

if [[ "$PATH_MODIFIED" -eq 1 ]]; then
    cat <<EOF
A PATH update was written to ${PATH_MODIFIED_RC:-your shell rc file}. To
pick it up in THIS terminal:

  source ${PATH_MODIFIED_RC:-~/.bashrc} && $NEXT_CMD

Or open a new terminal and run: $NEXT_CMD

EOF
else
    cat <<EOF
Run: $NEXT_CMD

EOF
fi

if [[ "$MODEL_PULL_OK" -ne 1 ]]; then
    cat <<EOF
NOTE: the qwen3.5:2b model didn't finish downloading. 'vortis doctor'
shows the retry progress; chat will work once the download completes
in the background.

EOF
fi

cat <<EOF
Background work continues silently:
  - Rust toolchain + maturin extension build
  - Bigger model downloads
  Run 'vortis doctor' to check status anytime.
EOF
