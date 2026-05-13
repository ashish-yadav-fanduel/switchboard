#!/usr/bin/env bash
# Switchboard plugin bootstrap.
# ${CLAUDE_PLUGIN_ROOT}  — directory where this script lives (read-only plugin files)
# ${CLAUDE_PLUGIN_DATA}  — persistent writable directory (venv, stats, pid)

set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/hooks/switchboard}"
VENV="$DATA_DIR/venv"
PYTHON="$VENV/bin/python3"
REQ="$PLUGIN_ROOT/requirements.txt"
STAMP="$DATA_DIR/.req_stamp"

# One-time setup: create venv and install deps (non-fatal — hook degrades gracefully)
if [[ ! -x "$PYTHON" ]]; then
    mkdir -p "$DATA_DIR"
    python3 -m venv "$VENV" >/dev/null 2>&1 || true
fi

# Install / upgrade deps when requirements.txt changes
if [[ -x "$PYTHON" && "$REQ" -nt "$STAMP" ]]; then
    "$VENV/bin/pip" install --quiet -r "$REQ" >/dev/null 2>&1 && touch "$STAMP" || true
fi

export SWITCHBOARD_DATA="$DATA_DIR"
exec "$PYTHON" "$PLUGIN_ROOT/switchboard.py"
