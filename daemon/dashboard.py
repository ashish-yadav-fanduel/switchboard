"""
Terminal dashboard using Rich (falls back to plain text when Rich is absent).
Called by /sb-stats command and by the hook's stderr output.
"""

from __future__ import annotations

import os


def _is_terminal() -> bool:
    return bool(os.environ.get("TERM_PROGRAM"))


def render_hook_stats(
    ratio: float,
    savings_pct: int,
    filler_count: int,
    source: str,
    daily_total: str,
    hint_label: str,
    preview: str,
) -> str:
    """Return a string suitable for hook stderr output (ANSI or plain)."""
    if _is_terminal():
        return _ansi_hook(ratio, savings_pct, filler_count, source, daily_total, hint_label, preview)
    return _plain_hook(ratio, savings_pct, filler_count, source, daily_total, hint_label, preview)


def render_full_dashboard(stats: dict) -> str:
    """Render the full /sb-stats dashboard."""
    try:
        return _rich_dashboard(stats)
    except ImportError:
        return _plain_dashboard(stats)


# ── ANSI hook output ──────────────────────────────────────────────────────────

def _ansi_hook(
    ratio: float, savings_pct: int, filler_count: int, source: str,
    daily_total: str, hint_label: str, preview: str,
) -> str:
    BOLD = "\033[1m"; GREEN = "\033[32m"; CYAN = "\033[36m"
    YELLOW = "\033[33m"; DIM = "\033[2m"; RESET = "\033[0m"; WHITE = "\033[97m"
    BAR_W = 10

    def bar(pct: float) -> str:
        filled = round(min(pct, 100) / 100 * BAR_W)
        return "█" * filled + "░" * (BAR_W - filled)

    rows = [
        ("TOKENS SAVED",   bar(savings_pct),                  f"{savings_pct}%  ({daily_total} today)"),
        ("COMPRESSION",    bar(min((ratio - 1) / 2 * 100, 100)), f"{ratio:.1f}×"),
        ("FILLER REMOVED", bar(min(filler_count * 12, 100)),  f"{filler_count} phrases"),
        ("ENGINE",         bar(100 if source == "llmlingua" else 55), source),
    ]
    if hint_label:
        rows.append(("MODEL NUDGE", bar(70), hint_label[:60]))

    label_w = max(len(r[0]) for r in rows)
    val_w   = max(len(r[2]) for r in rows)
    border  = "─" * (label_w + 2 + BAR_W + 2 + val_w + 2)

    lines = [f"{BOLD}{WHITE}┌{border}┐{RESET}"]
    for label, b, val in rows:
        lines.append(
            f"{BOLD}{WHITE}│{RESET} "
            f"{CYAN}{label:<{label_w}}{RESET}  "
            f"{YELLOW}{b}{RESET}  "
            f"{BOLD}{GREEN}{val:<{val_w}}{RESET} "
            f"{BOLD}{WHITE}│{RESET}"
        )
    lines.append(f"{BOLD}{WHITE}└{border}┘{RESET}")
    lines.append(f"\n{BOLD}Prompt sent to Claude:{RESET}\n{DIM}{preview}{RESET}")
    return "\n".join(lines) + "\n"


def _plain_hook(
    ratio: float, savings_pct: int, filler_count: int, source: str,
    daily_total: str, hint_label: str, preview: str,
) -> str:
    lines = [
        f"Switchboard · {source} · {ratio:.1f}× compressed",
        f"  Tokens saved   {savings_pct}%  ({daily_total} today)",
        f"  Compression    {ratio:.1f}×",
        f"  Filler removed {filler_count} phrases",
        f"  Engine         {source}",
    ]
    if hint_label:
        lines.append(f"  Model nudge    {hint_label}")
    lines.append(f"\nPrompt: {preview}")
    return "\n".join(lines) + "\n"


# ── Rich full dashboard ───────────────────────────────────────────────────────

def _rich_dashboard(stats: dict) -> str:
    from io import StringIO
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box

    buf = StringIO()
    console = Console(file=buf, highlight=False)

    sess = stats["session"]
    life = stats["lifetime"]
    brevity = stats.get("brevity_mode", "full")
    streak  = stats.get("streak", 0)

    # Session panel
    sess_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    sess_table.add_column("Metric", style="cyan")
    sess_table.add_column("Value",  style="bold green")
    sess_table.add_row("Tokens saved", f"{sess['tokens_saved']:,}")
    sess_table.add_row("Tokens processed", f"{sess['tokens_in']:,}")
    sess_table.add_row("USD saved", f"${sess['usd_saved']:.4f}")
    sess_table.add_row("Compressions", str(sess['compressions']))
    sess_table.add_row("Brevity mode", brevity.upper())

    # Lifetime panel
    life_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    life_table.add_column("Metric", style="cyan")
    life_table.add_column("Value",  style="bold green")
    life_table.add_row("Tokens saved (all time)", f"{life['tokens_saved']:,}")
    life_table.add_row("Total processed", f"{life['tokens_in']:,}")
    life_table.add_row("USD saved (all time)", f"${life['usd_saved']:.4f}")
    life_table.add_row("Total compressions", str(life['compressions']))
    life_table.add_row("Streak", f"{streak} day{'s' if streak != 1 else ''} 🔥")

    # 7-day sparkline
    daily = stats.get("daily_7", [])
    if daily:
        max_saved = max((d["tokens_saved"] for d in daily), default=1) or 1
        sparks = "".join(
            _spark_char(d["tokens_saved"] / max_saved) for d in daily
        )
        spark_str = f"7-day: {sparks}  ({daily[-1]['day'] if daily else '—'})"
    else:
        spark_str = "No data yet"

    # Top intents
    tiers = stats.get("top_tiers", [])
    tier_str = "  ".join(f"{t['tier']}×{t['cnt']}" for t in tiers) or "—"

    console.print(Panel(
        Columns([
            Panel(sess_table, title="[bold]This Session[/]", border_style="blue"),
            Panel(life_table, title="[bold]Lifetime[/]",     border_style="green"),
        ]),
        title="[bold cyan]⚡ Switchboard v2[/]",
        subtitle=f"[dim]{spark_str}  │  Top intents: {tier_str}[/]",
        border_style="cyan",
    ))

    return buf.getvalue()


def _plain_dashboard(stats: dict) -> str:
    sess = stats["session"]
    life = stats["lifetime"]
    lines = [
        "=== Switchboard v2 Dashboard ===",
        "",
        "SESSION",
        f"  Tokens saved:  {sess['tokens_saved']:,}",
        f"  USD saved:     ${sess['usd_saved']:.4f}",
        f"  Compressions:  {sess['compressions']}",
        f"  Brevity mode:  {stats.get('brevity_mode', 'full').upper()}",
        "",
        "LIFETIME",
        f"  Tokens saved:  {life['tokens_saved']:,}",
        f"  USD saved:     ${life['usd_saved']:.4f}",
        f"  Compressions:  {life['compressions']}",
        f"  Streak:        {stats.get('streak', 0)} days",
    ]
    daily = stats.get("daily_7", [])
    if daily:
        lines.append(f"\n7-DAY TREND ({daily[0]['day']} → {daily[-1]['day']})")
        for d in daily:
            lines.append(f"  {d['day']}: {d['tokens_saved']:,} tokens  ${d['usd_saved']:.4f}")
    return "\n".join(lines)


_SPARK = " ▁▂▃▄▅▆▇█"

def _spark_char(ratio: float) -> str:
    idx = int(ratio * (len(_SPARK) - 1))
    return _SPARK[max(0, min(idx, len(_SPARK) - 1))]
