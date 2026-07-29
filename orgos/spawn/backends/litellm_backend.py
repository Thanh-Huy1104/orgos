"""LiteLLM adapter — single-turn reference SpawnBackend.

LiteLLM provides a uniform ``completion`` call across ~100 providers. This
adapter is deliberately minimal: one prompt, one response, no tool loop —
for tool-using governed runs use :class:`AnthropicBackend` (which also does
native prompt caching) or the CrewAI engine.

Usage semantics note: LiteLLM normalizes to OpenAI-style usage, where
``prompt_tokens`` INCLUDES cached tokens. The orgos.spawn contract (and the
cost module) define ``prompt_tokens`` as the UNCACHED remainder, so this
adapter subtracts the cached count before reporting — otherwise cached
tokens get billed twice (full rate + cache rate) downstream.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BackendResult,
    SpawnBackend,
    ToolCallHandler,
    TokenUsageHandler,
    format_system,
    format_user,
)


class LiteLLMBackend(SpawnBackend):
    """A thin wrapper over ``litellm.completion`` — single-turn, no tools."""

    name = "litellm"

    def __init__(
        self,
        model: str,
        *,
        temperature: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        # None means "don't send the parameter". Current Anthropic models
        # (Opus 4.7/4.8, Sonnet 5, Fable 5) reject temperature/top_p/top_k
        # with a 400, so only pass sampling params when explicitly set.
        self.temperature = temperature
        self.extra_body = extra_body or {}

    async def execute(
        self,
        *,
        role: Any,
        brief: Any,
        tools: list[Any],
        max_tokens: int | None = None,
        on_tool_call: ToolCallHandler | None = None,
        on_token_usage: TokenUsageHandler | None = None,
    ) -> BackendResult:
        # Import inside the method so importing orgos.spawn doesn't pull litellm
        # unless a consumer actually instantiates this backend.
        import litellm  # noqa: PLC0415

        if tools:
            # Fail loudly rather than silently drop the tools.
            raise NotImplementedError(
                "LiteLLMBackend is single-turn and does not run tools — use "
                "AnthropicBackend or the CrewAI engine for tool-using roles."
            )

        # Shared helpers: probes _build_system_prompt/description/system_prompt
        # so the persona and tier banner are never silently dropped.
        system = format_system(role)
        user = format_user(brief, role)

        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            **self.extra_body,
        }
        if self.temperature is not None:
            call_kwargs["temperature"] = self.temperature

        response = await litellm.acompletion(**call_kwargs)

        choice = response.choices[0]
        output = (choice.message.content or "").strip()

        # Coarse mapping of provider finish reasons onto our stop_reason enum.
        finish = getattr(choice, "finish_reason", None)
        stop = "length" if finish == "length" else "stop"

        # Report token usage. LiteLLM normalises this across providers.
        usage = getattr(response, "usage", None)
        if usage and on_token_usage is not None:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            # Anthropic + DeepSeek expose cache stats via usage.prompt_tokens_details.
            # LiteLLM >=1.50 normalises it to a pydantic PromptTokensDetailsWrapper
            # (attribute access, no .get); raw provider payloads may be dicts.
            details = getattr(usage, "prompt_tokens_details", None)
            if isinstance(details, dict):
                cache_hit = int(details.get("cached_tokens") or 0)
            else:
                cache_hit = int(getattr(details, "cached_tokens", 0) or 0)
            on_token_usage(
                model=self.model,
                # Contract: prompt_tokens = UNCACHED remainder (OpenAI-style
                # totals include cached tokens; subtract to avoid double-billing).
                prompt_tokens=max(0, prompt_tokens - cache_hit),
                completion_tokens=completion_tokens,
                cache_hit_input=cache_hit,
            )

        return BackendResult(output=output, stop_reason=stop, raw=response)
