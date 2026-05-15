# Switchboard v2

Switchboard is a local productivity plugin for Claude Code that compresses every prompt before it reaches the model, tracks token and USD savings, enforces output brevity, and nudges you toward the right model for each task — all without any prompt text leaving the machine.

---

## What it does

| Feature | How |
|---------|-----|
| **Input compression** | Two-pass: substitution rules (`utilize→use`, `in order to→to`) + filler phrase removal + TF-IDF sentence scoring |
| **Output brevity modes** | `/sb-lite` / `/sb-full` / `/sb-ultra` inject a brevity instruction into every prompt |
| **Model nudge** | Classifies intent (SIMPLE/MEDIUM/COMPLEX/REASONING) and shows the recommended model + estimated USD savings |
| **Per-prompt tips** | Rotating prompt-efficiency tips by intent tier, one per response |
| **Token + USD dashboard** | Tracks session and lifetime savings, shown on every prompt |
| **macOS notifications** | Desktop app fires a system notification after every compressed prompt |
| **Universal GenAI proxy** | Drop-in OpenAI-compatible + Anthropic-compatible local proxy — any SDK, one-line change |
| **Opt-in org rollup** | Daily HMAC-signed digest of counts + USD (no prompt text) → your org's analytics endpoint |

---

## Quick start (Claude Code plugin)

Add to `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "switchboard": {
      "source": { "source": "github", "repo": "ashish-yadav-fanduel/switchboard" }
    }
  },
  "enabledPlugins": { "switchboard@switchboard": true }
}
```

Reload Claude Code. On first use, `run.sh` auto-creates a venv under `~/.claude/hooks/switchboard`, installs deps, and starts the background daemon.

### Manual install

```bash
git clone https://github.com/ashish-yadav-fanduel/switchboard
cd switchboard
./install.sh

# Optional: LLMLingua neural compressor (~180MB, PyTorch, higher compression ratio)
INSTALL_LLMLINGUA=1 ./install.sh
```

`install.sh` registers all three hooks (`UserPromptSubmit`, `SessionStart`, `Stop`), symlinks slash commands into `~/.claude/commands/`, and runs a daemon smoke test.

---

## What you see on every prompt

### Terminal (Claude Code CLI)

A plain-text stats block appears after every compressed prompt as a hook output block:

```
⚡ Switchboard v2  |  heuristic  |  1.4x compressed
────────────────────────────────────────────────
  Tokens saved    28%  (1,200 [5×] today)
  Compression     1.4×
  Filler removed  6 phrases
  Engine          heuristic
  USD saved       $0.0012  ($0.0048 today)
  Intent          🟢 SIMPLE  →  haiku-4-5
────────────────────────────────────────────────
Prompt: <compressed preview>
────────────────────────────────────────────────
💬 Tip: SIMPLE tasks don't need Sonnet. Haiku handles explain/summarize at the same quality.
```

### Desktop app (Claude Code macOS)

A macOS system notification fires after every compressed prompt:

```
Switchboard
heuristic
1.4x · 28% saved · 1,200 [5×] today
```

For macOS 26 Tahoe (Darwin 25+), `osascript` is broken system-wide. Install `terminal-notifier` as a fallback:

```bash
brew install terminal-notifier
```

Switchboard automatically detects which method works and falls back to `terminal-notifier` if `osascript` fails. See **Troubleshooting** if notifications don't appear.

---

## How compression works

Every prompt goes through two passes before reaching Claude:

**Pass 1 — Word-level substitutions + filler removal**

Substitution rules applied first:

| Verbose | Replaced with |
|---------|--------------|
| `in order to` | `to` |
| `the reason is because` | `because` |
| `make sure to` | `ensure` |
| `utilize` | `use` |
| `implement a solution for` | `fix` |
| `take into consideration` | `consider` |
| `due to the fact that` | `because` |
| `at this point in time` | `now` |
| `in the event that` | `if` |
| `with regard to` | `regarding` |

Then ~40 filler/hedging patterns are stripped: `please note that`, `basically`, `honestly`, `i think`, `however`, `furthermore`, `feel free to`, `could you please`, `it goes without saying`, etc. Code blocks (```` ``` ```` and `` ` ``) are never touched.

**Pass 2 — TF-IDF sentence scoring**

Sentences are scored by information density (TF-IDF). Low-scoring sentences are dropped until the target ratio is met. The first and last sentences are always kept as anchors.

**Skip conditions:** prompt under ~40 tokens, or compression ratio below 1.05 (savings negligible).

---

## Slash commands

| Command | What it does |
|---------|--------------|
| `/sb-stats` | Full token savings dashboard — session, lifetime, USD, streak |
| `/sb-lite` | Brevity mode: strip filler only, keep full sentences |
| `/sb-full` | Brevity mode: concise, no hedging (default) |
| `/sb-ultra` | Brevity mode: telegraphic — code first, ≤2 sentence explanations, no prose |
| `/sb-commit` | Conventional commit message (≤50 chars) from staged diff |
| `/sb-review` | One-line per-file PR review with severity emoji (🔴🟡🟢💡) |
| `/sb-compress [file]` | Compress a context file (e.g. `CLAUDE.md`) — shows before/after, asks before writing |

**Brevity mode persists for the session.** Set `/sb-ultra` once and every subsequent response in that session is telegraphic.

---

## Model nudge

On every prompt, intent is classified into one of four tiers using LiteLLM's `ComplexityRouter` (local scoring, no API calls):

| Tier | Emoji | Recommended model | Triggers |
|------|-------|------------------|---------|
| SIMPLE | 🟢 | `claude-haiku-4-5` | explain, summarize, what is, unit test |
| MEDIUM | 🟡 | `claude-sonnet-4-6` | debug, fix, refactor, rename |
| COMPLEX | 🟠 | `claude-sonnet-4-6` | multi-file implementation |
| REASONING | 🔴 | `claude-opus-4-7` | architect, design pattern, trade-off, CQRS |

When the recommended model differs from your current model **and** estimated savings exceed $0.005, a nudge line appears in the stats block:

```
💡 Nudge    SIMPLE task — Haiku would save ~$0.014 (set /model claude-haiku-4-5)
```

No interception. You decide whether to switch.

---

## Per-prompt tips

Each response includes a rotating tip matched to the detected intent tier. Tips change every hour (stable within a session). Examples:

- **SIMPLE:** "SIMPLE tasks don't need Sonnet. Haiku handles explain/summarize at the same quality."
- **MEDIUM:** "Paste the full stack trace, not just the last line. Claude needs the root frame to avoid guessing."
- **COMPLEX:** "Multi-file changes: list the files you want touched. Unlisted files rarely need changing."
- **REASONING:** "Reasoning tasks are where Opus pays for itself. Consider: /model claude-opus-4-7"

---

## Universal GenAI proxy

The daemon doubles as a drop-in OpenAI-compatible + Anthropic-compatible local proxy. Any tool that uses either SDK compresses its prompts **transparently** with a one-line change.

### Start the daemon

```bash
python3 switchboard.py --serve &
```

### Python — OpenAI SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:9847/v1", api_key="YOUR_KEY")
resp = client.chat.completions.create(
    model="claude-haiku-4-5",
    messages=[{"role": "user", "content": "explain what a for loop does"}],
)
print(resp.choices[0].message.content)
```

### Python — Anthropic SDK

```python
import anthropic, os
client = anthropic.Anthropic(
    base_url="http://localhost:9847",
    api_key=os.environ["ANTHROPIC_API_KEY"],
)
msg = client.messages.create(
    model="claude-haiku-4-5", max_tokens=200,
    messages=[{"role": "user", "content": "explain what a for loop does"}],
)
print(msg.content)
```

### LangChain

```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    openai_api_base="http://localhost:9847/v1",
    openai_api_key="YOUR_KEY",
    model_name="claude-haiku-4-5",
)
print(llm.invoke("explain what a for loop does"))
```

### Node.js

```javascript
import OpenAI from "openai";
const openai = new OpenAI({ baseURL: "http://localhost:9847/v1", apiKey: "YOUR_KEY" });
const resp = await openai.chat.completions.create({
  model: "claude-haiku-4-5",
  messages: [{ role: "user", content: "explain what a for loop does" }],
});
console.log(resp.choices[0].message.content);
```

### curl

```bash
curl http://localhost:9847/v1/chat/completions \
  -H "Authorization: Bearer $ANTHROPIC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5","messages":[{"role":"user","content":"explain what a for loop does"}]}'
```

Proxy savings are logged to SQLite automatically and included in `/sb-stats`.

---

## Org rollup (opt-in)

Switchboard can send a **daily HMAC-signed digest** to your org's analytics endpoint. Prompt text never leaves the machine — only aggregate counts and USD totals.

```bash
export SWITCHBOARD_ROLLUP_OPTIN=1
export SWITCHBOARD_ROLLUP_URL=https://your-org-endpoint/switchboard
export SWITCHBOARD_ENGINEER_EMAIL=you@fanduel.com   # hashed, never sent plaintext
export SWITCHBOARD_ROLLUP_SECRET=your-org-hmac-secret
```

Payload sent once per day on `SessionStart`:

```json
{
  "version": "2",
  "engineer_id": "a3f7b2c1d4e5f6a7",
  "date": "2026-05-15",
  "tokens_in": 12400,
  "tokens_saved": 5820,
  "usd_saved": 0.0873,
  "compressions": 28,
  "by_model": { "claude-haiku-4-5": 0.002, "claude-sonnet-4-6": 0.085 },
  "sig": "sha256-hmac"
}
```

`engineer_id` is `sha256(email + org_salt)[:16]` — joinable in Looker/Datadog for team leaderboards without storing PII.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Adapters (thin, per-IDE)                           │
│    • Claude Code hook (UserPromptSubmit)  [v2 ✓]   │
│    • Claude Code slash commands           [v2 ✓]   │
│    • Universal GenAI proxy (OpenAI+Anthropic) [v2 ✓]│
│    • MCP tool-description shrinker        [planned] │
│    • Cursor extension                     [v3]      │
│    • ChatGPT browser extension            [v4]      │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP localhost:9847
┌──────────────────▼──────────────────────────────────┐
│  Switchboard daemon (one Python process)            │
│    /compress  /classify  /brevity                   │
│    /stats     /event     /session    /rollup        │
│    /v1/chat/completions  /v1/messages               │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────▼───────────┐
       │  SQLite state.db      │
       │  events · sessions    │
       │  config · pricing     │
       └───────────────────────┘
```

The daemon is the single source of truth for stats, brevity mode, and rollup. Future IDE adapters (Cursor, ChatGPT extension) call the same HTTP API — no changes to the daemon required.

---

## Daemon HTTP API

All running on `localhost:9847`:

| Route | Method | Purpose |
|-------|--------|---------|
| `/health` | GET | `{"status":"ok","version":"2.0"}` |
| `/compress` | POST | `{text, ratio}` → `{compressed, ratio, source, filler_count}` |
| `/classify` | POST | `{text, tokens}` → `{tier, score, recommended, usd_delta, hint_label}` |
| `/brevity` | GET | Current session brevity mode + injected text |
| `/brevity` | POST | `{mode}` → set mode (`lite`/`full`/`ultra`) |
| `/stats` | GET | Full stats dict (session, lifetime, streak, top tiers) |
| `/event` | POST | Log a compression/classify event to SQLite |
| `/session` | POST | `{action, session_id}` — mark session start/end |
| `/rollup` | GET | Produce + optionally POST today's signed digest |
| `/v1/chat/completions` | POST | OpenAI-compatible proxy (compress → forward → log) |
| `/v1/messages` | POST | Anthropic-compatible proxy |
| `/v1/models` | GET | Returns supported model list (OpenAI SDK validation) |

CORS headers (`Access-Control-Allow-Origin: *`) are included on every response, enabling browser extension and Cursor callers.

---

## Project layout

```
switchboard/
├── .claude-plugin/
│   ├── plugin.json          ← manifest: hooks, commands dir
│   └── marketplace.json     ← GitHub marketplace metadata (v2.0.0)
├── hooks/
│   └── hooks.json           ← UserPromptSubmit + SessionStart + Stop
├── commands/
│   ├── sb-stats.md
│   ├── sb-lite.md
│   ├── sb-full.md
│   ├── sb-ultra.md
│   ├── sb-commit.md
│   ├── sb-review.md
│   └── sb-compress.md
├── daemon/
│   ├── server.py            ← HTTP daemon + CORS + proxy routes
│   ├── compress.py          ← heuristic compressor (substitutions + filler + TF-IDF)
│   ├── classify.py          ← intent tier + USD delta
│   ├── brevity.py           ← lite / full / ultra mode texts
│   ├── tips.py              ← rotating per-tier prompt efficiency tips
│   ├── dashboard.py         ← terminal hook stats renderer
│   ├── pricing.py           ← model cost table (Opus/Sonnet/Haiku)
│   ├── proxy.py             ← OpenAI + Anthropic proxy logic
│   ├── rollup.py            ← HMAC daily digest
│   └── storage.py           ← SQLite: events, sessions, config
├── switchboard.py           ← thin Claude Code adapter (hook + daemon launcher)
├── run.sh                   ← plugin bootstrap (venv, pip, exec)
├── install.sh               ← manual installer (Python 3.10+ guard)
└── requirements.txt         ← litellm>=1.83.0,<2.0.0  rich>=13.0.0,<14.0.0
```

---

## Requirements

- **Python 3.10+**
- `litellm >= 1.83.0` — intent classification (local scoring, no API calls)
- `rich >= 13.0.0` — terminal rendering (falls back to plain text if absent)
- `llmlingua` — optional neural compressor (~180MB, PyTorch). Install with `INSTALL_LLMLINGUA=1 ./install.sh`
- `terminal-notifier` — optional macOS notification fallback for Tahoe (`brew install terminal-notifier`)

---

## Env vars reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `SWITCHBOARD_DATA` | `~/.claude/hooks/switchboard` | SQLite, pid file, venv |
| `SWITCHBOARD_PORT` | `9847` | Daemon HTTP port |
| `SWITCHBOARD_CURRENT_MODEL` | `claude-opus-4-7` | Used for USD delta in nudge |
| `SWITCHBOARD_ROLLUP_OPTIN` | `0` | Set to `1` to enable daily rollup POST |
| `SWITCHBOARD_ROLLUP_URL` | — | Org endpoint for daily digest |
| `SWITCHBOARD_ROLLUP_SECRET` | internal default | HMAC key for rollup signing |
| `SWITCHBOARD_ENGINEER_EMAIL` | `$USER` | Hashed for anonymous engineer_id |
| `SWITCHBOARD_ORG_SALT` | `switchboard-fanduel-v2` | Extra salt for engineer_id hash |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No compression output | Prompt under ~40 tokens or ratio < 1.05 — intentional no-ops |
| No stats block in terminal | Hook not registered — run `./install.sh` or check `~/.claude/settings.json` for a `UserPromptSubmit` entry |
| No macOS notification (desktop app) | Run `brew install terminal-notifier`; then check `~/.claude/hooks/switchboard/hook_invoke.log` for `notify:` lines |
| Notifications blocked on macOS 26 Tahoe | `osascript` is broken system-wide on Tahoe — `terminal-notifier` is the fix |
| `/sb-stats` shows zeros | Send at least one prompt to warm the daemon first |
| Port conflict | Change `SWITCHBOARD_PORT` in env (keep hook and daemon in sync) |
| Stale brevity mode | Run `/sb-full` to reset to default |
| Daemon won't start | Run `python3 switchboard.py --serve` in terminal; check for Python < 3.10 |
| Double compression | Check `~/.claude/settings.json` for a legacy manual hook pointing at `switchboard.py` directly — remove it |
| No slash commands | Re-run `./install.sh` to symlink `commands/` into `~/.claude/commands/` |

### Checking the debug log

Every hook invocation writes to `~/.claude/hooks/switchboard/hook_invoke.log`:

```
invoked tokens=112 terminal=False plan=False TERM=? TERM_PROGRAM=?
daemon_ok=True
ratio=1.39 source=heuristic
notify: macOS=15.4.0 major=15
notify: osascript rc=0
```

If `daemon_ok=False`, the daemon failed to start (check Python version and `litellm` install).  
If `skipped: ratio below threshold`, the prompt was already concise — no compression needed.  
If `notify: terminal-notifier not found`, run `brew install terminal-notifier`.

---

## Multi-IDE roadmap

- **v3 — Cursor:** VS Code extension hooks `onWillSendMessage`, calls `localhost:9847/compress` + `/classify`, injects brevity preamble. Same daemon, same dashboard.
- **v4 — ChatGPT:** Browser extension intercepts the compose box. No daemon changes required — the HTTP API is IDE-agnostic.
