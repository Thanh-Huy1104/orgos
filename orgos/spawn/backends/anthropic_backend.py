"""Anthropic adapter — native prompt caching, adaptive thinking, tool loop.

The flagship 0.2.0 backend. Runs a role's brief against the Anthropic API
using the official SDK, with:

  - **Prompt caching** on the stable system prefix (``cache_control:
    ephemeral``, optional 1h TTL). Agentic runs re-send the same persona
    scaffold every turn; caching it is the difference between full-rate and
    ~0.1x input pricing on the repeated prefix.
  - **Adaptive thinking** (``{"type": "adaptive"}``) by default. Current
    models (Opus 4.7/4.8, Sonnet 5, Fable 5) reject ``budget_tokens`` and
    sampling params, so neither is ever sent.
  - **A manual tool loop** rather than the SDK's beta tool runner: governance
    must intercept every tool call anyway (tier gate → audit → budget →
    execute), and the manual loop is the stable non-beta surface that gives
    us that interception point. Every ``tool_use`` block is routed through
    ``on_tool_call``; the handler (usually ``run_governed``) owns policy.
  - **Four-way usage reporting** per response: uncached input, cache reads,
    cache writes, output — via ``on_token_usage``.

Requires the ``anthropic`` extra. The SDK's built-in retries
handle 429/5xx; tool-level failures are fed back to the model as
``is_error`` tool results, except governance aborts (BudgetExceeded,
LoopDetected, ToolBudgetExceeded, TierViolation), which propagate.
"""

from __future__ import annotations

from typing import Any

from ..governance.audit import BudgetExceeded, LoopDetected, ToolBudgetExceeded
from ..governance.result import TierViolation, ToolConfigurationError
from .base import (
    BackendResult,
    SpawnBackend,
    ToolCallHandler,
    TokenUsageHandler,
    format_system,
    format_user,
)

_GOVERNANCE_ABORTS = (
    BudgetExceeded, LoopDetected, ToolBudgetExceeded, TierViolation,
    ToolConfigurationError,
)

_DEFAULT_MODEL = "claude-opus-4-8"
_DEFAULT_MAX_TOKENS = 8192
# Above this, non-streaming requests risk SDK HTTP timeouts — stream instead.
_STREAM_THRESHOLD = 16_000


class AnthropicBackend(SpawnBackend):
    """SpawnBackend on the official Anthropic SDK (async client)."""

    name = "anthropic"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        *,
        thinking: bool = True,
        effort: str | None = None,
        cache_system_prompt: bool = True,
        cache_ttl: str = "5m",  # "5m" | "1h"
        max_loops: int = 25,
        client: Any = None,
    ) -> None:
        self.model = model
        self.thinking = thinking
        self.effort = effort
        self.cache_system_prompt = cache_system_prompt
        self.cache_ttl = cache_ttl
        self.max_loops = max_loops
        self._client = client  # injectable for tests

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415 - lazy so core imports stay light
            except ImportError as e:  # pragma: no cover
                raise ImportError(
                    "AnthropicBackend needs the anthropic extra: "
                    "pip install 'anthropic'"
                ) from e
            self._client = anthropic.AsyncAnthropic()
        return self._client

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
        client = self._get_client()
        max_tokens = max_tokens or _DEFAULT_MAX_TOKENS

        system_blocks = self._system_blocks(role)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": format_user(brief, role)}
        ]
        api_tools = [_tool_schema(t) for t in tools]
        usage_totals: dict[str, int] = {}
        calls: list[dict[str, Any]] = []

        for _ in range(self.max_loops):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system_blocks,
                "messages": messages,
            }
            if api_tools:
                kwargs["tools"] = api_tools
            if self.thinking:
                kwargs["thinking"] = {"type": "adaptive"}
            if self.effort:
                kwargs["output_config"] = {"effort": self.effort}

            response = await self._request(client, kwargs, max_tokens)
            self._report_usage(response, usage_totals, on_token_usage)

            stop = getattr(response, "stop_reason", "end_turn")

            if stop == "refusal":
                return BackendResult(
                    output="", tool_calls=calls, stop_reason="refusal",
                    raw=response, usage=usage_totals,
                )

            if stop == "pause_turn":
                # Server-side loop paused; re-send to resume where it left off.
                messages.append({"role": "assistant", "content": response.content})
                continue

            if stop == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                results: list[dict[str, Any]] = []
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    arguments = dict(block.input or {})
                    out, is_error = self._run_tool(
                        on_tool_call, block.name, arguments
                    )
                    calls.append({
                        "name": block.name, "arguments": arguments,
                        "result": out, "is_error": is_error,
                    })
                    result_block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": out,
                    }
                    if is_error:
                        result_block["is_error"] = True
                    results.append(result_block)
                # All results go back in ONE user message — splitting them
                # trains the model out of parallel tool calls.
                messages.append({"role": "user", "content": results})
                continue

            # end_turn / max_tokens / stop_sequence — terminal.
            text = "".join(
                b.text for b in response.content
                if getattr(b, "type", None) == "text"
            ).strip()
            return BackendResult(
                output=text,
                tool_calls=calls,
                stop_reason="length" if stop in ("max_tokens", "model_context_window_exceeded") else "stop",
                raw=response,
                usage=usage_totals,
            )

        return BackendResult(
            output="", tool_calls=calls, stop_reason="max_iterations",
            raw=None, usage=usage_totals,
        )

    async def _request(
        self, client: Any, kwargs: dict[str, Any], max_tokens: int
    ) -> Any:
        if max_tokens > _STREAM_THRESHOLD:
            async with client.messages.stream(**kwargs) as stream:
                return await stream.get_final_message()
        return await client.messages.create(**kwargs)

    def _run_tool(
        self,
        on_tool_call: ToolCallHandler | None,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[str, bool]:
        if on_tool_call is None:
            return (
                f"[ERROR] Model requested tool '{name}' but no tool handler "
                "is wired into this run.",
                True,
            )
        try:
            return str(on_tool_call(name, arguments)), False
        except _GOVERNANCE_ABORTS:
            raise  # governance kills the run; never fed back to the model
        except Exception as e:  # noqa: BLE001 - model recovers from tool errors
            return f"{type(e).__name__}: {e}", True

    def _system_blocks(self, role: Any) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"type": "text", "text": format_system(role)}
        if self.cache_system_prompt:
            cache: dict[str, Any] = {"type": "ephemeral"}
            if self.cache_ttl == "1h":
                cache["ttl"] = "1h"
            block["cache_control"] = cache
        return [block]

    def _report_usage(
        self,
        response: Any,
        totals: dict[str, int],
        on_token_usage: TokenUsageHandler | None,
    ) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt = int(getattr(usage, "input_tokens", 0) or 0)
        completion = int(getattr(usage, "output_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        for key, val in (
            ("prompt_tokens", prompt),
            ("completion_tokens", completion),
            ("cache_hit_input", cache_read),
            ("cache_write_input", cache_write),
        ):
            totals[key] = totals.get(key, 0) + val
        if on_token_usage is not None:
            on_token_usage(
                model=self.model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                cache_hit_input=cache_read,
                cache_write_input=cache_write,
            )


def _tool_schema(tool: Any) -> dict[str, Any]:
    """Duck-typed tool → Anthropic tool definition.

    Accepts dicts with name/description/input_schema keys, or objects with
    those attributes (the runner's ToolDef, or anything shaped like it).
    """
    if isinstance(tool, dict):
        if "type" in tool:
            # Server-tool definition (web_search_*, code_execution_*, ...):
            # pass through verbatim — stripping the type would silently
            # convert it into a schema-less client tool the API never runs.
            return dict(tool)
        return {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get(
                "input_schema", {"type": "object", "properties": {}}
            ),
        }
    return {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "input_schema": getattr(tool, "input_schema", None)
        or {"type": "object", "properties": {}},
    }
