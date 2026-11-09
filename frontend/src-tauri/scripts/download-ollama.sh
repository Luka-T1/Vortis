#!/usr/bin/env bash

set -euo pipefail

BINARIES_DIR="$(cd "$(dirname "$0")/../binaries" 2>/dev/null && pwd || echo "$(dirname "$0")/../binaries")"
mkdir -p "$BINARIES_DIR"

if [ "${1:-}" != "" ]; then
    TARGET="$1"
else
    ARCH="$(uname -m)"
    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            case "$ARCH" in
                arm64)  TARGET="aarch64-apple-darwin" ;;
                x86_64) TARGET="x86_64-apple-darwin" ;;
                *)      echo "Unsupported arch: $ARCH"; exit 1 ;;
            esac
            ;;
        Linux)
            case "$ARCH" in
                x86_64)  TARGET="x86_64-unknown-linux-gnu" ;;
                aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
                *)       echo "Unsupported arch: $ARCH"; exit 1 ;;
            esac
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            case "${PROCESSOR_ARCHITEW6432:-${PROCESSOR_ARCHITECTURE:-$ARCH}}" in
                ARM64|arm64|aarch64) TARGET="aarch64-pc-windows-msvc" ;;
                AMD64|amd64|x86_64) TARGET="x86_64-pc-windows-msvc" ;;
                *) echo "Unsupported Windows arch: $ARCH"; exit 1 ;;
            esac
            ;;
        *)
            echo "Unsupported OS: $OS"; exit 1 ;;
    esac
fi

echo "Target triple: $TARGET"

SUFFIX=""
case "$TARGET" in
    *windows*) SUFFIX=".exe" ;;
esac
OUT_FILE="$BINARIES_DIR/ollama-${TARGET}${SUFFIX}"
RUNTIME_DIR="$BINARIES_DIR/ollama-runtime-${TARGET}"

if [ -f "$OUT_FILE" ] && { [ "$TARGET" != "aarch64-pc-windows-msvc" ] || [ -d "$RUNTIME_DIR/lib/ollama" ]; }; then
    echo "Already exists: $OUT_FILE"
    echo "Delete it first to re-download."
    exit 0
fi

RELEASE_URL="https://github.com/ollama/ollama/releases/latest/download"

case "$TARGET" in
    *apple-darwin)
        ASSET_URL="${RELEASE_URL}/ollama-darwin.tgz"
        ARCHIVE_TYPE="tgz"
        ;;
    x86_64-unknown-linux-gnu)
        ASSET_URL="${RELEASE_URL}/ollama-linux-amd64.tar.zst"
        ARCHIVE_TYPE="zst"
        ;;
    aarch64-unknown-linux-gnu)
        ASSET_URL="${RELEASE_URL}/ollama-linux-arm64.tar.zst"
        ARCHIVE_TYPE="zst"
        ;;
    x86_64-pc-windows-msvc)
        ASSET_URL="${RELEASE_URL}/ollama-windows-amd64.zip"
        ARCHIVE_TYPE="zip"
        ;;
    aarch64-pc-windows-msvc)
        ASSET_URL="${RELEASE_URL}/ollama-windows-arm64.zip"
        ARCHIVE_TYPE="zip"
        ;;
    *)
        echo "No Ollama binary mapping for target: $TARGET"
        exit 1
        ;;
esac

OLLAMA_TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$OLLAMA_TMP_DIR"' EXIT

echo "Downloading: $ASSET_URL"
ARCHIVE_FILE="$OLLAMA_TMP_DIR/ollama-archive"
curl -fSL --progress-bar "$ASSET_URL" -o "$ARCHIVE_FILE"

echo "Extracting..."
case "$ARCHIVE_TYPE" in
    tgz)
        tar xzf "$ARCHIVE_FILE" -C "$OLLAMA_TMP_DIR"
        ;;
    zst)
        if command -v zstd &>/dev/null; then
            zstd -d "$ARCHIVE_FILE" -o "$OLLAMA_TMP_DIR/ollama.tar" --quiet
            tar xf "$OLLAMA_TMP_DIR/ollama.tar" -C "$OLLAMA_TMP_DIR"
        else
            echo "zstd not found. Install with: brew install zstd (macOS) or apt install zstd (Linux)"
            exit 1
        fi
        ;;
    zip)
        unzip -q "$ARCHIVE_FILE" -d "$OLLAMA_TMP_DIR"
        ;;
esac

OLLAMA_BIN=""
for candidate in "$OLLAMA_TMP_DIR/bin/ollama" "$OLLAMA_TMP_DIR/ollama" "$OLLAMA_TMP_DIR/ollama.exe"; do
    if [ -f "$candidate" ]; then
        OLLAMA_BIN="$candidate"
        break
    fi
done

if [ -z "$OLLAMA_BIN" ]; then
    echo "Could not find ollama binary in archive. Contents:"
    find "$OLLAMA_TMP_DIR" -type f | head -20
    exit 1
fi

if [ "$TARGET" = "universal-apple-darwin" ]; then
    if ! lipo "$OLLAMA_BIN" -verify_arch arm64 x86_64; then
        echo "Ollama's darwin archive does not contain a universal arm64+x86_64 binary"
        exit 1
    fi
fi

if [ "$TARGET" = "aarch64-pc-windows-msvc" ]; then
    if [ ! -d "$OLLAMA_TMP_DIR/lib/ollama" ]; then
        echo "Windows Ollama archive is missing its lib/ollama inference runtime"
        exit 1
    fi
    rm -rf "$RUNTIME_DIR"
    mkdir -p "$RUNTIME_DIR"
    for resource in "$OLLAMA_TMP_DIR"/*; do
        case "$(basename "$resource")" in
            ollama.exe|ollama-archive) continue ;;
        esac
        cp -R "$resource" "$RUNTIME_DIR/"
    done
fi

cp "$OLLAMA_BIN" "$OUT_FILE"
chmod +x "$OUT_FILE"

echo "Saved to: $OUT_FILE"
ls -lh "$OUT_FILE"
echo "Done."
