#!/usr/bin/env python3
"""
Switchboard v2 — Claude Code adapter.

Hook mode (default):  called by Claude Code on every UserPromptSubmit / SessionStart / Stop.
Daemon mode (--serve): persistent process that holds all state and compression logic.

The hook starts the daemon on first use and communicates via HTTP on localhost:PORT.
All compression, classification, stats, and brevity logic lives in the daemon/ package.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HOOK_DIR    = Path(os.environ.get(
    "SWITCHBOARD_DATA",
    Path.home() / ".claude" / "hooks" / "switchboard",
))
PID_FILE    = HOOK_DIR / "daemon.pid"
PORT        = int(os.environ.get("SWITCHBOARD_PORT", 9847))

MIN_TOKENS  = 10    # skip very short prompts
MIN_RATIO   = 1.05  # skip if compression savings are negligible
WAIT_SECS   = 8.0   # daemon starts in <1s without llmlingua; allow headroom
REQ_TIMEOUT = 4.0


# ── Daemon communication ──────────────────────────────────────────────────────

def _call(path: str, body: dict | None = None, timeout: float = REQ_TIMEOUT) -> dict | None:
    try:
        data = json.dumps(body).encode() if body is not None else None
        req  = urllib.request.Request(
            f"http://localhost:{PORT}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _ensure_daemon() -> bool:
    if _call("/health", timeout=0.5) is not None:
        return True
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "SWITCHBOARD_DATA": str(HOOK_DIR)},
    )
    deadline = time.monotonic() + WAIT_SECS
    while time.monotonic() < deadline:
        if _call("/health", timeout=0.5) is not None:
            return True
        time.sleep(0.25)
    return False


# ── Local fallbacks (when daemon unavailable) ─────────────────────────────────

def _local_compress(text: str) -> tuple[str, float, str, int]:
    """Pure-local heuristic compression — no daemon required."""
    sys.path.insert(0, str(Path(__file__).parent))
    from daemon.compress import heuristic_compress
    compressed, ratio, filler_count = heuristic_compress(text)
    return compressed, ratio, "heuristic", filler_count


def _local_brevity_text() -> str:
    try:
        from daemon.brevity import get_text, DEFAULT_MODE
        return get_text(DEFAULT_MODE)
    except Exception:
        return (
            "[brevity mode] Respond concisely. Skip filler and hedging. "
            "Prefer [thing] [action] [outcome]."
        )


# ── Session ID ────────────────────────────────────────────────────────────────

def _session_id() -> str:
    """Date-scoped session ID — one session per local calendar day."""
    from datetime import date
    return str(date.today())


def _macos_notify(hint: str, ratio: float, savings_pct: int, daily_total: str) -> None:
    """Fire a macOS notification. Uses osascript; falls back to terminal-notifier if available."""
    import platform

    def _ascii(s: str) -> str:
        return s.encode("ascii", "ignore").decode()

    subtitle = _ascii(hint[:50])
    body_msg  = _ascii(f"{ratio:.1f}x · {savings_pct}% saved · {daily_total} today")

    try:
        ver = platform.mac_ver()[0]
        major = int(ver.split(".")[0]) if ver else 0
        _debug_log(f"notify: macOS={ver} major={major}")
    except Exception as e:
        _debug_log(f"notify: ver_check_err={e}")
        major = 0

    # Try osascript first (broken on some macOS 26 builds but worth trying)
    try:
        result = subprocess.run(
            ["osascript", "-e",
             f'display notification "{body_msg}" with title "Switchboard" subtitle "{subtitle}"'],
            timeout=2, check=False, capture_output=True, text=True,
        )
        _debug_log(f"notify: osascript rc={result.returncode} err={result.stderr.strip()!r}")
        if result.returncode == 0:
            return
    except Exception as e:
        _debug_log(f"notify: osascript_exc={e}")

    # Fallback: terminal-notifier (brew install terminal-notifier)
    try:
        result = subprocess.run(
            ["terminal-notifier", "-title", "Switchboard", "-subtitle", subtitle,
             "-message", body_msg, "-sound", "default"],
            timeout=2, check=False, capture_output=True, text=True,
        )
        _debug_log(f"notify: terminal-notifier rc={result.returncode}")
    except FileNotFoundError:
        _debug_log("notify: terminal-notifier not found — brew install terminal-notifier")
    except Exception as e:
        _debug_log(f"notify: terminal-notifier_exc={e}")


# ── Hook: UserPromptSubmit ────────────────────────────────────────────────────

def _debug_log(msg: str) -> None:
    try:
        log = HOOK_DIR / "hook_invoke.log"
        with open(log, "a") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def run_hook() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.stdout.write("{}")
        return

    prompt: str        = data.get("prompt", "")
    is_plan: bool      = data.get("permission_mode") == "plan"
    is_terminal: bool  = bool(os.environ.get("TERM_PROGRAM"))
    token_estimate     = len(prompt) // 4
    session_id         = _session_id()

    _debug_log(
        f"invoked tokens={token_estimate} terminal={is_terminal} plan={is_plan} "
        f"TERM={os.environ.get('TERM','?')} TERM_PROGRAM={os.environ.get('TERM_PROGRAM','?')}"
    )

    if token_estimate < MIN_TOKENS:
        sys.stdout.write("{}")
        return

    # ── Compression ────────────────────────────────────────────────────────────
    daemon_ok = _ensure_daemon()
    _debug_log(f"daemon_ok={daemon_ok}")

    if daemon_ok:
        result = _call("/compress", {"text": prompt, "ratio": 0.5})
    else:
        result = None

    if result:
        compressed    = result["compressed"]
        ratio         = result["ratio"]
        source        = result["source"]
        filler_count  = result.get("filler_count", 0)
    else:
        compressed, ratio, source, filler_count = _local_compress(prompt)

    _debug_log(f"ratio={ratio:.2f} source={source}")
    if ratio < MIN_RATIO:
        _debug_log("skipped: ratio below threshold")
        sys.stdout.write("{}")
        return

    compressed_tokens = max(int(token_estimate / ratio), 1)
    tokens_saved      = token_estimate - compressed_tokens
    savings_pct       = round(tokens_saved / max(token_estimate, 1) * 100)

    # ── Classification + model nudge ───────────────────────────────────────────
    hint_label  = ""
    tier        = "MEDIUM"
    recommended = ""
    if daemon_ok:
        cls = _call("/classify", {"text": compressed, "tokens": compressed_tokens})
        if cls:
            tier        = cls.get("tier", "MEDIUM")
            hint_label  = cls.get("hint_label", "")   # non-empty only above $0.005 threshold
            recommended = cls.get("recommended", "")

    # ── USD savings on input compression ──────────────────────────────────────
    try:
        from daemon.pricing import usd_for_tokens
        usd_saved = usd_for_tokens(tokens_saved)
    except Exception:
        usd_saved = 0.0

    # ── Brevity mode ───────────────────────────────────────────────────────────
    if daemon_ok:
        brev = _call("/brevity", timeout=1.0)
        brevity_text = brev.get("text", _local_brevity_text()) if brev else _local_brevity_text()
        brevity_mode = brev.get("mode", "full") if brev else "full"
    else:
        brevity_text = _local_brevity_text()
        brevity_mode = "full"

    # ── Persist event ──────────────────────────────────────────────────────────
    if daemon_ok:
        _call("/event", {
            "session_id":   session_id,
            "event_type":   "compress",
            "tokens_in":    token_estimate,
            "tokens_saved": tokens_saved,
            "ratio":        ratio,
            "source":       source,
            "tier":         tier,
            "model_hint":   hint_label[:80],
            "usd_saved":    usd_saved,
            "brevity_mode": brevity_mode,
        })

    # ── Load stats for display ─────────────────────────────────────────────────
    daily_usd = 0.0
    if daemon_ok:
        stats_data = _call("/stats", timeout=1.0)
        if stats_data:
            daily_saved = stats_data["session"]["tokens_saved"]
            daily_count = stats_data["session"]["compressions"]
            daily_usd   = stats_data["session"].get("usd_saved", 0.0)
            daily_total = f"{daily_saved:,} [{daily_count}×]"
        else:
            daily_total = f"{tokens_saved:,} [1×]"
            daily_usd   = usd_saved
    else:
        daily_total = f"{tokens_saved:,} [1×]"
        daily_usd   = usd_saved

    # ── Desktop macOS notification ─────────────────────────────────────────────
    if not is_terminal:
        _macos_notify(hint_label or source, ratio, savings_pct, daily_total)

    # ── Terminal / desktop stderr output ───────────────────────────────────────
    preview = compressed[:400] + ("…" if len(compressed) > 400 else "")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from daemon.dashboard import render_hook_stats
        sys.stderr.write(render_hook_stats(
            ratio, savings_pct, filler_count, source,
            daily_total, hint_label, preview,
        ))
    except Exception:
        pass

    # ── Hook output ────────────────────────────────────────────────────────────
    # Plain-text stats — no markdown tables, renders cleanly in terminal
    _TIER_EMOJI = {"SIMPLE": "🟢", "MEDIUM": "🟡", "COMPLEX": "🟠", "REASONING": "🔴"}
    tier_line = f"{_TIER_EMOJI.get(tier, '⚪')} {tier}"
    if recommended:
        short_model = recommended.replace("claude-", "").replace("-2024", "")
        tier_line += f"  →  {short_model}"
    rows = [
        ("Tokens saved",   f"{savings_pct}%  ({daily_total} today)"),
        ("Compression",    f"{ratio:.1f}×"),
        ("Filler removed", f"{filler_count} phrases"),
        ("Engine",         source),
        ("USD saved",      f"${usd_saved:.4f}  (${daily_usd:.4f} today)"),
        ("Intent",         tier_line),
    ]
    if hint_label:
        rows.append(("💡 Nudge", hint_label))

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from daemon.tips import get_tip
        tip = get_tip(tier, seed=session_id)
    except Exception:
        tip = ""

    col_w = max(len(r[0]) for r in rows)
    stats_lines = "\n".join(f"  {label:<{col_w}}  {val}" for label, val in rows)
    preview_txt = compressed[:300] + ("..." if len(compressed) > 300 else "")
    system_msg = (
        f"⚡ Switchboard v2  |  {source}  |  {ratio:.1f}x compressed\n"
        f"{'─' * 48}\n"
        + stats_lines
        + f"\n{'─' * 48}\n"
        f"Prompt: {preview_txt}"
        + (f"\n{'─' * 48}\n💬 Tip: {tip}" if tip else "")
    )

    user_msg_final = brevity_text + f"\n\n{compressed}"

    sys.stdout.write(json.dumps({
        "userMessage":   user_msg_final,
        "systemMessage": system_msg,
    }))


# ── Hook: SessionStart ────────────────────────────────────────────────────────

def run_session_start() -> None:
    session_id = _session_id()
    if _ensure_daemon():
        _call("/session", {"action": "start", "session_id": session_id})
        # Trigger opt-in daily rollup via daemon (daemon owns storage init)
        _call("/rollup", timeout=6.0)
    sys.stdout.write("{}")


# ── Hook: Stop ────────────────────────────────────────────────────────────────

def run_stop() -> None:
    if _call("/health", timeout=0.5):
        _call("/session", {"action": "end", "session_id": _session_id()})
    sys.stdout.write("{}")


# ── Daemon mode ───────────────────────────────────────────────────────────────

def run_daemon() -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from daemon.server import serve
    serve(HOOK_DIR)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = set(sys.argv[1:])
    if "--serve" in args:
        run_daemon()
    elif "--session-start" in args:
        run_session_start()
    elif "--stop" in args:
        run_stop()
    else:
        run_hook()
