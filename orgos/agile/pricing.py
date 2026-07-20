"""Token pricing for benchmark cost accounting.

Prices in USD per 1M tokens. Reference:
  https://api-docs.deepseek.com/quick_start/pricing

DeepSeek charges DIFFERENT rates for cache-hit vs cache-miss input tokens.
Real agent workloads hit ~85-95% cache on the repeated persona scaffold,
so a cost estimate that ignores cache hits overstates spend by ~3-4x.

Usage:
  cost_usd(model, prompt_tokens, completion_tokens)
      → legacy signature, treats all prompt tokens as cache-miss (conservative)

  cost_usd_cached(model, cache_hit_in, cache_miss_in, completion_tokens)
      → accurate signature, use when the provider reports cache stats
"""

from __future__ import annotations


# Per DeepSeek's public pricing page (2025-2026 rates):
#   Input cache-miss: full rate
#   Input cache-hit:  ~25% of miss rate (deepseek-chat: $0.07 vs $0.27;
#                                          deepseek-reasoner: $0.14 vs $0.55)
#   Output:           reasoning_tokens are counted as output tokens for
#                     billing purposes (they are part of completion_tokens
#                     in DeepSeek's OpenAI-compat response).
_PER_MILLION: dict[str, dict[str, float]] = {
    "deepseek/deepseek-chat": {
        "input_miss": 0.27,
        "input_hit": 0.07,
        "output": 1.10,
    },
    "deepseek/deepseek-reasoner": {
        "input_miss": 0.55,
        "input_hit": 0.14,
        "output": 2.19,
    },
    # Fallbacks so unknown models don't crash the harness.
    "unknown": {
        "input_miss": 0.50,
        "input_hit": 0.13,
        "output": 1.50,
    },
}


def _rates(model: str) -> dict:
    return _PER_MILLION.get(model, _PER_MILLION["unknown"])


def cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int,
) -> float:
    """Legacy signature — assumes 100% cache-miss for prompt tokens.

    Kept for backwards compatibility with call sites that don't have
    cache stats (e.g. mock executor, historical events). This is
    CONSERVATIVE (overestimates by ~3x for real agent workloads).

    Prefer cost_usd_cached() when cache_hit_tokens is available.
    """
    p = _rates(model)
    return (
        (prompt_tokens / 1_000_000) * p["input_miss"]
        + (completion_tokens / 1_000_000) * p["output"]
    )


def cost_usd_cached(
    model: str,
    cache_hit_tokens: int,
    cache_miss_tokens: int,
    completion_tokens: int,
) -> float:
    """Accurate cost when the provider reports prompt cache hit/miss split.

    DeepSeek's response.usage includes:
      prompt_cache_hit_tokens
      prompt_cache_miss_tokens
    Sum equals prompt_tokens.
    """
    p = _rates(model)
    return (
        (int(cache_hit_tokens or 0) / 1_000_000) * p["input_hit"]
        + (int(cache_miss_tokens or 0) / 1_000_000) * p["input_miss"]
        + (int(completion_tokens or 0) / 1_000_000) * p["output"]
    )


def estimate_with_cache_rate(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_rate: float = 0.90,
) -> float:
    """Estimate real cost when raw cache stats aren't available but you
    have a known typical hit rate for your workload. Default 0.90 matches
    what DeepSeek reports for agentic prompts with a repeated system
    message (persona scaffold).
    """
    hit = int(prompt_tokens * cache_hit_rate)
    miss = int(prompt_tokens) - hit
    return cost_usd_cached(model, hit, miss, completion_tokens)
