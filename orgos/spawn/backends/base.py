"""Backend contract for spawn execution.

A ``SpawnBackend`` is the *how* under the *what* enforced by
:mod:`orgos.spawn.governance`. Governance decides which tools a role may call,
what the token budget is, and how the audit trail records the run; the
backend is the thing that actually feeds the prompt to an LLM and dispatches
tool calls.

Multiple backends can coexist in one process — pick one per spawn.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


class ToolCallHandler(Protocol):
    """Callback signature invoked by a backend when the model requests a tool.

    The handler is expected to (a) enforce the governance tier gate, (b)
    execute the tool, and (c) return the result string to feed back into the
    model context. Raising propagates as an execution failure.
    """

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> str: ...


class TokenUsageHandler(Protocol):
    """Callback invoked once per LLM response with token accounting.

    Backends should always report both prompt and completion tokens. If the
    provider distinguishes cached input, report it too; otherwise leave the
    cache fields at 0. ``model`` is the string the consumer will use to look
    up pricing. Anthropic-style providers report a four-way split: uncached
    input (``prompt_tokens``), reads served from cache (``cache_hit_input``,
    billed ~0.1x), and cache *writes* (``cache_write_input``, billed at a
    premium — 1.25x for 5m TTL, 2x for 1h).
    """

    def __call__(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_input: int = 0,
        cache_write_input: int = 0,
    ) -> None: ...


@dataclass
class BackendResult:
    """Uniform result returned from every backend.

    ``raw`` is the provider-specific response object, mostly for debugging.
    ``output`` is the textual completion the model produced. ``tool_calls``
    is the ordered list of ``(tool_name, arguments, result)`` triples that
    occurred during the run — useful for the audit trail and for testing.
    Backends set ``stop_reason`` to a coarse category:
    ``"stop"`` (natural end), ``"length"`` (max tokens hit), ``"tool_error"``
    (an unrecoverable tool failure), ``"budget"`` (governance killed it),
    ``"refusal"`` (provider safety classifiers declined — content may be
    empty or partial), or ``"max_iterations"`` (the tool loop hit its cap).
    ``usage`` carries the run's aggregate token totals when the backend
    tracks them (same keys as the TokenUsageHandler fields).
    """

    output: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "stop"
    raw: Any = None
    usage: dict[str, int] = field(default_factory=dict)


class SpawnBackend(ABC):
    """Abstract base for a backend that executes a role's brief.

    Backends are async because most modern SDKs are — provide a sync
    wrapper at the consumer edge if needed. Do NOT enforce governance
    concerns inside a backend; those live in
    :func:`orgos.spawn.governance.spawn`.
    """

    #: Human-readable identifier used in the audit trail. Override in subclasses.
    name: str = "abstract"

    @abstractmethod
    async def execute(
        self,
        *,
        role: Any,            # RoleSpec — kept as Any to avoid import cycle
        brief: Any,           # TaskBrief
        tools: list[Any],
        max_tokens: int | None = None,
        on_tool_call: ToolCallHandler | None = None,
        on_token_usage: TokenUsageHandler | None = None,
    ) -> BackendResult:
        """Run one turn of ``role`` against ``brief`` with ``tools``.

        Governance has already validated the brief and wired the tier gate
        into each tool. The backend is free to loop internally (tool call →
        model → tool call → ...) but MUST fire ``on_tool_call`` for every
        call and ``on_token_usage`` for every model response so the outer
        audit + budget layers see the full picture.
        """
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - default noop
        """Release any long-lived resources (HTTP clients, thread pools)."""
        return None


# Type alias for consumer-friendly signatures.
SpawnBackendFactory = Callable[[], SpawnBackend]
AsyncSpawnBackendFactory = Callable[[], Awaitable[SpawnBackend]]


def format_system(role: Any) -> str:
    """System prompt from a RoleSpec (tier banner + persona), duck-typed.

    Shared by every backend so no backend can silently drop the governance
    banner by probing the wrong attribute names.
    """
    builder = getattr(role, "_build_system_prompt", None)
    if callable(builder):
        return builder()
    name = getattr(role, "name", "agent")
    goal = getattr(role, "description", "") or getattr(role, "goal", "")
    prompt = getattr(role, "system_prompt", "") or getattr(role, "backstory", "")
    parts = [f"You are {name}."]
    if goal:
        parts.append(f"Your goal: {goal}")
    if prompt:
        parts.append(prompt)
    return "\n\n".join(parts)


def format_user(brief: Any, role: Any = None) -> str:
    """User message from a TaskBrief — reuses its own rendering when present."""
    render_desc = getattr(brief, "render_description", None)
    render_exp = getattr(brief, "render_expected", None)
    if callable(render_desc) and callable(render_exp):
        return f"{render_desc(role)}\n\n# Expected output\n{render_exp(role)}"
    objective = getattr(brief, "objective", str(brief))
    expected = getattr(brief, "expected_output", "")
    parts = [objective]
    if expected:
        parts.append(f"Expected output:\n{expected}")
    return "\n\n".join(parts)
