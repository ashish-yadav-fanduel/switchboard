"""
Intent classification: maps prompt text → complexity tier + model recommendation + USD delta.
Uses LiteLLM ComplexityRouter when available; falls back to keyword heuristics.
"""

from __future__ import annotations

import os
from daemon.pricing import DEFAULT_MODEL, TIER_TO_MODEL, savings_if_switched

_complexity_router = None


def classify(text: str, compressed_tokens: int, assume_current: str = DEFAULT_MODEL) -> dict:
    """
    Returns:
        tier          — 'SIMPLE' | 'MEDIUM' | 'COMPLEX' | 'REASONING'
        score         — float [0, 1]
        recommended   — model slug for this tier
        current       — assumed current model (from env or DEFAULT_MODEL)
        usd_delta     — potential USD savings if user switches to recommended
        hint_label    — human-readable hint string (empty if no nudge warranted)
    """
    current = os.environ.get("SWITCHBOARD_CURRENT_MODEL", assume_current)
    tier, score = _classify_tier(text, compressed_tokens)
    recommended, usd_delta = savings_if_switched(compressed_tokens, current, tier)

    # Only nudge when delta is meaningful (> half a cent) and a cheaper model is recommended
    nudge_threshold = 0.005
    if usd_delta >= nudge_threshold and recommended != current:
        hint_label = (
            f"💡 {tier} task — {_short(recommended)} would save ~${usd_delta:.3f} "
            f"(set /model {recommended})"
        )
    elif recommended == current:
        hint_label = f"✓ {_short(current)} is right for this {tier} task"
    else:
        hint_label = ""

    return {
        "tier":        tier,
        "score":       round(score, 3),
        "recommended": recommended,
        "current":     current,
        "usd_delta":   usd_delta,
        "hint_label":  hint_label,
    }


def _short(model: str) -> str:
    """claude-haiku-4-5 → Haiku, claude-opus-4-7 → Opus, etc."""
    if "haiku" in model:
        return "Haiku"
    if "sonnet" in model:
        return "Sonnet"
    if "opus" in model:
        return "Opus"
    return model


def _classify_tier(text: str, compressed_tokens: int) -> tuple[str, float]:
    global _complexity_router
    try:
        import logging
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "1")

        from litellm.router_strategy.complexity_router.complexity_router import (
            ComplexityRouter, ComplexityTier,
        )
        from litellm.router_strategy.complexity_router.config import (
            DEFAULT_TECHNICAL_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
        )
        from litellm._logging import verbose_router_logger
        verbose_router_logger.setLevel(logging.ERROR)

        if _complexity_router is None:
            _complexity_router = ComplexityRouter(
                model_name="dummy",
                litellm_router_instance=None,
                complexity_router_config={
                    "reasoning_keywords": DEFAULT_REASONING_KEYWORDS + [
                        "trade-off", "trade-offs", "tradeoff", "tradeoffs",
                        "when should", "best approach", "how should i approach",
                        "should i use", "which is better", "what's the difference",
                        "compare", "architect", "design pattern", "best practice",
                        "pros and cons",
                    ],
                    "technical_keywords": DEFAULT_TECHNICAL_KEYWORDS + [
                        "cqrs", "event sourcing", "event-driven", "multi-tenant",
                        "row-level security", "dependency injection", "solid",
                        "domain-driven", "ddd", "hexagonal", "clean architecture",
                        "saga", "outbox", "circuit breaker", "rate limiting",
                        "idempotent", "eventual consistency", "sharding",
                        "cap theorem", "acid",
                    ],
                    "dimension_weights": {
                        "tokenCount":         0.10,
                        "codePresence":       0.20,
                        "reasoningMarkers":   0.30,
                        "technicalTerms":     0.30,
                        "simpleIndicators":   0.05,
                        "multiStepPatterns":  0.03,
                        "questionComplexity": 0.02,
                    },
                    "tier_boundaries": {
                        "simple_medium":     0.10,
                        "medium_complex":    0.28,
                        "complex_reasoning": 0.55,
                    },
                },
            )

        tier_obj, score, _ = _complexity_router.classify(text)
        tier_name = {
            ComplexityTier.SIMPLE:    "SIMPLE",
            ComplexityTier.MEDIUM:    "MEDIUM",
            ComplexityTier.COMPLEX:   "COMPLEX",
            ComplexityTier.REASONING: "REASONING",
        }.get(tier_obj, "MEDIUM")
        return tier_name, score

    except Exception:
        pass

    # Keyword fallback
    lower = text.lower()
    keyword_map: list[tuple[list[str], str]] = [
        (["unit test", "pytest", "spec", "mock", "fixture", "assert", "explain",
          "summarize", "tldr", "what does", "what is", "describe"], "SIMPLE"),
        (["refactor", "rename", "clean up", "add type hints", "lint",
          "debug", "why is this", "not working"], "MEDIUM"),
        (["architect", "design system", "how should i approach", "trade-off",
          "design pattern", "cqrs", "domain-driven"], "REASONING"),
    ]
    for signals, tier in keyword_map:
        if any(s in lower for s in signals):
            return tier, 0.5
    return ("REASONING" if compressed_tokens > 800 else "MEDIUM"), 0.5
