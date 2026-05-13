# Switchboard

Switchboard is a local prompt compressor for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). On each user prompt it can shorten the text you send (via LLMLingua when the daemon is running, or a built-in heuristic fallback), attach brevity instructions, show token savings, and suggest a rough model tier hint based on prompt complexity.

## What it does

- Hook mode (default): reads JSON from stdin (Claude Code `UserPromptSubmit` hook shape), optionally compresses the prompt, and prints JSON with `userMessage`, `additionalContext`, and `systemMessage`.
- Daemon mode (`--serve`): runs a small HTTP server on `localhost:9847` that loads the LLMLingua model once and serves `/health` and `/compress`. The hook starts this process automatically and reuses it across prompts; the daemon exits after two hours of idle time.

Short prompts (under about 150 estimated tokens) and low compression ratios (below about 1.3×) are left unchanged so noise stays low.

The recommended way to run Switchboard is the Claude Code plugin (layout and install below). You can also wire the hook manually to a venv if you prefer.

## Project layout (plugin)

When this repo is installed as a plugin, the checkout root is the plugin root. Layout:

```text
switchboard/
├── .claude-plugin/
│   └── plugin.json          ← plugin manifest (name, version, hooks ref)
├── hooks/
│   └── hooks.json           ← UserPromptSubmit hook using ${CLAUDE_PLUGIN_ROOT}/run.sh
├── run.sh                   ← bootstrap: venv in data dir, pip installs deps
├── requirements.txt         ← litellm>=1.83.0
└── switchboard.py           ← main hook; HOOK_DIR from SWITCHBOARD_DATA
```

| Path | Role |
|------|------|
| `.claude-plugin/plugin.json` | Manifest; points at `hooks/hooks.json` |
| `hooks/hooks.json` | `UserPromptSubmit` command → `${CLAUDE_PLUGIN_ROOT}/run.sh` |
| `run.sh` | Creates venv under the data directory, installs `requirements.txt` when needed, exports `SWITCHBOARD_DATA`, then `exec`’s `switchboard.py` |
| `switchboard.py` | Hook + optional LLMLingua daemon |
| `requirements.txt` | `litellm` for complexity-based model hints |

## Installing as a Claude Code plugin

When the plugin runs, Claude Code provides:

- `${CLAUDE_PLUGIN_ROOT}` — read-only plugin source (this `switchboard` directory).
- `${CLAUDE_PLUGIN_DATA}` — writable per-user directory (virtualenv, `daily_stats.json`, `daemon.pid`).

Behavior:

- On first run, `run.sh` creates a venv under the data directory and `pip install`s from `requirements.txt` (when the venv appears or when `requirements.txt` is newer than a stamp file).
- On later runs it is fast: same venv, `exec` to `python switchboard.py` with `SWITCHBOARD_DATA` set to the data dir.
- If `pip` fails, the hook still works: LiteLLM is only used for model-hint routing; the heuristic compressor does not depend on it.

If `CLAUDE_PLUGIN_DATA` is not set, `run.sh` defaults the data directory to `~/.claude/hooks/switchboard`.

To distribute from GitHub, users add to `~/.claude/settings.json` (replace `your-gh-username` with the real org or user):

```json
{
  "extraKnownMarketplaces": [
    { "source": "github", "repo": "your-gh-username/switchboard" }
  ],
  "enabledPlugins": { "switchboard@switchboard": true }
}
```

Follow Claude Code’s docs for enabling plugins and reloading settings after edits.

## Requirements

- Python 3.10+ (3.14 used in development is fine).
- `litellm` — complexity routing for model hints (in `requirements.txt`; the plugin installs this via `run.sh` into the data-dir venv).
- `llmlingua` — full neural compression in daemon mode (not installed by the plugin bootstrap). If the daemon cannot start, the hook still uses the heuristic compressor (filler stripping + sentence scoring).

For a manual, non-plugin setup, install declared requirements, then add LLMLingua if you want the daemon path:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install llmlingua
```

LLMLingua pulls in PyTorch / Transformers; first model load can take a while and uses significant disk and RAM (~180MB model weights on CPU by default).

## Data directory and `SWITCHBOARD_DATA`

State files (`daemon.pid`, `daily_stats.json`) and the directory the hook treats as “home” come from `SWITCHBOARD_DATA`.

- Plugin: `run.sh` sets `SWITCHBOARD_DATA` to `CLAUDE_PLUGIN_DATA` (or `~/.claude/hooks/switchboard` when that is unset). You normally do not set it yourself.
- Standalone: if `SWITCHBOARD_DATA` is unset, `switchboard.py` falls back to `$HOME/Desktop/development/switchboard`. Override for other layouts:

```bash
export SWITCHBOARD_DATA="$HOME/path/to/writable/dir"
```

Use one writable directory for both the hook process and any manually started `--serve` daemon so PID and stats stay consistent.

## Using with Claude Code

### Plugin (recommended)

Install and enable the plugin via marketplace / `settings.json` as in [Installing as a Claude Code plugin](#installing-as-a-claude-code-plugin). No hand-edited hook command is required.

### Manual hook (no plugin)

1. Clone or copy this repo to a stable path and set `SWITCHBOARD_DATA` to a writable directory if you do not use the default.
2. Create a venv and install dependencies (see [Requirements](#requirements)).
3. Register a `UserPromptSubmit` hook that invokes `switchboard.py` with that environment.

Example `settings.json` hook (adjust paths):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "command": "/absolute/path/to/.venv/bin/python /absolute/path/to/switchboard/switchboard.py"
      }
    ]
  }
}
```

Adjust paths to your venv and `switchboard.py`. After saving hook config, restart Claude Code or reload hooks as documented in your Claude Code version.

On stdin, Switchboard expects JSON with at least a `prompt` string. It may output `{}` (no change) or JSON with `userMessage`, `additionalContext`, and `systemMessage` for the client to apply.

## Running the daemon manually

Usually you do not need to start the daemon yourself; the hook spawns `python switchboard.py --serve` when needed.

To run it manually (debugging or warm-up):

```bash
# Standalone: activate your project venv, then:
source .venv/bin/activate
export SWITCHBOARD_DATA="/path/to/switchboard"   # optional for standalone
python switchboard.py --serve
```

For a plugin install, point `SWITCHBOARD_DATA` at the same directory `run.sh` uses (for example `~/.claude/hooks/switchboard`) and run `switchboard.py` with `$SWITCHBOARD_DATA/venv/bin/python3` so LLMLingua matches the hook’s environment.

Then:

- `GET http://localhost:9847/health` → should return `ok`.
- `POST http://localhost:9847/compress` with JSON `{"text": "...", "ratio": 0.5}` → JSON `compressed` and `ratio`.

The daemon listens only on localhost port 9847.

## Offline / Hugging Face

The daemon sets `TRANSFORMERS_OFFLINE` and `HF_HUB_OFFLINE` to `1` by default so it prefers local weights. Ensure the LLMLingua model is available locally if you work fully offline (see Transformers / Hugging Face cache documentation).

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| No compression, only heuristic | Daemon not running or LLMLingua import failed; check `python switchboard.py --serve` in a terminal for errors. |
| Hook seems no-op | Prompt may be under the token threshold or ratio under `MIN_RATIO`; see constants at top of `switchboard.py`. |
| Wrong stats / PID path | Plugin: files live under `CLAUDE_PLUGIN_DATA` (default `~/.claude/hooks/switchboard`). Standalone: set `SWITCHBOARD_DATA` to one writable directory shared by hook and daemon. |
| Port conflict | Another process using 9847; change `PORT` in `switchboard.py` if you must (keep hook and daemon in sync). |
