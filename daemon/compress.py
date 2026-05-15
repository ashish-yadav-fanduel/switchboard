"""
Heuristic prompt compressor (two-pass: filler strip + TF-IDF sentence scoring).
This runs inside the daemon process but is importable standalone for tests.
"""

import math
import re
from collections import Counter

_SUBSTITUTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bin order to\b',                    re.I), 'to'),
    (re.compile(r'\bthe reason is because\b',          re.I), 'because'),
    (re.compile(r'\bmake sure to\b',                   re.I), 'ensure'),
    (re.compile(r'\butilize\b',                        re.I), 'use'),
    (re.compile(r'\bimplement a solution for\b',       re.I), 'fix'),
    (re.compile(r'\bprovide assistance with\b',        re.I), 'help with'),
    (re.compile(r'\btake into consideration\b',        re.I), 'consider'),
    (re.compile(r'\bdue to the fact that\b',           re.I), 'because'),
    (re.compile(r'\bat this point in time\b',          re.I), 'now'),
    (re.compile(r'\bin the event that\b',              re.I), 'if'),
    (re.compile(r'\bin spite of the fact that\b',      re.I), 'although'),
    (re.compile(r'\bwith regard to\b',                 re.I), 'regarding'),
    (re.compile(r'\bfor the purpose of\b',             re.I), 'to'),
]

_FILLER_RE = re.compile(
    r'\b('
    # meta-commentary openers
    r'please note that|it is worth noting that|it should be noted that|'
    r'i want you to note that|just note that|'
    r'as you can see|needless to say|as we can see|'
    r'i would like you to|i want you to|could you please|'
    # hedging
    r'just|really|basically|sure|actually|honestly|certainly|simply|'
    r'essentially|generally|perhaps|maybe|somewhat|rather|quite|'
    r'of course|you know|i mean|i think|i believe|i feel like|'
    r'it seems like|it appears that|'
    # filler connectors
    r'in other words|that being said|that said|having said that|'
    r'with that being said|at the end of the day|'
    r'for what it\'s worth|to be honest|to be fair|'
    r'it\'s important to|feel free to|'
    r'however|furthermore|additionally|in addition|moreover|'
    r'nevertheless|nonetheless|'
    # redundant politeness
    r'if you could|if you would|if possible|as needed|as appropriate|'
    r'when you get a chance|at your earliest convenience|'
    r'i\'d appreciate it if|it would be great if|it would be helpful if'
    r')\s*',
    re.IGNORECASE,
)

_CODE_RE = re.compile(r'(```[\s\S]*?```|`[^`\n]+`)', re.MULTILINE)


def strip_filler(text: str) -> tuple[str, int]:
    """Remove hedging/filler phrases and apply substitutions, preserving code blocks."""
    parts = _CODE_RE.split(text)
    result = []
    total_removed = 0
    for i, part in enumerate(parts):
        if i % 2 == 1:  # code block — preserve exactly
            result.append(part)
            continue
        # substitution pass first (in order to → to, utilize → use, etc.)
        for pattern, replacement in _SUBSTITUTIONS:
            part = pattern.sub(replacement, part)
        # filler removal pass
        cleaned, n = _FILLER_RE.subn('', part)
        total_removed += n
        cleaned = re.sub(r'([.!?])\s+,\s*', r'\1 ', cleaned)
        cleaned = re.sub(r'(?m)^\s*[,;]\s*', '', cleaned)
        cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
        cleaned = re.sub(r'(?<=[.!?] )([a-z])', lambda m: m.group(1).upper(), cleaned)
        result.append(cleaned)
    return '\n'.join(p for p in result if p.strip()), total_removed


def heuristic_compress(text: str, target_ratio: float = 0.5) -> tuple[str, float, int]:
    """
    Two-pass compressor:
      1. Word-level: strip filler/hedging phrases
      2. Sentence-level: TF-IDF scoring, drop lowest-information sentences
    Preserves code blocks. Keeps first/last sentence as anchors.
    Returns (compressed_text, actual_ratio, filler_count).
    """
    original_len = len(text)
    text, filler_count = strip_filler(text)

    block_re = re.compile(r'(```[\s\S]*?```)', re.MULTILINE)
    placeholders: dict[str, str] = {}
    ph_counter = [0]

    def stash(m: re.Match) -> str:
        key = f"\x00BLK{ph_counter[0]}\x00"
        placeholders[key] = m.group(0)
        ph_counter[0] += 1
        return key

    scrubbed = block_re.sub(stash, text)
    raw_sentences = re.split(r'(?<=[.!?])\s+|\n{2,}', scrubbed)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    if len(sentences) <= 3:
        return text, round(original_len / max(len(text), 1), 2), filler_count

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
    must_keep = {0, len(sentences) - 1}
    original_chars = sum(len(s) for s in sentences)
    target_chars = max(int(original_chars * target_ratio), 1)

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

    for key, block in placeholders.items():
        compressed = compressed.replace(key, block)

    actual_ratio = original_len / max(len(compressed), 1)
    return compressed, round(actual_ratio, 2), filler_count
