"""
Brevity mode definitions and session-scoped mode management.
"""

MODES: dict[str, str] = {
    "lite": (
        "Remove filler words and hedging from responses. "
        "Keep complete sentences but strip: 'please note', 'it's worth mentioning', "
        "'basically', 'just', 'of course', 'certainly', 'feel free to'. "
        "No other changes to style or format."
    ),
    "full": (
        "[brevity mode] Respond concisely. Use fragments where meaning is clear. "
        "Skip filler, hedging phrases, and explanatory padding. "
        "Prefer: [thing] [action] [outcome]. "
        "Omit 'please note', 'it is worth', 'basically', 'just'."
    ),
    "ultra": (
        "[ULTRA brevity] Telegraphic responses. Rules:\n"
        "• Code first, explanation after (only if non-obvious)\n"
        "• ≤2 sentences max for any explanation\n"
        "• No prose intros: no 'I'll', 'Let me', 'Sure', 'Great'\n"
        "• No hedging: no 'might', 'could potentially', 'you may want to'\n"
        "• No trailing summaries of what you just did\n"
        "• Fragments OK when meaning is clear\n"
        "Format: [result] · [reason in ≤8 words] if non-obvious."
    ),
}

DEFAULT_MODE = "full"
VALID_MODES = set(MODES)


def get_text(mode: str) -> str:
    return MODES.get(mode, MODES[DEFAULT_MODE])


def validate(mode: str) -> str:
    """Return mode if valid, otherwise DEFAULT_MODE."""
    return mode if mode in VALID_MODES else DEFAULT_MODE
