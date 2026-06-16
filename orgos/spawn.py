"""The spawn library — CrewAI edition.

spawn() and spawn_chain() are the only entry points. They compile RoleSpecs
and TaskBriefs into CrewAI Crews, enforce tier policies, wire approval gates,
and return a validated HandoffEnvelope.

Guarantees (enforced in code, not prompts):
  - Tier-based tool allow/deny/gate via fnmatch patterns and category allowlists.
  - fail-closed gating: if a tier requires approval for a tool but no approval_fn
    is provided, spawn raises _TierViolation.
  - publish-category tools rejected on non-publisher roles.
  - unstructured output → needs_revision, never silently completed.
  - optional token-budget abort (BudgetExceeded caught gracefully).
"""

from __future__ import annotations

import copy
import fnmatch
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from crewai import Crew, Process, Task

from .contracts import (
    TIER_POLICY,
    HandoffEnvelope,
    PermissionTier,
    RoleSpec,
    TaskBrief,
)
from .audit import BudgetExceeded, make_audit_callback, make_task_callback
from .tools import GatedToolBase


# ── Sentinel for _build_task ─────────────────────────────────────────────────
_UNSET = object()


@dataclass
class SpawnResult:
    envelope: HandoffEnvelope
    run_id: str
    token_usage: dict[str, int] | None
    raw_output: str | None
    tasks_output: list[Any]


# ═══════════════════════════════════════════════════════════════════════════════
# Tool enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class _TierViolation(ValueError):
    """Raised when a role's tier doesn't permit the configured tools."""


def _tool_matches(name: str, pattern: str) -> bool:
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def _enforce_tier(role: RoleSpec) -> list[Any]:
    """Validate and filter tools against the role's tier policy.

    Checks (in order):
      1. DENY: tool name matches denied_tools pattern → raise.
      2. ALLOW: if allowed_tools != ["*"], the name must match a pattern.
      3. CATEGORY: if allowed_categories is set, the tool's category must be
         in it. Unknown/empty category → denied (fail-closed for read-only tiers).
      4. PUBLISH: tool_category="publish" → only allowed if can_publish.
    """
    policy = TIER_POLICY[role.tier]
    tools = list(role.tools)
    result: list[Any] = []

    for tool in tools:
        tool_name = getattr(tool, "name", tool.__class__.__name__)
        category: str = (getattr(tool, "tool_category", "") or "").lower()

        # 1. Deny
        for pat in policy.denied_tools:
            if _tool_matches(tool_name, pat):
                raise _TierViolation(
                    f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                    f"tool '{tool_name}' — denied by tier (pattern: '{pat}')"
                )

        # 2. Allow
        if policy.allowed_tools != ["*"]:
            if not any(_tool_matches(tool_name, p) for p in policy.allowed_tools):
                raise _TierViolation(
                    f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                    f"tool '{tool_name}' — not in allowed_tools: {policy.allowed_tools}"
                )

        # 3. Category allowlist (fail-closed for unknown categories)
        if policy.allowed_categories is not None:
            if category not in policy.allowed_categories:
                raise _TierViolation(
                    f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                    f"tool '{tool_name}' — category '{category or 'unknown'}' "
                    f"not in allowed {policy.allowed_categories}"
                )

        # 4. Publish category
        if category == "publish" and not policy.can_publish:
            raise _TierViolation(
                f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                f"publish-class tool '{tool_name}' — only publisher tier may publish"
            )

        # 5. Gateability — anything that must be gated must be a GatedToolBase
        needs_gate = (category == "publish") or any(
            _tool_matches(tool_name, p) for p in policy.requires_approval
        )
        if needs_gate and not isinstance(tool, GatedToolBase):
            raise _TierViolation(
                f"Role '{role.name}' (tier={role.tier.value}) holds tool "
                f"'{tool_name}' that must be approval-gated, but it is not a "
                f"GatedToolBase — wrap it so the gate can actually fire."
            )

        result.append(tool)

    return result


def _wire_gates(tools: list[Any], role: RoleSpec, approval_fn: Any | None) -> list[Any]:
    """Wire approval callbacks into gated tools.

    For each GatedToolBase whose name matches a requires_approval pattern:
      - Sets _agent_role and _gate_required=True.
      - If approval_fn is None → raises _TierViolation (fail-closed).
      - Otherwise sets tool.approval_fn.
    """
    policy = TIER_POLICY[role.tier]

    for tool in tools:
        if not isinstance(tool, GatedToolBase):
            continue
        tool_name = getattr(tool, "name", tool.__class__.__name__)

        should_gate = any(_tool_matches(tool_name, p) for p in policy.requires_approval)
        if not should_gate:
            continue

        if approval_fn is None:
            raise _TierViolation(
                f"Role '{role.name}' (tier={role.tier.value}) requires approval "
                f"for tool '{tool_name}' but no approval_fn was provided — "
                f"refusing to spawn ungated."
            )

        tool._agent_role = role.name
        tool._gate_required = True
        tool.approval_fn = approval_fn

    return tools


# ═══════════════════════════════════════════════════════════════════════════════
# Agent / task factory
# ═══════════════════════════════════════════════════════════════════════════════

def _make_logged_agent(
    role: RoleSpec,
    run_id: str,
    approval_fn: Any | None = None,
    verbose: bool = True,
) -> Any:
    """Build a CrewAI Agent with tier enforcement, audit logging, and gates.

    Budget enforcement happens at the LLM layer (see contracts.budget_llm)
    so it fires for tool-less agents too.

    Copies tools before wiring so shared instances don't cross-mutate
    (PrivateAttrs are fresh on copy, and _wire_gates sets role + gate fields
    on the per-agent copy).
    """
    tools = [copy.copy(t) for t in _enforce_tier(role)]
    tools = _wire_gates(tools, role, approval_fn)

    return role.to_agent(
        tools=tools,
        step_callback=make_audit_callback(role.name, run_id),
        verbose=verbose,
    )


def _build_task(
    role: RoleSpec,
    brief: TaskBrief,
    agent: Any,
    *,
    context: list[Task] | None = None,
    output_pydantic: Any = _UNSET,
) -> Task:
    """Build a CrewAI Task. Pass output_pydantic=_UNSET to default to
    HandoffEnvelope; pass None to explicitly disable schema validation."""
    op = HandoffEnvelope if output_pydantic is _UNSET else output_pydantic
    return brief.to_task(
        agent,
        role=role,
        context=context,
        output_pydantic=op,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Envelope validation
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_json_object(text: str) -> str | None:
    """Pull a JSON object out of prose/markdown.

    Tries a ```json fenced block first, then the first balanced {...} span.
    Returns None if no object-like span is found. This makes the non-json_object
    fallback tolerant of models that wrap their handoff JSON in commentary.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _read_envelope(
    raw_output: str,
    role_name: str,
    pydantic_result: Any | None = None,
) -> HandoffEnvelope:
    """Validate the result against HandoffEnvelope. Fails closed."""
    if pydantic_result is not None and isinstance(pydantic_result, HandoffEnvelope):
        envelope = pydantic_result
    elif pydantic_result is not None and isinstance(pydantic_result, dict):
        try:
            pydantic_result.setdefault("role", role_name)
            envelope = HandoffEnvelope.model_validate(pydantic_result)
        except Exception:
            return HandoffEnvelope.failed(role_name, "invalid pydantic result")
    elif raw_output and raw_output.strip():
        # Try the whole string as JSON, then fall back to extracting a JSON
        # object embedded in prose/markdown (some models wrap it in commentary).
        candidate = raw_output
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            extracted = _extract_json_object(raw_output)
            if extracted is None:
                return HandoffEnvelope.not_completed(
                    role_name, f"output was not valid JSON: {raw_output[:200]}"
                )
            try:
                data = json.loads(extracted)
            except json.JSONDecodeError:
                return HandoffEnvelope.not_completed(
                    role_name, f"output was not valid JSON: {raw_output[:200]}"
                )
        try:
            if isinstance(data, dict):
                data.setdefault("role", role_name)
                envelope = HandoffEnvelope.model_validate(data)
            else:
                return HandoffEnvelope.not_completed(
                    role_name, f"output was not a dict: {raw_output[:200]}"
                )
        except Exception as exc:
            return HandoffEnvelope.failed(role_name, f"envelope validation error: {exc}")
    else:
        return HandoffEnvelope.failed(role_name, "no output produced")

    if envelope.status == "completed" and not envelope.success_criteria_met:
        envelope.status = "needs_revision"
        envelope.notes = (envelope.notes or "") + " [gate: success_criteria_met was False]"
    return envelope


def _extract_token_usage(result: Any) -> dict[str, int] | None:
    if not result.token_usage:
        return None
    tu = result.token_usage
    return {
        "total_tokens": getattr(tu, "total_tokens", 0),
        "prompt_tokens": getattr(tu, "prompt_tokens", 0),
        "completion_tokens": getattr(tu, "completion_tokens", 0),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Kickoff with structured-output fallback
# ═══════════════════════════════════════════════════════════════════════════════

def _is_structured_unsupported(exc: Exception) -> bool:
    """True if the error looks like the provider rejecting structured outputs.

    Non-OpenAI providers (DeepSeek, some local models) reject the
    `response_format`/json_schema parameter that output_pydantic relies on.
    We detect that and fall back to plain text + JSON parsing in _read_envelope.
    """
    msg = str(exc).lower()
    return (
        "response_format" in msg
        or "json_schema" in msg
        or ("structured" in msg and "output" in msg)
    )


def _kickoff_with_fallback(build_crew: Any, probe_structured: bool = True) -> Any:
    """Run the crew, optionally probing structured output first.

    build_crew is a callable taking a single bool (structured) → Crew.

    - probe_structured=True: try build_crew(True); on a structured-output
      rejection, rebuild without the schema and retry once.
    - probe_structured=False: go straight to build_crew(False) — no wasted
      probe for providers known to reject json_schema (e.g. DeepSeek).

    BudgetExceeded propagates untouched. Other exceptions propagate to the
    caller, which converts them into a failed envelope (fail-closed).
    """
    if not probe_structured:
        return build_crew(False).kickoff()
    try:
        return build_crew(True).kickoff()
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 — provider errors are opaque
        if _is_structured_unsupported(exc):
            # Degrade to JSON-via-instructions; _read_envelope parses it.
            return build_crew(False).kickoff()
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# spawn
# ═══════════════════════════════════════════════════════════════════════════════

def spawn(
    role: RoleSpec,
    brief: TaskBrief,
    *,
    subordinates: list[RoleSpec] | None = None,
    approval_fn: Any | None = None,
    verbose: bool = True,
    structured: bool | None = None,
) -> SpawnResult:
    """Spawn one configured agent for one brief.

    Two modes:
      1. Single agent: one RoleSpec → sequential Crew of 1.
      2. Orchestrator: role + subordinates → hierarchical Crew. The orchestrator
         manages; a final sequential synthesis task carries the HandoffEnvelope
         schema so the output is validated without the hierarchical+pydantic crash.

    Tier enforcement happens inside _make_logged_agent.
    """
    run_id = f"{role.name}-{uuid.uuid4().hex[:8]}"
    use_structured = role.effective_structured() if structured is None else structured

    def build_crew(structured: bool) -> Crew:
        op = _UNSET if structured else None
        agent = _make_logged_agent(role, run_id, approval_fn, verbose=verbose)

        if role.tier == PermissionTier.ORCHESTRATOR and subordinates:
            sub_agents = [
                _make_logged_agent(s, run_id, approval_fn, verbose=verbose)
                for s in subordinates
            ]

            # Manager task: no agent assigned (CrewAI's _update_manager_tools
            # injects delegation tools targeting task.agent if set, or all
            # self.agents if task.agent is None — so leaving it unset gives
            # the manager delegation tools for every subordinate).
            manager_task = brief.to_task(
                agent=None,    # type: ignore[arg-type] — BaseAgent | None is valid
                role=role,
                output_pydantic=None,
            )

            # Synthesis task: carries the envelope schema (when structured),
            # assigned to the manager.
            synth_brief = TaskBrief(
                objective=(
                    "Synthesise the results from your delegated work into a final "
                    "handoff. Include all findings, decisions, and the validated shortlist."
                ),
                expected_output="A structured HandoffEnvelope with the final results.",
            )
            synthesis_task = _build_task(role, synth_brief, agent, output_pydantic=op)

            return Crew(
                agents=sub_agents,          # manager NOT in agents list
                tasks=[manager_task, synthesis_task],
                process=Process.hierarchical,
                manager_agent=agent,
                verbose=verbose,
                task_callback=make_task_callback(run_id),
            )

        task = _build_task(role, brief, agent, output_pydantic=op)
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=verbose,
            task_callback=make_task_callback(run_id),
        )

    try:
        result = _kickoff_with_fallback(build_crew, probe_structured=use_structured)
    except BudgetExceeded as exc:
        return SpawnResult(
            envelope=HandoffEnvelope.failed(role.name, str(exc)),
            run_id=run_id,
            token_usage=None,
            raw_output=None,
            tasks_output=[],
        )
    except Exception as exc:  # noqa: BLE001 — fail closed on any kickoff error
        return SpawnResult(
            envelope=HandoffEnvelope.failed(role.name, f"kickoff failed: {exc}"),
            run_id=run_id,
            token_usage=None,
            raw_output=None,
            tasks_output=[],
        )

    envelope = _read_envelope(result.raw, role.name, result.pydantic)

    return SpawnResult(
        envelope=envelope,
        run_id=run_id,
        token_usage=_extract_token_usage(result),
        raw_output=result.raw,
        tasks_output=list(result.tasks_output) if result.tasks_output else [],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# spawn_chain
# ═══════════════════════════════════════════════════════════════════════════════

def spawn_chain(
    steps: list[tuple[RoleSpec, TaskBrief]],
    *,
    approval_fn: Any | None = None,
    verbose: bool = True,
    structured: bool | None = None,
) -> SpawnResult:
    """Run a sequential chain of agents.

    Each step is (RoleSpec, TaskBrief). Agents run in order; each receives the
    previous step's output via task context chaining. Only the final task carries
    the HandoffEnvelope schema.
    """
    run_id = f"chain-{uuid.uuid4().hex[:8]}"
    last_role = steps[-1][0].name if steps else "chain"
    # The last task carries the schema, so the last role's preference governs.
    if structured is None:
        use_structured = steps[-1][0].effective_structured() if steps else True
    else:
        use_structured = structured

    def build_crew(structured: bool) -> Crew:
        agents: list[Any] = []
        tasks: list[Task] = []
        for i, (role_spec, task_brief) in enumerate(steps):
            agent = _make_logged_agent(role_spec, run_id, approval_fn, verbose=verbose)
            agents.append(agent)

            is_last = (i == len(steps) - 1)
            context = tasks.copy() if tasks else None
            op = (HandoffEnvelope if structured else None) if is_last else None

            task = _build_task(
                role_spec,
                task_brief,
                agent,
                context=context,
                output_pydantic=op,
            )
            tasks.append(task)

        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=verbose,
            task_callback=make_task_callback(run_id),
        )

    try:
        result = _kickoff_with_fallback(build_crew, probe_structured=use_structured)
    except BudgetExceeded as exc:
        return SpawnResult(
            envelope=HandoffEnvelope.failed(last_role, str(exc)),
            run_id=run_id,
            token_usage=None,
            raw_output=None,
            tasks_output=[],
        )
    except Exception as exc:  # noqa: BLE001 — fail closed on any kickoff error
        return SpawnResult(
            envelope=HandoffEnvelope.failed(last_role, f"kickoff failed: {exc}"),
            run_id=run_id,
            token_usage=None,
            raw_output=None,
            tasks_output=[],
        )

    final = result.tasks_output[-1] if result.tasks_output else None
    pydantic_result = final.pydantic if final else None
    raw = final.raw if final else result.raw

    return SpawnResult(
        envelope=_read_envelope(raw or "", last_role, pydantic_result),
        run_id=run_id,
        token_usage=_extract_token_usage(result),
        raw_output=raw,
        tasks_output=list(result.tasks_output) if result.tasks_output else [],
    )
