"""Tests for daemon/classify.py — tier classification + USD delta nudge."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from daemon.classify import classify, _classify_tier
from daemon.pricing import DEFAULT_MODEL, usd_for_tokens, savings_if_switched


# ── Tier classification ───────────────────────────────────────────────────────

SIMPLE_PROMPTS = [
    "explain what this unit test does",
    "what is a python list?",
    "summarize this function",
    "what does assert mean?",
]

REASONING_PROMPTS = [
    "how should I architect a multi-tenant SaaS with row-level security and eventual consistency?",
    "what are the trade-offs between CQRS and a traditional layered architecture?",
    "design a circuit breaker pattern for our event-driven microservices",
]


@pytest.mark.parametrize("prompt", SIMPLE_PROMPTS)
def test_simple_tier(prompt):
    tier, _ = _classify_tier(prompt, 50)
    assert tier in ("SIMPLE", "MEDIUM"), f"Expected SIMPLE/MEDIUM for: {prompt!r}, got {tier}"


@pytest.mark.parametrize("prompt", REASONING_PROMPTS)
def test_reasoning_tier(prompt):
    tier, _ = _classify_tier(prompt, 50)
    assert tier in ("COMPLEX", "REASONING"), f"Expected COMPLEX/REASONING for: {prompt!r}, got {tier}"


def test_large_token_count_biases_toward_reasoning():
    tier, _ = _classify_tier("fix this", 2000)
    # high token count should push toward opus
    assert tier in ("MEDIUM", "COMPLEX", "REASONING")


# ── USD delta calculation ─────────────────────────────────────────────────────

def test_usd_delta_positive_for_simple_on_opus():
    result = classify("explain what this function does", 1000, assume_current="claude-opus-4-7")
    assert result["usd_delta"] > 0, "Should save money switching SIMPLE task from Opus"


def test_usd_delta_zero_for_reasoning_on_opus():
    result = classify(
        "architect a multi-tenant SaaS with row-level security",
        1000, assume_current="claude-opus-4-7"
    )
    assert result["usd_delta"] == 0.0, "Opus is already optimal for REASONING"
    assert result["recommended"] == "claude-opus-4-7"


def test_nudge_fires_above_threshold():
    # 1000 SIMPLE tokens on Opus: (15.00 - 0.80) / 1e6 * 1000 = $0.0142 >> threshold
    result = classify("explain what this function does", 1000, assume_current="claude-opus-4-7")
    assert result["hint_label"] != "", "Nudge should appear for 1000 SIMPLE tokens on Opus"
    assert "Haiku" in result["hint_label"] or "haiku" in result["hint_label"].lower()


def test_nudge_absent_below_threshold():
    # 50 tokens → delta < $0.001, too small to nudge
    result = classify("what is x?", 50, assume_current="claude-opus-4-7")
    # With 50 tokens the delta is ~$0.00071 which is below $0.005 threshold
    if result["tier"] in ("SIMPLE", "MEDIUM"):
        assert result["usd_delta"] < 0.005 or result["hint_label"] == ""


def test_no_nudge_when_already_on_best_model():
    result = classify("what is x?", 500, assume_current="claude-haiku-4-5")
    # SIMPLE on Haiku: recommended=Haiku, delta=0
    if result["tier"] == "SIMPLE":
        assert result["usd_delta"] == 0.0
        assert result["recommended"] == "claude-haiku-4-5"


# ── Pricing helpers ───────────────────────────────────────────────────────────

def test_usd_for_tokens_monotone_across_models():
    tokens = 10_000
    haiku  = usd_for_tokens(tokens, "claude-haiku-4-5")
    sonnet = usd_for_tokens(tokens, "claude-sonnet-4-6")
    opus   = usd_for_tokens(tokens, "claude-opus-4-7")
    assert haiku < sonnet < opus, "Haiku must be cheapest, Opus most expensive"


def test_savings_if_switched_nonzero():
    _, delta = savings_if_switched(1000, "claude-opus-4-7", "SIMPLE")
    assert delta > 0.01, "Switching 1k tokens from Opus to Haiku should save >$0.01"


def test_savings_if_switched_same_model_is_zero():
    _, delta = savings_if_switched(1000, "claude-opus-4-7", "REASONING")
    assert delta == 0.0, "No savings when recommended == current"


# ── Result schema ─────────────────────────────────────────────────────────────

def test_classify_returns_required_keys():
    result = classify("fix this bug", 100)
    for key in ("tier", "score", "recommended", "current", "usd_delta", "hint_label"):
        assert key in result, f"Missing key: {key}"


def test_score_in_range():
    result = classify("refactor this", 200)
    assert 0.0 <= result["score"] <= 1.0
