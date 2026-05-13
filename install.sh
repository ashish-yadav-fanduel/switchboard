#!/usr/bin/env bash
set -e

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$HOOK_DIR/switchboard.py"
VENV_DIR="$HOOK_DIR/venv"
SETTINGS="$HOME/.claude/settings.json"

echo "==> Creating virtual environment..."
python3 -m venv "$VENV_DIR"

echo "==> Installing LLMLingua..."
"$VENV_DIR/bin/pip" install --quiet llmlingua

echo "==> Registering hook in $SETTINGS..."
python3 - <<PYEOF
import json
from pathlib import Path

settings_path = Path("$SETTINGS")
hook_command = "$VENV_DIR/bin/python3 $HOOK_SCRIPT"

if settings_path.exists() and settings_path.stat().st_size > 0:
    settings = json.loads(settings_path.read_text())
else:
    settings = {}

hooks = settings.setdefault("hooks", {})
submit_hooks = hooks.setdefault("UserPromptSubmit", [])

# Idempotent — don't add a duplicate entry
if not any(
    h.get("command") == hook_command
    for entry in submit_hooks
    for h in entry.get("hooks", [])
):
    submit_hooks.append({
        "hooks": [{"type": "command", "command": hook_command}]
    })
    settings_path.write_text(json.dumps(settings, indent=2))
    print("Hook registered.")
else:
    print("Hook already registered — skipped.")
PYEOF

echo ""
echo "Done. Switchboard will compress long prompts automatically in Claude Code."
echo "The LLMLingua daemon starts on your first prompt (one-time ~5s load)."
echo ""
echo "To verify: send any prompt longer than ~600 characters and look for"
echo "  [switchboard] Nx compressed"
echo "in the Claude Code output."
