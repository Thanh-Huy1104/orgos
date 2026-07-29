"""Per-model rate table with a four-way cache split.

Providers price caching differently:
  - **Anthropic** bills cache *reads* at ~0.1x the input rate and cache
    *writes* at a premium — 1.25x for the 5-minute TTL, 2x for 1-hour.
    ``usage.input_tokens`` is the uncached remainder only; reads and writes
    arrive in separate fields.
  - **DeepSeek** bills cache hits at a reduced input rate and has no write
    premium.

A single ``Rates`` shape covers both. Lookup order in :func:`rates_for`:
the pinned table below (audited numbers for the models orgos.spawn is most
used with), then LiteLLM's community-maintained ``model_cost`` map when
litellm is installed, then ``KeyError`` — never a silent guess.

Pinned Anthropic rates cached from platform.claude.com pricing, 2026-06.
Sonnet 5 uses the sticker price (an introductory discount ran through
2026-08-31; pin the sticker so estimates don't silently drop later).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rates:
    """USD per 1M tokens."""

    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


def _anthropic(input_rate: float, output_rate: float) -> Rates:
    return Rates(
        input=input_rate,
        output=output_rate,
        cache_read=input_rate * 0.1,
        cache_write_5m=input_rate * 1.25,
        cache_write_1h=input_rate * 2.0,
    )


PINNED: dict[str, Rates] = {
    # Anthropic (bare and litellm-prefixed ids)
    "claude-fable-5": _anthropic(10.0, 50.0),
    "claude-opus-4-8": _anthropic(5.0, 25.0),
    "claude-opus-4-7": _anthropic(5.0, 25.0),
    "claude-opus-4-6": _anthropic(5.0, 25.0),
    "claude-sonnet-5": _anthropic(3.0, 15.0),
    "claude-sonnet-4-6": _anthropic(3.0, 15.0),
    "claude-haiku-4-5": _anthropic(1.0, 5.0),
    # DeepSeek: reduced-rate cache hits, no write premium.
    "deepseek/deepseek-chat": Rates(
        input=0.27, output=1.10, cache_read=0.07,
        cache_write_5m=0.27, cache_write_1h=0.27,
    ),
    "deepseek/deepseek-reasoner": Rates(
        input=0.55, output=2.19, cache_read=0.14,
        cache_write_5m=0.55, cache_write_1h=0.55,
    ),
}


def _from_litellm(model: str) -> Rates | None:
    """Look the model up in litellm's community rate map, if available."""
    try:
        from litellm import model_cost  # noqa: PLC0415 - optional dep
    except ImportError:
        return None
    entry = model_cost.get(model) or model_cost.get(model.split("/")[-1])
    if not entry or "input_cost_per_token" not in entry:
        return None
    inp = float(entry["input_cost_per_token"]) * 1_000_000
    out = float(entry.get("output_cost_per_token", 0.0)) * 1_000_000
    read = float(entry.get("cache_read_input_token_cost", 0.0) or 0.0) * 1_000_000
    write = float(entry.get("cache_creation_input_token_cost", 0.0) or 0.0) * 1_000_000
    return Rates(
        input=inp,
        output=out,
        cache_read=read or inp,
        cache_write_5m=write or inp,
        cache_write_1h=write * 1.6 if write else inp,
    )


def rates_for(model: str) -> Rates:
    """Resolve rates for a model id; raise KeyError rather than guess.

    Checks the pinned table (exact id, then with any provider prefix
    stripped), then litellm's ``model_cost`` map when installed.
    """
    if model in PINNED:
        return PINNED[model]
    bare = model.split("/")[-1]
    if bare in PINNED:
        return PINNED[bare]
    from_litellm = _from_litellm(model)
    if from_litellm is not None:
        return from_litellm
    raise KeyError(
        f"no rates for model {model!r} — add it to orgos.spawn.cost.rates.PINNED "
        "or install litellm for community rates"
    )
