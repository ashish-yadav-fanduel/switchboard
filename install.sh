#!/usr/bin/env bash
# Switchboard v2 manual installer.
# Run once per machine. Registers hooks in ~/.claude/settings.json.
# For plugin-managed installs, Claude Code uses run.sh instead.
set -e

# Python 3.10+ required (match-statement / X | Y union types)
PY_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor + sys.version_info.major * 100)' 2>/dev/null || echo 0)
if [[ "$PY_VERSION" -lt 310 ]]; then
    echo "ERROR: Python 3.10+ is required (found $(python3 --version 2>&1 || echo 'none'))."
    echo "       Install via: brew install python@3.12"
    exit 1
fi

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$HOOK_DIR/switchboard.py"
VENV_DIR="$HOOK_DIR/venv"
SETTINGS="$HOME/.claude/settings.json"
DATA_DIR="${SWITCHBOARD_DATA:-$HOME/.claude/hooks/switchboard}"

echo "==> Switchboard v2 installer"
echo "    Plugin root : $HOOK_DIR"
echo "    Data dir    : $DATA_DIR"
echo ""

# ── Venv + deps ───────────────────────────────────────────────────────────────
echo "==> Creating virtual environment..."
python3 -m venv "$VENV_DIR"

echo "==> Installing dependencies (litellm, rich)..."
"$VENV_DIR/bin/pip" install --quiet -r "$HOOK_DIR/requirements.txt"

if [[ "${INSTALL_LLMLINGUA:-0}" == "1" ]]; then
    echo "==> Installing LLMLingua (optional, ~180MB)..."
    "$VENV_DIR/bin/pip" install --quiet llmlingua \
        || echo "    LLMLingua install failed — heuristic compressor will be used."
fi

# ── Data dir + symlink commands ───────────────────────────────────────────────
mkdir -p "$DATA_DIR"
echo "==> Data directory ready: $DATA_DIR"

# Symlink commands/ into ~/.claude/commands/ so slash commands work globally
CLAUDE_COMMANDS="$HOME/.claude/commands"
mkdir -p "$CLAUDE_COMMANDS"
for cmd_file in "$HOOK_DIR/commands"/*.md; do
    name="$(basename "$cmd_file")"
    target="$CLAUDE_COMMANDS/$name"
    if [[ ! -e "$target" ]]; then
        ln -sf "$cmd_file" "$target"
        echo "    Linked slash command: /$name"
    else
        echo "    Already linked: /$name"
    fi
done

# ── Register hooks in ~/.claude/settings.json ─────────────────────────────────
echo "==> Registering hooks in $SETTINGS..."
"$VENV_DIR/bin/python3" - <<PYEOF
import json
from pathlib import Path

settings_path = Path("$SETTINGS")
venv_python   = "$VENV_DIR/bin/python3"
hook_script   = "$HOOK_SCRIPT"

if settings_path.exists() and settings_path.stat().st_size > 0:
    settings = json.loads(settings_path.read_text())
else:
    settings = {}

hooks = settings.setdefault("hooks", {})

def _register(event: str, args: str = "") -> None:
    cmd = f"{venv_python} {hook_script}" + (f" {args}" if args else "")
    entries = hooks.setdefault(event, [])
    if not any(
        h.get("command") == cmd
        for entry in entries
        for h in entry.get("hooks", [])
    ):
        entries.append({"hooks": [{"type": "command", "command": cmd}]})
        print(f"  Registered: {event}")
    else:
        print(f"  Already registered: {event}")

_register("UserPromptSubmit")
_register("SessionStart", "--session-start")
_register("Stop",         "--stop")

settings_path.write_text(json.dumps(settings, indent=2))
PYEOF

# ── Smoke test daemon startup ─────────────────────────────────────────────────
echo ""
echo "==> Starting daemon smoke test..."
export SWITCHBOARD_DATA="$DATA_DIR"
"$VENV_DIR/bin/python3" "$HOOK_SCRIPT" --serve &
DAEMON_PID=$!
sleep 2

if curl -sf http://localhost:9847/health >/dev/null 2>&1; then
    echo "    Daemon started OK (pid $DAEMON_PID)"
    kill "$DAEMON_PID" 2>/dev/null || true
else
    echo "    Daemon did not respond — check logs (non-fatal, will retry on first prompt)"
    kill "$DAEMON_PID" 2>/dev/null || true
fi

echo ""
echo "==> Done! Switchboard v2 is installed."
echo ""
echo "Available slash commands:"
echo "  /sb-stats      — token savings dashboard (session + lifetime + USD)"
echo "  /sb-lite       — lite brevity mode (filler removal only)"
echo "  /sb-full       — full brevity mode (default, concise fragments)"
echo "  /sb-ultra      — ultra brevity mode (telegraphic, code first)"
echo "  /sb-commit     — conventional commit message for staged diff"
echo "  /sb-review     — one-line per-file PR review with severity emoji"
echo "  /sb-compress   — compress a context file (e.g. CLAUDE.md)"
echo ""
echo "Optional env vars:"
echo "  SWITCHBOARD_ROLLUP_OPTIN=1         — enable opt-in org telemetry"
echo "  SWITCHBOARD_ROLLUP_URL=https://... — org endpoint for daily digest"
echo "  SWITCHBOARD_ENGINEER_EMAIL=...     — anonymised in rollup (hash only)"
echo "  INSTALL_LLMLINGUA=1 ./install.sh   — include neural compressor (~180MB)"
