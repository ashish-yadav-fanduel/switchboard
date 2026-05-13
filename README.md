# Switchboard

Switchboard is a local prompt compressor for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). On each user prompt it can shorten the text you send (via LLMLingua when the daemon is running, or a built-in heuristic fallback), attach brevity instructions, show token savings, and suggest a rough model tier hint based on prompt complexity.

## What it does

- Hook mode (default): reads JSON from stdin (Claude Code `UserPromptSubmit` hook shape), optionally compresses the prompt, and prints JSON with `userMessage`, `additionalContext`, and `systemMessage`.
- Daemon mode (`--serve`): runs a small HTTP server on `localhost:9847` that loads the LLMLingua model once and serves `/health` and `/compress`. The hook starts this process automatically and reuses it across prompts; the daemon exits after two hours of idle time.

Short prompts (under about 150 estimated tokens) and low compression ratios (below about 1.3×) are left unchanged so noise stays low.

## Requirements

- Python 3.10+ (3.14 used in development is fine).
- `litellm` — complexity routing for model hints (in `requirements.txt`).
- `llmlingua` — full neural compression in daemon mode. If the daemon cannot start, the hook still uses the heuristic compressor (filler stripping + sentence scoring).

Install the declared requirements, then add LLMLingua for full compression:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install llmlingua
```

LLMLingua pulls in PyTorch / Transformers; first model load can take a while and uses significant disk and RAM (~180MB model weights on CPU by default).

## Project layout

| Path | Role |
|------|------|
| `switchboard.py` | Hook entrypoint and daemon server |
| `requirements.txt` | Minimal pinned deps (`litellm`) |
| `daemon.pid` | Written when the daemon is running (gitignored) |
| `daily_stats.json` | Rolling same-day stats for the dashboard (gitignored) |

## Data directory and `SWITCHBOARD_DATA`

State files (`daemon.pid`, `daily_stats.json`) and the default “home” for the tool live under `SWITCHBOARD_DATA`.

If unset, the code defaults to:

`$HOME/Desktop/development/switchboard`

On another machine or path, set the variable so hooks and daemon agree:

```bash
export SWITCHBOARD_DATA="$HOME/path/to/switchboard"
```

Use the same directory for the script location you invoke from Claude Code and for this env var.

## Using with Claude Code

1. Clone or copy this repo to a stable path (or set `SWITCHBOARD_DATA` to that path).
2. Install dependencies (see above).
3. Wire a `UserPromptSubmit` hook so Claude Code runs Switchboard on every prompt and merges its output.

Point the hook at your interpreter and script, for example:

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
source .venv/bin/activate
export SWITCHBOARD_DATA="/path/to/switchboard"   # optional
python switchboard.py --serve
```

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
| Wrong stats / PID path | Set `SWITCHBOARD_DATA` explicitly to the repo directory you use for hooks. |
| Port conflict | Another process using 9847; change `PORT` in `switchboard.py` if you must (keep hook and daemon in sync). |
