#!/usr/bin/env python3
"""
Switchboard — local Claude Code prompt compressor.

Hook mode (default):  called by Claude Code on every UserPromptSubmit.
Daemon mode (--serve): persistent process that holds LLMLingua in memory.

The hook starts the daemon on first use and keeps it alive between prompts
so the 180MB model only loads once per session.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOOK_DIR    = Path(os.environ.get(
    "SWITCHBOARD_DATA",
    Path.home() / "Desktop" / "development" / "switchboard",
))
PID_FILE    = HOOK_DIR / "daemon.pid"
STATS_FILE  = HOOK_DIR / "daily_stats.json"
PORT        = 9847
MIN_TOKENS  = 150     # skip compression for short prompts
MIN_RATIO   = 1.3     # don't show advisory if savings are negligible
WAIT_SECS   = 5.0     # max time to wait for daemon to start
REQ_TIMEOUT = 3.0     # max time for a compress request
IDLE_SECS   = 7200    # daemon shuts itself down after 2h idle

# Brevity instruction injected into Claude's context (caveman-style output compression)
BREVITY_CONTEXT = (
    "[brevity mode] Respond concisely. Use fragments where meaning is clear. "
    "Skip filler, hedging phrases, and explanatory padding. "
    "Prefer: [thing] [action] [outcome]. Omit 'please note', 'it is worth', 'basically', 'just'."
)

# ── Daily stats ───────────────────────────────────────────────────────────────

def _load_stats() -> dict:
    from datetime import date
    today = str(date.today())
    try:
        data = json.loads(STATS_FILE.read_text())
        if data.get("date") == today:
            return data
    except Exception:
        pass
    return {"date": today, "tokens_saved": 0, "compressions": 0, "original_tokens": 0}


def _save_stats(stats: dict) -> None:
    try:
        STATS_FILE.write_text(json.dumps(stats))
    except Exception:
        pass


# ── Model routing ─────────────────────────────────────────────────────────────

_complexity_router = None  # lazy-loaded, reused across calls in same process


def _model_hint(text: str, compressed_tokens: int) -> str:
    """
    Uses LiteLLM ComplexityRouter (7-dimension local scoring, no API calls).
    Extended with Claude Code-specific reasoning/technical keywords and
    rebalanced weights so architectural prompts score correctly.
    Falls back to keyword heuristics if litellm is unavailable.
    """
    global _complexity_router
    try:
        import logging
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "1")

        from litellm.router_strategy.complexity_router.complexity_router import (
            ComplexityRouter, ComplexityTier,
        )
        from litellm.router_strategy.complexity_router.config import (
            ComplexityRouterConfig,
            DEFAULT_TECHNICAL_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_CODE_KEYWORDS,
            DEFAULT_SIMPLE_KEYWORDS,
        )
        from litellm._logging import verbose_router_logger
        verbose_router_logger.setLevel(logging.ERROR)

        if _complexity_router is None:
            _complexity_router = ComplexityRouter(
                model_name="dummy",
                litellm_router_instance=None,
                complexity_router_config={
                    "reasoning_keywords": DEFAULT_REASONING_KEYWORDS + [
                        "trade-off", "trade-offs", "trade off", "trade offs",
                        "tradeoff", "tradeoffs",
                        "when should", "best approach", "how should i approach",
                        "how should i", "should i use", "which is better",
                        "what's the difference", "compare", "architect",
                        "design pattern", "best practice", "pros and cons",
                    ],
                    "technical_keywords": DEFAULT_TECHNICAL_KEYWORDS + [
                        "cqrs", "event sourcing", "event-driven", "multi-tenant",
                        "row-level security", "dependency injection", "solid",
                        "domain-driven", "ddd", "hexagonal", "clean architecture",
                        "saga", "outbox", "circuit breaker", "rate limiting",
                        "idempotent", "eventual consistency", "sharding",
                        "consistency model", "cap theorem", "acid", "base",
                    ],
                    "dimension_weights": {
                        "tokenCount":        0.10,
                        "codePresence":      0.20,
                        "reasoningMarkers":  0.30,
                        "technicalTerms":    0.30,
                        "simpleIndicators":  0.05,
                        "multiStepPatterns": 0.03,
                        "questionComplexity":0.02,
                    },
                    "tier_boundaries": {
                        "simple_medium":    0.10,
                        "medium_complex":   0.28,
                        "complex_reasoning":0.55,
                    },
                },
            )

        tier, score, signals = _complexity_router.classify(text)

        label = {
            ComplexityTier.SIMPLE:    f"→ haiku    (score {score:.2f})",
            ComplexityTier.MEDIUM:    f"→ sonnet   (score {score:.2f})",
            ComplexityTier.COMPLEX:   f"→ sonnet   (score {score:.2f})",
            ComplexityTier.REASONING: f"→ opus     (score {score:.2f})",
        }.get(tier, f"→ sonnet (score {score:.2f})")
        return label
    except Exception:
        pass

    # Keyword fallback
    lower = text.lower()
    keyword_map = [
        (["unit test", "pytest", "spec", "mock", "fixture", "assert"],        "→ haiku"),
        (["explain", "summarize", "tldr", "what does", "what is", "describe"],"→ haiku"),
        (["refactor", "rename", "clean up", "add type hints", "lint"],         "→ sonnet"),
        (["architect", "design system", "how should i approach", "trade-off"], "→ opus"),
        (["debug", "why is this", "root cause", "not working", "investigate"],  None),
    ]
    for signals, hint in keyword_map:
        if any(s in lower for s in signals):
            if hint:
                return hint
            return "→ opus" if compressed_tokens > 800 else "→ sonnet"
    return "→ opus" if compressed_tokens > 800 else ""


# ── Daemon communication ──────────────────────────────────────────────────────

def _post(path: str, body: dict | None = None, timeout: float = REQ_TIMEOUT) -> dict | None:
    try:
        data = json.dumps(body or {}).encode() if body else None
        req = urllib.request.Request(
            f"http://localhost:{PORT}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method="POST" if data else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _start_daemon() -> None:
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_for_daemon(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _post("/health", timeout=0.5) is not None:
            return True
        time.sleep(0.3)
    return False


import re as _re

# ── Caveman-style filler patterns (word-level) ────────────────────────────────
_FILLER_RE = _re.compile(
    r'\b('
    r'please note that|it is worth noting that|it should be noted that|'
    r'as you can see|needless to say|'
    r'just|really|basically|sure|actually|honestly|certainly|'
    r'of course|you know|i mean|in other words|that being said|'
    r'at the end of the day|for what it\'s worth|to be honest|'
    r'it\'s important to|feel free to'
    r')\s*',
    _re.IGNORECASE,
)


def _strip_filler(text: str) -> tuple[str, int]:
    """Remove hedging/filler phrases while preserving code blocks.
    Returns (cleaned_text, filler_count)."""
    CODE_RE = _re.compile(r'(```[\s\S]*?```|`[^`\n]+`)', _re.MULTILINE)
    parts = CODE_RE.split(text)
    result = []
    total_removed = 0
    for i, part in enumerate(parts):
        if i % 2 == 1:  # code block — leave untouched
            result.append(part)
            continue
        cleaned, n = _FILLER_RE.subn('', part)
        total_removed += n
        cleaned = _re.sub(r'([.!?])\s+,\s*', r'\1 ', cleaned)
        cleaned = _re.sub(r'(?m)^\s*[,;]\s*', '', cleaned)
        cleaned = _re.sub(r'[ \t]{2,}', ' ', cleaned)
        cleaned = _re.sub(r'(?<=[.!?] )([a-z])', lambda m: m.group(1).upper(), cleaned)
        result.append(cleaned)
    return '\n'.join(p for p in result if p.strip()), total_removed


def _heuristic_compress(text: str, target_ratio: float = 0.5) -> tuple[str, float, int]:
    """
    Two-pass compressor (caveman-inspired):
      1. Word-level: strip filler/hedging phrases
      2. Sentence-level: TF-IDF scoring, drop lowest-information sentences
    Preserves code blocks throughout. Keeps first/last sentence as anchors.
    Returns (compressed_text, actual_ratio, filler_count).
    """
    import math
    import re
    from collections import Counter

    text, filler_count = _strip_filler(text)

    CODE_RE = re.compile(r'(```[\s\S]*?```)', re.MULTILINE)

    # Stash code blocks so they're never scored or dropped
    placeholders: dict[str, str] = {}
    ph_counter = [0]

    def stash(m: re.Match) -> str:
        key = f"\x00BLK{ph_counter[0]}\x00"
        placeholders[key] = m.group(0)
        ph_counter[0] += 1
        return key

    scrubbed = CODE_RE.sub(stash, text)

    # Split into sentences on ./?/! followed by whitespace, or on blank lines
    raw_sentences = re.split(r'(?<=[.!?])\s+|\n{2,}', scrubbed)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    if len(sentences) <= 3:
        return text, 1.0, filler_count

    # TF-IDF scoring
    def tokens(s: str) -> list[str]:
        return re.findall(r'[a-z]+', s.lower())

    tokenized = [tokens(s) for s in sentences]
    doc_freq = Counter(t for toks in tokenized for t in set(toks))
    n = len(sentences)

    def score(toks: list[str]) -> float:
        if not toks:
            return 0.0
        tf = Counter(toks)
        return sum(
            (tf[t] / len(toks)) * math.log((n + 1) / (doc_freq[t] + 1))
            for t in tf
        ) / len(tf)

    scores = [score(t) for t in tokenized]

    # Always keep first + last sentence as context anchors
    must_keep = {0, len(sentences) - 1}

    original_chars = sum(len(s) for s in sentences)
    target_chars = max(int(original_chars * target_ratio), 1)

    # Greedily fill budget in score order (must-keep go first)
    order = sorted(range(len(sentences)),
                   key=lambda i: (0 if i in must_keep else 1, -scores[i]))
    kept: set[int] = set()
    total = 0
    for i in order:
        if total >= target_chars and i not in must_keep:
            break
        kept.add(i)
        total += len(sentences[i])

    compressed_parts = [s for i, s in enumerate(sentences) if i in kept]
    compressed = " ".join(compressed_parts)

    # Restore code blocks
    for key, block in placeholders.items():
        compressed = compressed.replace(key, block)

    actual_ratio = len(text) / max(len(compressed), 1)
    return compressed, round(actual_ratio, 2), filler_count


def _compress(text: str) -> tuple[str, float, str, int]:
    """
    Returns (compressed_text, ratio, source, filler_count).
    Tries LLMLingua daemon first, falls back to heuristic.
    Always succeeds.
    """
    result = _post("/compress", {"text": text, "ratio": 0.5})
    if result:
        return result["compressed"], result["ratio"], "llmlingua", 0

    # Daemon not running — try to start it (for future requests)
    _start_daemon()
    if _wait_for_daemon(WAIT_SECS):
        result = _post("/compress", {"text": text, "ratio": 0.5})
        if result:
            return result["compressed"], result["ratio"], "llmlingua", 0

    compressed, ratio, filler_count = _heuristic_compress(text)
    return compressed, ratio, "heuristic", filler_count


# ── Hook mode ─────────────────────────────────────────────────────────────────

def run_hook() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.stdout.write("{}")
        return

    prompt: str = data.get("prompt", "")
    token_estimate = len(prompt) // 4

    if token_estimate < MIN_TOKENS:
        sys.stdout.write("{}")
        return

    stats = _load_stats()

    compressed, ratio, source, filler_count = _compress(prompt)

    if ratio < MIN_RATIO:
        sys.stdout.write("{}")
        return

    compressed_tokens = max(int(token_estimate / ratio), 1)
    tokens_saved = token_estimate - compressed_tokens
    savings_pct = round(tokens_saved / max(token_estimate, 1) * 100)

    # update and persist daily stats
    stats["tokens_saved"]   += tokens_saved
    stats["compressions"]   += 1
    stats["original_tokens"] += token_estimate
    _save_stats(stats)

    hint = _model_hint(compressed, compressed_tokens)
    advisory = f"[switchboard/{source}] {ratio:.1f}× compressed"
    if hint:
        advisory += f" · {hint}"
    advisory += f"\n{BREVITY_CONTEXT}"

    preview_limit = 400
    preview = compressed[:preview_limit] + ("…" if len(compressed) > preview_limit else "")

    # ── ANSI helpers ──
    BOLD   = "\033[1m"
    GREEN  = "\033[32m"
    CYAN   = "\033[36m"
    YELLOW = "\033[33m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"
    WHITE  = "\033[97m"

    # ── ASCII bar chart (caveman-style) ──
    BAR_W = 10
    def bar(pct: float) -> str:
        filled = round(min(pct, 100) / 100 * BAR_W)
        return "█" * filled + "░" * (BAR_W - filled)

    filler_pct = min(filler_count * 12, 100)
    engine_pct  = 100 if source == "llmlingua" else 55

    daily_total = f"{stats['tokens_saved']:,} [{stats['compressions']}×]"
    rows = [
        ("TOKENS SAVED",   bar(savings_pct),  f"{savings_pct}%  ({daily_total} today)"),
        ("COMPRESSION",    bar(min((ratio-1)/2*100, 100)), f"{ratio:.1f}×"),
        ("FILLER REMOVED", bar(filler_pct),   f"{filler_count} phrases"),
        ("ENGINE",         bar(engine_pct),   source),
    ]
    if hint:
        rows.append(("MODEL HINT", bar(80), hint))

    label_w = max(len(r[0]) for r in rows)
    val_w   = max(len(r[2]) for r in rows)
    inner_w = label_w + 2 + BAR_W + 2 + val_w
    border  = f"{'─' * (inner_w + 2)}"

    chart_lines = [f"{BOLD}{WHITE}┌{border}┐{RESET}"]
    for label, b, val in rows:
        chart_lines.append(
            f"{BOLD}{WHITE}│{RESET} "
            f"{CYAN}{label:<{label_w}}{RESET}  "
            f"{YELLOW}{b}{RESET}  "
            f"{BOLD}{GREEN}{val:<{val_w}}{RESET} "
            f"{BOLD}{WHITE}│{RESET}"
        )
    chart_lines.append(f"{BOLD}{WHITE}└{border}┘{RESET}")

    system_msg = (
        "\n".join(chart_lines)
        + f"\n\n{BOLD}Prompt sent to Claude:{RESET}\n{DIM}{preview}{RESET}"
    )

    sys.stdout.write(json.dumps({
        "userMessage": compressed,
        "additionalContext": advisory,
        "systemMessage": system_msg,
    }))


# ── Daemon mode ───────────────────────────────────────────────────────────────

def run_daemon() -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    from llmlingua import PromptCompressor

    compressor = PromptCompressor(
        model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        use_llmlingua2=True,
        device_map="cpu",
    )

    last_request = [time.monotonic()]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # suppress access log noise

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        def do_POST(self):
            if self.path != "/compress":
                self.send_response(404)
                self.end_headers()
                return

            last_request[0] = time.monotonic()
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text: str = body.get("text", "")
            ratio_target: float = float(body.get("ratio", 0.5))

            try:
                r = compressor.compress_prompt(text, rate=ratio_target, force_tokens=["\n"])
                compressed = r["compressed_prompt"]
                orig   = r.get("origin_tokens",     len(text)       // 4)
                compr  = r.get("compressed_tokens", len(compressed) // 4)
                ratio  = round(orig / max(compr, 1), 2)
            except Exception:
                compressed, ratio = text, 1.0

            payload = json.dumps({"compressed": compressed, "ratio": ratio}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    HOOK_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    def _idle_watcher():
        while True:
            time.sleep(60)
            if time.monotonic() - last_request[0] > IDLE_SECS:
                PID_FILE.unlink(missing_ok=True)
                os._exit(0)

    threading.Thread(target=_idle_watcher, daemon=True).start()

    server = HTTPServer(("localhost", PORT), Handler)
    server.serve_forever()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--serve" in sys.argv:
        run_daemon()
    else:
        run_hook()
