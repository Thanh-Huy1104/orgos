"""Token pricing for benchmark cost accounting.

Prices in USD per 1M tokens. Update as providers change their rates.
Reference: https://api-docs.deepseek.com/quick_start/pricing (cache-miss rates).
"""

from __future__ import annotations

_PER_MILLION: dict[str, dict[str, float]] = {
    "deepseek/deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek/deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # Fallbacks so unknown models don't crash the harness.
    "unknown": {"input": 0.50, "output": 1.50},
}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost in USD for a given model's prompt+completion tokens."""
    p = _PER_MILLION.get(model, _PER_MILLION["unknown"])
    return (
        (prompt_tokens / 1_000_000) * p["input"]
        + (completion_tokens / 1_000_000) * p["output"]
    )
