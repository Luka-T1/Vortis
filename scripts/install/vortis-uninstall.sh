#!/usr/bin/env bash

set -euo pipefail

VORTIS_HOME="${VORTIS_HOME:-$HOME/.vortis}"
ASSUME_YES=false

usage() {
    cat <<'EOF'
Usage: vortis-uninstall [-y|--yes]

Removes Vortis and its local data. Without --yes, an explicit confirmation
is required before config, memory, skills, databases, or connector tokens are
deleted.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            ASSUME_YES=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

refuse_unsafe_root() {
    echo "Refusing unsafe VORTIS_HOME: $VORTIS_HOME" >&2
    exit 2
}

if [[ -d "$VORTIS_HOME" ]]; then
    resolved_install_root="$(cd "$VORTIS_HOME" && pwd -P)"
    resolved_user_home="$(cd "$HOME" && pwd -P)"
    if [[ -z "$resolved_install_root" ]] \
        || [[ "$resolved_install_root" == "/" ]] \
        || [[ "$resolved_install_root" == "$resolved_user_home" ]] \
        || [[ "$resolved_user_home" == "$resolved_install_root"/* ]]; then
        refuse_unsafe_root
    fi

    case "$resolved_install_root" in
        /Users|/home|/opt|/tmp|/private|/private/tmp|/var|/var/tmp|/private/var|/private/var/tmp|/usr|/etc)
            refuse_unsafe_root
            ;;
    esac

    ownership_marker="$resolved_install_root/.state/install-state.json"
    if [[ ! -f "$ownership_marker" ]] \
        || [[ -L "$ownership_marker" ]] \
        || ! grep -Eq '"(install_uv|clone_repo|copy_scripts|create_venv|editable_install)"[[:space:]]*:[[:space:]]*true' "$ownership_marker"; then
        refuse_unsafe_root
    fi

    VORTIS_HOME="$resolved_install_root"

    if [[ "$ASSUME_YES" != true ]]; then
        cat <<EOF
WARNING: This permanently deletes all Vortis data under:
  $VORTIS_HOME

That includes config.toml, SOUL.md/MEMORY.md/USER.md, skills, scheduler and
telemetry databases, stored memory, and connector/OAuth credentials.
EOF
        printf 'Type "yes" to continue: '
        reply=""
        read -r reply || true
        case "$reply" in
            yes|YES|Yes) ;;
            *)
                echo "Vortis was not removed."
                exit 0
                ;;
        esac
    fi
fi

if [[ -f "$VORTIS_HOME/.state/bg.pid" ]]; then
    pid=$(cat "$VORTIS_HOME/.state/bg.pid" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        echo "Stopping background work (pid=$pid)..."
        kill "$pid" 2>/dev/null || true
    fi
fi

if command -v ollama >/dev/null 2>&1; then
    ollama stop >/dev/null 2>&1 || true
fi

if [[ -d "$VORTIS_HOME" ]]; then
    rm -rf -- "$VORTIS_HOME"
    echo "Removed $VORTIS_HOME"
fi

for f in "$HOME/.local/bin/vortis" "$HOME/.local/bin/vortis-uninstall"; do
    if [[ -L "$f" ]] || [[ -f "$f" ]]; then
        rm -f "$f"
        echo "Removed $f"
    fi
done

cat <<EOF

Vortis removed.

Left intact (may be used by other tools):
  - Ollama       (uninstall: brew uninstall ollama  /  rm -f /usr/local/bin/ollama)
  - uv           (uninstall: rm -rf ~/.local/share/uv ~/.cargo/bin/uv)
  - Rust toolchain (uninstall: rustup self uninstall)
EOF
