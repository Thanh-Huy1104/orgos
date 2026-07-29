"""Backend-based governed execution — the framework-free spawn path.

``run_governed(role, brief, backend)`` runs one role's brief through any
``SpawnBackend`` with the full governance stack that the CrewAI ``spawn()``
engine enforces, minus the framework:

  1. **Brief gate** — an underspecified brief is rejected before a token is
     spent (same zero-cost pre-spawn check as the engine).
  2. **Tier enforcement** — tools are validated against the role's
     TIER_POLICY (deny → allow → category → publish) up front; violations
     raise before execution.
  3. **Approval gates** — tools the tier marks ``requires_approval`` (and
     every publish-category tool) call ``approval_fn(role, tool, input)``
     per invocation; a denial is fed back to the model as an error result
     and logged, never silently executed.
  4. **Audit trail** — every tool call is appended to the run's JSONL log
     in the same record shape as the engine's ``trace_tool``, so
     ``read_trail(run_id)`` works identically across execution paths.
  5. **Budgets** — a run-level token ceiling (``run_budget_tokens``) fed by
     the backend's usage reports, plus the brief's ``tool_call_budget`` and
     the same repeated-action loop guard the engine uses.
  6. **Envelope validation** — the model's output is parsed into a
     HandoffEnvelope (lenient about surrounding prose, strict about shape);
     unparseable output degrades to ``not_completed`` rather than crashing.

Tools are duck-typed: anything with ``name``, optional ``description`` /
``input_schema`` / ``tool_category``, and a callable ``run(**kwargs)`` (or
being callable itself). ``ToolDef`` is provided as the convenient shape.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ..observability import tracer
from ..output.validation import OutputValidationError, validate_output_with
from ..retry import RetryPolicy
from . import audit as _audit
from .audit import (
    BudgetExceeded,
    LoopDetected,
    RunBudget,
    ToolBudgetExceeded,
)
from .contracts import HandoffEnvelope, RoleSpec, TaskBrief
from .result import SpawnResult, ToolConfigurationError
from .tiers import filter_tools_for_tier, requires_approval, tool_name

ApprovalFn = Callable[[str, str, dict[str, Any]], bool]

_MAX_REPEATS = 4  # identical (tool, input) actions before LoopDetected


@dataclass
class ToolDef:
    """A backend-agnostic tool: schema for the model, callable for the runner."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    tool_category: str = ""
    run: Callable[..., Any] | None = None

    def __call__(self, **kwargs: Any) -> Any:
        if self.run is None:
            raise RuntimeError(f"tool '{self.name}' has no run function")
        return self.run(**kwargs)


def run_governed(
    role: RoleSpec,
    brief: TaskBrief,
    backend: Any,
    *,
    tools: list[Any] | None = None,
    approval_fn: ApprovalFn | None = None,
    run_budget_tokens: int | None = None,
    max_tokens: int | None = None,
    validate_brief: bool = True,
    tool_retry: RetryPolicy | None = None,
) -> SpawnResult:
    """Synchronous wrapper around :func:`arun_governed`.

    Must be called from synchronous code. Inside a running event loop
    (FastAPI handler, Jupyter), ``await arun_governed(...)`` instead —
    calling this there raises immediately with that instruction rather
    than asyncio's opaque nesting error.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "run_governed() cannot be used inside a running event loop "
            "(e.g. FastAPI, Jupyter) — use `await arun_governed(...)` instead."
        )
    return asyncio.run(
        arun_governed(
            role, brief, backend,
            tools=tools, approval_fn=approval_fn,
            run_budget_tokens=run_budget_tokens, max_tokens=max_tokens,
            validate_brief=validate_brief, tool_retry=tool_retry,
        )
    )


async def arun_governed(
    role: RoleSpec,
    brief: TaskBrief,
    backend: Any,
    *,
    tools: list[Any] | None = None,
    approval_fn: ApprovalFn | None = None,
    run_budget_tokens: int | None = None,
    max_tokens: int | None = None,
    validate_brief: bool = True,
    tool_retry: RetryPolicy | None = None,
) -> SpawnResult:
    run_id = f"{role.name}-{uuid.uuid4().hex[:8]}"
    usage_totals: dict[str, int] = {}

    if approval_fn is not None and inspect.iscoroutinefunction(approval_fn):
        # bool(coroutine) is always True — an async approver would silently
        # approve every gate. Same footgun as an async tool.run: refuse loudly.
        raise ToolConfigurationError(
            "approval_fn is async, but the approval gate calls it "
            "synchronously — its result would be an unawaited coroutine and "
            "every gate would silently approve. Make it sync (e.g. wrap with "
            "asyncio.run or bridge to your async approver)."
        )

    # 1. Brief gate — refuse to spend tokens on an underspecified brief.
    if validate_brief and (reason := brief.underspecified()):
        return SpawnResult(
            envelope=HandoffEnvelope.failed(role.name, f"brief rejected: {reason}"),
            run_id=run_id, token_usage=None, raw_output=None, tasks_output=[],
        )

    # 2. Tier enforcement — raises TierViolation on a policy breach.
    tool_list = filter_tools_for_tier(
        role, list(tools if tools is not None else role.tools),
        has_approval_fn=approval_fn is not None,
    )
    by_name = {tool_name(t): t for t in tool_list}

    run_budget = RunBudget(run_budget_tokens) if run_budget_tokens else None
    action_counts: dict[str, int] = {}

    def _log(record: dict[str, Any]) -> None:
        _audit.append_record(run_id, record)

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # 3+4+5. The tool-call boundary: gate, bound, execute, audit.
    def on_tool_call(name: str, arguments: dict[str, Any]) -> str:
        base = {"ts": _now(), "run_id": run_id, "role": role.name,
                "type": "tool_call", "tool": name, "tool_input": arguments}

        # Every request — including hallucinated tool names — counts against
        # the loop guard and the brief's call budget. Unknown-tool requests
        # used to bypass both, letting a model spin uncounted.
        sig = f"{name}::{json.dumps(arguments, sort_keys=True, default=str)}"
        action_counts[sig] = action_counts.get(sig, 0) + 1
        if action_counts[sig] > _MAX_REPEATS:
            _log({**base, "ok": False, "output_preview": "loop_detected"})
            raise LoopDetected(
                f"Loop detected: role '{role.name}' issued '{name}' with "
                f"identical input {action_counts[sig]} times (>{_MAX_REPEATS})."
            )
        total = sum(action_counts.values())
        if brief.tool_call_budget is not None and total > brief.tool_call_budget:
            _log({**base, "ok": False, "output_preview": "tool_budget_exceeded"})
            raise ToolBudgetExceeded(
                f"Tool-call budget exceeded: {total} calls "
                f"(>{brief.tool_call_budget} allotted by the brief)."
            )

        tool = by_name.get(name)
        if tool is None:
            _log({**base, "ok": False, "output_preview": "unknown tool"})
            available = ", ".join(sorted(by_name)) or "none"
            return (f"[ERROR] Unknown tool '{name}'. "
                    f"Available tools: {available}.")

        if requires_approval(role, tool):
            approved = bool(approval_fn and approval_fn(role.name, name, arguments))
            _log({**base, "type": "approval", "approved": approved})
            if not approved:
                # Denial is information, not an abort — the model adapts.
                return f"[DENIED] Approval refused for tool '{name}'."

        def _execute() -> Any:
            return tool(**arguments) if callable(tool) else tool.run(**arguments)

        try:
            # Retry covers ONLY the tool's own execution — the gates above
            # already ran, and governance aborts never enter this path.
            with tracer.tool_span(tool_name=name):
                result = tool_retry.call(_execute) if tool_retry else _execute()
            if inspect.iscoroutine(result):
                # Checked outside the retry wrapper: a mis-wired tool is a
                # configuration problem, not a transient failure to retry.
                result.close()
                raise ToolConfigurationError(
                    f"tool '{name}' has an async run function, which the sync "
                    "tool boundary cannot await — the tool body would silently "
                    "never execute. Wrap it (e.g. asyncio.run) or make it sync."
                )
            _log({**base, "ok": True, "output_preview": str(result)[:1200]})
            return str(result)
        except Exception as exc:
            _log({**base, "ok": False,
                  "output_preview": f"{type(exc).__name__}: {exc}"})
            raise

    def on_token_usage(*, model: str, prompt_tokens: int, completion_tokens: int,
                       cache_hit_input: int = 0, cache_write_input: int = 0) -> None:
        for key, val in (
            ("prompt_tokens", prompt_tokens),
            ("completion_tokens", completion_tokens),
            ("cache_hit_input", cache_hit_input),
            ("cache_write_input", cache_write_input),
        ):
            usage_totals[key] = usage_totals.get(key, 0) + val
        usage_totals["model_calls"] = usage_totals.get("model_calls", 0) + 1
        if run_budget is not None:
            # Cache reads and writes are processed (and billed) tokens too —
            # excluding them lets a cache-heavy run sail past its ceiling.
            run_budget.add(
                prompt_tokens + completion_tokens
                + cache_hit_input + cache_write_input,
                role.name,
            )

    try:
        with tracer.spawn_span(role_name=role.name, run_id=run_id,
                               tier=role.tier.value):
            result = await backend.execute(
                role=role, brief=brief, tools=tool_list, max_tokens=max_tokens,
                on_tool_call=on_tool_call, on_token_usage=on_token_usage,
            )
    except (BudgetExceeded, LoopDetected, ToolBudgetExceeded,
            ToolConfigurationError) as e:
        _log({"ts": _now(), "run_id": run_id, "role": role.name,
              "type": "aborted", "reason": f"{type(e).__name__}: {e}"})
        return SpawnResult(
            envelope=HandoffEnvelope.failed(role.name, str(e)),
            run_id=run_id, token_usage=usage_totals or None,
            raw_output=None, tasks_output=[],
        )

    # 6. Envelope validation.
    if result.stop_reason == "refusal":
        envelope = HandoffEnvelope.failed(
            role.name, "provider safety classifiers declined the request"
        )
    elif not result.output:
        envelope = HandoffEnvelope.failed(
            role.name, f"backend returned no output (stop={result.stop_reason})"
        )
    else:
        try:
            envelope = validate_output_with(
                HandoffEnvelope, result.output, role_name=role.name,
                inject={"role": role.name},
            )
        except OutputValidationError:
            envelope = HandoffEnvelope.not_completed(role.name, result.output[:2000])
        else:
            # Parity with the CrewAI engine: "completed" without the success
            # criteria actually met is downgraded — never silently completed.
            if envelope.status == "completed" and not envelope.success_criteria_met:
                envelope.status = "needs_revision"
                envelope.notes = (
                    (envelope.notes or "")
                    + " [downgraded: reported completed without success_criteria_met]"
                ).strip()

    _log({"ts": _now(), "run_id": run_id, "role": role.name, "type": "task",
          "name": "governed_run", "output": (result.output or "")[:2000]})

    return SpawnResult(
        envelope=envelope,
        run_id=run_id,
        token_usage=usage_totals or None,
        raw_output=result.output,
        tasks_output=result.tool_calls,
    )
