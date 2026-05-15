"""
Rotating tips by intent tier — teaches prompt efficiency one prompt at a time.
"""

import hashlib
import time

_TIPS: dict[str, list[str]] = {
    "SIMPLE": [
        "Explain/lookup tasks run 18× cheaper on Haiku. Switch with: /model claude-haiku-4-5",
        "For 'what is X' questions, ask for a one-sentence answer first, then ask to expand if needed.",
        "Summaries compress 40-60% better when you specify format: 'summarize in 3 bullets'.",
        "SIMPLE tasks don't need Sonnet. Haiku handles explain/what-is/summarize at the same quality.",
        "Add 'no preamble' to skip 'Great question!' openers and save ~10 output tokens per response.",
        "For unit test generation, name the framework upfront ('pytest, no mocks') to avoid back-and-forth.",
        "Lookup prompts benefit from specificity: 'in Python 3.12' beats 'in Python'.",
    ],
    "MEDIUM": [
        "Debugging prompts compress best as: error message + file:line + 3 lines of context. Skip backstory.",
        "For refactors, state the constraint upfront: 'no new deps', 'keep public API', 'max 50 chars'.",
        "Medium tasks (debug/fix/rename) perform equally well on Sonnet vs Opus — Opus adds cost, not quality.",
        "Paste the full stack trace, not just the last line. Claude needs the root frame to avoid guessing.",
        "'Fix this' + code is enough. You don't need to explain what the code does — Claude can read it.",
        "For rename tasks, specify scope: 'rename in this file only' avoids unintended cross-file changes.",
        "Add 'one change at a time' to refactor prompts to keep diffs reviewable.",
    ],
    "COMPLEX": [
        "Complex implementations: break into phases. 'Build phase 1: data model only' beats one giant prompt.",
        "Multi-file changes: list the files you want touched. Unlisted files rarely need changing.",
        "Add 'no tests unless I ask' to save 30-40% output tokens on implementation tasks.",
        "For new features, share your existing patterns first: 'follow the style in auth.py'.",
        "Specify done criteria upfront: 'done when all existing tests still pass and X works'.",
        "Long context? Put the most relevant code last — Claude attends to recent tokens more strongly.",
        "Add 'explain your plan in one sentence before coding' to catch misunderstandings early.",
    ],
    "REASONING": [
        "Architecture questions: state constraints first — team size, scale target, existing stack.",
        "Trade-off questions get sharper answers when you name the option you're leaning toward.",
        "Reasoning tasks are where Opus pays for itself. Consider: /model claude-opus-4-7",
        "For design patterns, add 'we use TypeScript + Node, no Java patterns' to avoid irrelevant suggestions.",
        "Ask for the anti-recommendation too: 'and tell me when NOT to use this pattern'.",
        "System design prompts: share your current pain point, not your current architecture.",
        "'What are the risks of X?' often gets better answers than 'should I do X?'.",
    ],
}

_DEFAULT_TIPS = [
    "Remove 'please note that', 'basically', 'feel free to' — Switchboard already strips them for you.",
    "Shorter prompts → faster responses → lower cost. Every token in costs ~3 tokens out.",
    "Use /sb-ultra for pure coding tasks — it cuts response prose by 60% with no quality loss.",
    "Run /sb-stats to see your token savings and streak across sessions.",
]


def get_tip(tier: str, seed: str = "") -> str:
    """Return a tip for the given tier, rotating based on time + seed."""
    bank = _TIPS.get(tier.upper(), _DEFAULT_TIPS)
    # Rotate by hour + seed hash so tips change each session but are stable within one
    h = int(hashlib.md5(f"{int(time.time() // 3600)}{seed}".encode()).hexdigest(), 16)
    return bank[h % len(bank)]
