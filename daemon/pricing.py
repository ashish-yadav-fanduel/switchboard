"""
Model pricing table (USD per million tokens, input/output).
Static snapshot; updated by litellm.model_cost when network is available.
"""

MODELS: dict[str, dict[str, float]] = {
    "claude-opus-4-7":   {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":  {"input":  0.80, "output":  4.00},
    "claude-opus-4-5":   {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-5": {"input":  3.00, "output": 15.00},
    "gpt-4o":            {"input":  5.00, "output": 15.00},
    "gpt-4o-mini":       {"input":  0.15, "output":  0.60},
}

DEFAULT_MODEL = "claude-opus-4-7"

TIER_TO_MODEL: dict[str, str] = {
    "SIMPLE":    "claude-haiku-4-5",
    "MEDIUM":    "claude-sonnet-4-6",
    "COMPLEX":   "claude-sonnet-4-6",
    "REASONING": "claude-opus-4-7",
}


def usd_per_token(model: str, direction: str = "input") -> float:
    prices = MODELS.get(model, MODELS[DEFAULT_MODEL])
    return prices[direction] / 1_000_000


def usd_for_tokens(tokens: int, model: str = DEFAULT_MODEL, direction: str = "input") -> float:
    return tokens * usd_per_token(model, direction)


def savings_if_switched(
    tokens: int, from_model: str = DEFAULT_MODEL, to_tier: str = "SIMPLE"
) -> tuple[str, float]:
    """Return (recommended_model, usd_savings) for switching from_model → tier's model."""
    to_model = TIER_TO_MODEL.get(to_tier, DEFAULT_MODEL)
    if to_model == from_model:
        return to_model, 0.0
    delta = usd_for_tokens(tokens, from_model) - usd_for_tokens(tokens, to_model)
    return to_model, round(max(delta, 0.0), 6)


def try_refresh() -> None:
    """Best-effort: sync pricing from litellm's model_cost map (no network calls)."""
    try:
        import litellm
        cost_map = getattr(litellm, "model_cost", {})
        for model_key, costs in cost_map.items():
            if model_key in MODELS:
                inp = costs.get("input_cost_per_token", 0) * 1_000_000
                out = costs.get("output_cost_per_token", 0) * 1_000_000
                if inp > 0:
                    MODELS[model_key]["input"] = inp
                if out > 0:
                    MODELS[model_key]["output"] = out
    except Exception:
        pass
