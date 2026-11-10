#!/usr/bin/env bash

VORTIS_HOME="${VORTIS_HOME:-$HOME/.vortis}"
VENV="$VORTIS_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "vortis: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://raw.githubusercontent.com/Luka-T1/Vortis/main/scripts/install/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/vortis" "$@"
