#!/usr/bin/env python3
"""
Accuracy test: sends each test prompt to Claude twice — original and compressed —
then compares responses by word-overlap (Jaccard) to verify compression doesn't
degrade answer quality.

Usage:
  python3 test_accuracy.py                # runs built-in test suite
  echo "your prompt" | python3 test_accuracy.py  # tests a single custom prompt
"""

import json
import os
import sys
from pathlib import Path

# ── import compressor from sibling file ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from switchboard import _heuristic_compress

# ── ANSI ──────────────────────────────────────────────────────────────────────
BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
RED    = "\033[31m"
DIM    = "\033[2m"
WHITE  = "\033[97m"
RESET  = "\033[0m"

# ── Built-in test prompts ─────────────────────────────────────────────────────
TEST_PROMPTS = [
    {
        "name": "Python list comprehension",
        "prompt": (
            "Please note that I would like you to explain how list comprehensions "
            "work in Python. It is worth noting that I am fairly new to Python. "
            "Basically, I want to understand the syntax and see a simple example "
            "of how to filter a list of numbers to keep only the even ones."
        ),
    },
    {
        "name": "Git rebase vs merge",
        "prompt": (
            "Can you explain the difference between git rebase and git merge? "
            "I want to understand when I should use each one. Of course, please "
            "include the trade-offs. It is important to cover how each affects "
            "the commit history. Feel free to use a simple example to illustrate."
        ),
    },
    {
        "name": "REST API design",
        "prompt": (
            "I need to design a REST API for a simple todo app. At the end of the day "
            "I just want to know what endpoints I need, what HTTP methods to use, and "
            "what the response shapes should look like. Basically give me the essentials "
            "without going into too much detail about authentication for now."
        ),
    },
]

BAR_W = 12

def bar(pct: float) -> str:
    filled = round(min(pct, 100) / 100 * BAR_W)
    return "█" * filled + "░" * (BAR_W - filled)


def jaccard(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa and not wb:
        return 1.0
    return len(wa & wb) / len(wa | wb)


def call_claude(prompt: str, label: str) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        return f"[ERROR: {e}]"


def run_test(name: str, original: str) -> dict:
    compressed, ratio, filler_count = _heuristic_compress(original)
    savings_pct = round((1 - 1/ratio) * 100)

    print(f"\n{BOLD}{WHITE}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}TEST:{RESET} {name}")
    print(f"{DIM}Original  ({len(original.split())} words): {original[:120]}…{RESET}")
    print(f"{DIM}Compressed ({len(compressed.split())} words): {compressed[:120]}…{RESET}")

    print(f"\n{DIM}Calling Claude with original…{RESET}")
    resp_orig = call_claude(original, "original")

    print(f"{DIM}Calling Claude with compressed…{RESET}")
    resp_comp = call_claude(compressed, "compressed")

    similarity = jaccard(resp_orig, resp_comp)
    sim_pct = round(similarity * 100)

    # render chart
    rows = [
        ("TOKENS SAVED",    bar(savings_pct), f"{savings_pct}%"),
        ("COMPRESSION",     bar(min((ratio-1)/2*100, 100)), f"{ratio:.1f}×"),
        ("FILLER REMOVED",  bar(min(filler_count*12, 100)), f"{filler_count} phrases"),
        ("RESPONSE MATCH",  bar(sim_pct), f"{sim_pct}%"),
    ]
    label_w = max(len(r[0]) for r in rows)
    val_w   = max(len(r[2]) for r in rows)
    inner_w = label_w + 2 + BAR_W + 2 + val_w
    border  = "─" * (inner_w + 2)

    print(f"\n{BOLD}{WHITE}┌{border}┐{RESET}")
    for label, b, val in rows:
        color = GREEN if label == "RESPONSE MATCH" and sim_pct >= 50 else (
                YELLOW if label == "RESPONSE MATCH" and sim_pct >= 30 else RED
                if label == "RESPONSE MATCH" else CYAN)
        print(
            f"{BOLD}{WHITE}│{RESET} "
            f"{CYAN}{label:<{label_w}}{RESET}  "
            f"{YELLOW}{b}{RESET}  "
            f"{BOLD}{color}{val:<{val_w}}{RESET} "
            f"{BOLD}{WHITE}│{RESET}"
        )
    print(f"{BOLD}{WHITE}└{border}┘{RESET}")

    return {"name": name, "ratio": ratio, "savings_pct": savings_pct, "sim_pct": sim_pct}


def main():
    if not sys.stdin.isatty():
        custom = sys.stdin.read().strip()
        if custom:
            run_test("Custom prompt", custom)
            return

    results = [run_test(p["name"], p["prompt"]) for p in TEST_PROMPTS]

    avg_savings = round(sum(r["savings_pct"] for r in results) / len(results))
    avg_sim     = round(sum(r["sim_pct"] for r in results) / len(results))

    print(f"\n{BOLD}{WHITE}{'═'*60}{RESET}")
    print(f"{BOLD}SUMMARY  —  {len(results)} tests{RESET}")
    print(f"  Avg tokens saved : {BOLD}{GREEN}{avg_savings}%{RESET}")
    print(f"  Avg response match: {BOLD}{GREEN if avg_sim >= 50 else YELLOW}{avg_sim}%{RESET}")
    print(f"{BOLD}{WHITE}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    main()
