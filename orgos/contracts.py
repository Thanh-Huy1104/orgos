"""Typed contracts for orgos — CrewAI edition.

These models are the load-bearing part of the system. They define the
permission model, compile RoleSpecs into CrewAI Agents, and enforce the
strict HandoffEnvelope boundary.

Tier enforcement lives HERE, in code — not in prompts. The spawn factory
reads these policies and (a) refuses tools the tier cannot use, (b) auto-gates
tools that require approval, (c) rejects tools whose category falls outside
a tier's allowlist.

Requires: crewai>=1.0, pydantic>=2
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from crewai import Agent, LLM, Task
from pydantic import BaseModel, Field, field_validator


# ── Category constants ───────────────────────────────────────────────────────
CATEGORY_READ = "read"
CATEGORY_SANDBOX = "sandbox"
CATEGORY_COMPUTE = "compute"
CATEGORY_PUBLISH = "publish"
CATEGORY_ORCHESTRATE = "orchestrate"
READONLY_CATEGORIES: set[str] = {CATEGORY_READ}
ORCHESTRATOR_CATEGORIES: set[str] = {CATEGORY_READ, CATEGORY_ORCHESTRATE}


# ── Permission tiers ─────────────────────────────────────────────────────────
class PermissionTier(str, Enum):
    WORKER = "worker"
    VALIDATOR = "validator"
    PUBLISHER = "publisher"
    ORCHESTRATOR = "orchestrator"


class TierPolicy(BaseModel):
    """How a tier maps onto tool permissions.

    Enforced in spawn(), not in prompts:
      - allowed_tools / denied_tools: fnmatch patterns on tool names.
      - requires_approval: fnmatch patterns — tools matching these are auto-gated
        by spawn() via GatedToolBase. Refusing to gate (no approval_fn) raises
        _TierViolation at spawn time.
      - can_publish: only publisher tier. Non-publisher roles with
        tool_category="publish" raise at spawn time.
      - allowed_categories: if set, only tools whose tool_category is in this
        set pass. Unknown/empty category → denied (fail-closed for read-only tiers).
    """

    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    denied_tools: list[str] = Field(default_factory=list)
    requires_approval: list[str] = Field(default_factory=list)
    can_publish: bool = False
    allowed_categories: set[str] | None = (
        None  # None = any category permitted
    )


# The policy table. Edit deliberately — this is the security boundary.
TIER_POLICY: dict[PermissionTier, TierPolicy] = {
    PermissionTier.WORKER: TierPolicy(
        allowed_tools=["*"],
        denied_tools=[],
        requires_approval=[],
        can_publish=False,
        allowed_categories=None,  # workhorse — any tool
    ),
    PermissionTier.VALIDATOR: TierPolicy(
        allowed_tools=["*"],
        denied_tools=[],
        requires_approval=[],
        can_publish=False,
        allowed_categories=READONLY_CATEGORIES,  # only read-category tools
    ),
    PermissionTier.PUBLISHER: TierPolicy(
        allowed_tools=["*"],
        denied_tools=[],
        requires_approval=["*"],  # every tool gated
        can_publish=True,
        allowed_categories=None,
    ),
    PermissionTier.ORCHESTRATOR: TierPolicy(
        allowed_tools=["*"],
        denied_tools=[],
        requires_approval=[],
        can_publish=False,
        allowed_categories=ORCHESTRATOR_CATEGORIES,  # read + orchestrate tools permitted
    ),
}


# ── LLM-layer token budget ───────────────────────────────────────────────────


def budget_llm(
    llm: LLM, role_name: str, max_tokens: int, run_budget: Any | None = None
) -> LLM:
    """Wrap an LLM to enforce a cumulative token budget at the call boundary.

    Mirrors the Anthropic SDK approach: enforcement lives on the LLM-call
    boundary, counting real token usage (not char-length estimates), so it
    fires for tool-less and tool-using agents alike.

    The wrapper monkey-patches ``llm.call`` to read ``_token_usage`` before
    and after each invocation; if cumulative usage exceeds *max_tokens* it
    raises ``BudgetExceeded``, which propagates out through ``kickoff()``.

    If *run_budget* (a ``RunBudget``) is supplied, each call's token *delta* is
    also added to that shared counter, which enforces a ceiling across every
    role in the run — not just this one LLM. Without it, an N-role chain has an
    effective ceiling of N × max_tokens with nothing watching the aggregate.
    """
    # Guard against stacking wrappers when the same LLM instance is reused
    # across roles: always wrap the *original* call, never a previous wrapper,
    # so re-wrapping replaces (last-cap-wins) instead of nesting.
    original_call = getattr(llm, "_orgos_budget_original", None) or llm.call
    llm._orgos_budget_original = original_call

    def _budgeted_call(
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        used = llm._token_usage.get("total_tokens", 0)
        if used > max_tokens:
            from .audit import BudgetExceeded

            raise BudgetExceeded(
                f"Budget exceeded: {used} real tokens > {max_tokens} cap "
                f"for role '{role_name}'. Run aborted."
            )

        result = original_call(
            messages=messages,
            tools=tools,
            callbacks=callbacks,
            available_functions=available_functions,
            from_task=from_task,
            from_agent=from_agent,
            response_model=response_model,
        )

        used = llm._token_usage.get("total_tokens", 0)
        # Feed this call's delta into the shared run budget (counts the chain
        # total across roles). Tracked per-LLM since _token_usage is cumulative.
        if run_budget is not None:
            prev = getattr(llm, "_orgos_last_total", 0)
            run_budget.add(used - prev, role_name)  # may raise BudgetExceeded
        llm._orgos_last_total = used
        if used > max_tokens:
            from .audit import BudgetExceeded

            raise BudgetExceeded(
                f"Budget exceeded: {used} real tokens > {max_tokens} cap "
                f"for role '{role_name}'. Run aborted."
            )
        return result

    llm.call = _budgeted_call
    return llm


# ── Provider capability ──────────────────────────────────────────────────────
# Providers that reject OpenAI json_schema response_format (output_pydantic).
# DeepSeek (both V4 Flash and Pro) and most local runtimes accept only
# text/json_object, so json_schema must be skipped for them.
_NO_JSON_SCHEMA_PREFIXES = ("deepseek/", "ollama/")


def _supports_json_schema(model: Any) -> bool:
    """False for providers known to reject json_schema structured outputs."""
    if isinstance(model, str):
        return not any(model.lower().startswith(p) for p in _NO_JSON_SCHEMA_PREFIXES)
    return True  # LLM instance or None (env default) — assume supported


# ── RoleSpec ─────────────────────────────────────────────────────────────────
class RoleSpec(BaseModel):
    """A declarative role. Compiles to a CrewAI Agent."""

    name: str
    description: str = ""
    tier: PermissionTier
    system_prompt: str

    tools: list[Any] = Field(default_factory=list)
    model: str | LLM | None = None

    max_iter: int = 20
    max_execution_time: int | None = None
    max_budget_tokens: int | None = None

    success_criteria: list[str] = Field(default_factory=list)
    allow_delegation: bool = False

    # Whether to attempt OpenAI-style structured outputs (output_pydantic →
    # response_format: json_schema). OpenAI/Anthropic support it; DeepSeek and
    # some local models reject json_schema (they only accept json_object), so
    # the probe wastes a full failed attempt. Set False for those providers to
    # go straight to JSON-via-instructions + _read_envelope parsing.
    structured_output: bool = True

    # Extension points — wired through to Agent(skills=…, mcps=…)
    skills: list[str | Path] = Field(
        default_factory=list,
        description=(
            "Skill paths (directories containing SKILL.md) or @org/name registry "
            "refs. String paths are converted to Path objects for CrewAI discovery. "
            "Resolved from ./skills/, ~/.crewai/skills/, or the CrewAI+ registry."
        ),
    )
    mcp_servers: list[Any] = Field(
        default_factory=list,
        description=(
            "MCP server configs: MCPServerStdio, MCPServerHTTP, MCPServerSSE "
            "instances, or string URLs. Passed directly to Agent(mcps=…)."
        ),
    )

    def effective_structured(self) -> bool:
        """Whether to attempt OpenAI json_schema structured outputs.

        True only if the role opts in AND the provider supports json_schema.
        DeepSeek/local models return False here, so spawn skips the wasted probe.
        """
        return self.structured_output and _supports_json_schema(self.model)

    def _build_llm(self, run_budget: Any | None = None) -> LLM | str | None:
        llm: LLM | None = None
        if isinstance(self.model, LLM):
            llm = self.model
        elif isinstance(self.model, str):
            llm = LLM(model=self.model)
        elif self.max_budget_tokens is not None:
            # No explicit model, but a budget was requested. A token budget can
            # only be enforced on an LLM instance we control, so build one from
            # the env default rather than letting CrewAI create an unwrappable
            # LLM internally (which would silently skip the budget).
            default_model = (
                os.environ.get("OPENAI_MODEL_NAME")
                or os.environ.get("MODEL")
                or "gpt-4o-mini"
            )
            llm = LLM(model=default_model)
        else:
            return None

        # json_object mode for providers that reject OpenAI json_schema
        # (DeepSeek, local models). A dict response_format routes through the
        # normal completions path and forces valid JSON, which _read_envelope
        # parses cleanly.
        #
        # CRITICAL: json_object forces *every* completion to be a JSON object,
        # which SUPPRESSES native tool calls. So only apply it to tool-LESS
        # roles. A tool-using DeepSeek role runs in "plain" mode (no json_schema,
        # no json_object) and emits its handoff as text that _read_envelope
        # extracts — that keeps native tool calls working.
        # json_object is only safe for a *terminal* role: a single final LLM call
        # with no tools, no MCP servers, and no delegation. Applying it elsewhere
        # breaks the role two ways: it suppresses native tool calls, and any
        # intermediate ReAct/delegation call whose prompt lacks the word "json"
        # gets a 400 ("prompt must contain 'json'") from the API. Non-terminal
        # DeepSeek roles run plain and rely on _read_envelope's JSON extraction.
        is_terminal = (
            not self.tools
            and not self.mcp_servers
            and not self.allow_delegation
            and self.tier != PermissionTier.ORCHESTRATOR
        )
        wants_json_object = (not self.effective_structured()) and is_terminal
        if wants_json_object and getattr(llm, "response_format", None) is None:
            llm.response_format = {"type": "json_object"}

        # Wrap for budget if there's a per-role cap OR a shared run budget to
        # feed. A role with no per-role cap still contributes to the run total,
        # so use a permissive per-role cap in that case and let the run cap bite.
        if self.max_budget_tokens is not None or run_budget is not None:
            per_role_cap = self.max_budget_tokens
            if per_role_cap is None:
                per_role_cap = run_budget.cap if run_budget is not None else 10**12
            llm = budget_llm(llm, self.name, per_role_cap, run_budget=run_budget)
        return llm

    def _build_system_prompt(self) -> str:
        tier = self.tier.value.upper()
        return f"[ROLE: {self.name}] [TIER: {tier}]\n\n{self.system_prompt}"

    def to_agent(self, **overrides: Any) -> Agent:
        """Compile this RoleSpec into a CrewAI Agent.

        Keyword overrides (tools=, step_callback=, llm=, verbose=, skills=,
        mcps=) take precedence over the defaults derived from this RoleSpec.
        """
        run_budget = overrides.pop("run_budget", None)
        llm = overrides.pop("llm", None)
        if llm is None:
            llm = self._build_llm(run_budget=run_budget)
        tools = overrides.pop("tools", self.tools)
        verbose = overrides.pop("verbose", True)

        skills = overrides.pop("skills", None)
        if skills is None and self.skills:
            resolved: list[str | Path] = []
            for s in self.skills:
                if isinstance(s, str) and not s.startswith("@"):
                    p = Path(s)
                    if p.is_dir():
                        resolved.append(p)
                    # else: skip non-existent paths — CrewAI crashes on discovery
                else:
                    resolved.append(s)
            skills = resolved if resolved else None
        skills = skills or None

        mcps = overrides.pop("mcps", None)
        if mcps is None and self.mcp_servers:
            mcps = list(self.mcp_servers)
        mcps = mcps or None

        return Agent(
            role=self.name.replace("-", " ").title(),
            goal=self.description,
            backstory=self._build_system_prompt(),
            tools=tools,
            llm=llm,
            max_iter=self.max_iter,
            max_execution_time=self.max_execution_time,
            allow_delegation=self.allow_delegation,
            verbose=verbose,
            skills=skills,
            mcps=mcps,
            **overrides,
        )


# ── TaskBrief ────────────────────────────────────────────────────────────────
class TaskBrief(BaseModel):
    objective: str
    expected_output: str = "Provide a comprehensive result with clear reasoning."
    boundaries: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[str] = Field(default_factory=list)

    # Anti-vague-delegation fields (Anthropic's documented cure). source_guidance
    # tells the worker WHERE to look; tool_call_budget caps HOW MANY tool calls it
    # may spend. The budget is both surfaced in the prompt and enforced in code
    # (audit callback raises ToolBudgetExceeded past it) — prompts alone don't hold.
    source_guidance: str = ""
    tool_call_budget: int | None = None

    def render_description(self, role: RoleSpec | None = None) -> str:
        crit = self.success_criteria or (role.success_criteria if role else [])
        parts = [f"# Objective\n{self.objective}"]
        if self.inputs:
            parts.append("\n# Inputs")
            for k, v in self.inputs.items():
                parts.append(f"- {k}: {v}")
        if self.source_guidance:
            parts.append(f"\n# Where to look\n{self.source_guidance}")
        if self.tool_call_budget is not None:
            parts.append(
                f"\n# Tool-call budget\nYou may make at most {self.tool_call_budget} "
                f"tool calls. Spend them deliberately — gather what you need, then "
                f"stop and report. Exceeding this aborts the run."
            )
        if self.boundaries:
            parts.append("\n# Boundaries (do NOT)")
            parts.extend(f"- {b}" for b in self.boundaries)
        if crit:
            parts.append("\n# Success criteria (all must be met to report completed)")
            parts.extend(f"- {c}" for c in crit)
        return "\n".join(parts)

    def render_expected(self, role: RoleSpec | None = None) -> str:
        parts = [self.expected_output]
        if role and role.success_criteria:
            parts.append("\nSuccess criteria:")
            parts.extend(f"- {c}" for c in role.success_criteria)
        parts.append(
            "\n\n# Handoff format\n"
            "When done, provide your result as a structured handoff with these fields: "
            "role (your role name), status (completed|needs_revision|blocked|failed), "
            "summary (markdown), artifacts (list of key outputs), "
            "success_criteria_met (bool), requires_human_approval (bool), "
            "payload (a JSON string encoding your findings, or empty), notes (optional)."
        )
        return "\n".join(parts)

    def to_task(
        self,
        agent: Agent,
        *,
        role: RoleSpec | None = None,
        context: list[Task] | None = None,
        output_pydantic: type | None = None,
        **overrides: Any,
    ) -> Task:
        kwargs: dict[str, Any] = {
            "description": self.render_description(role),
            "expected_output": self.render_expected(role),
            "agent": agent,
        }
        if context:
            kwargs["context"] = context
        if output_pydantic is not None:
            kwargs["output_pydantic"] = output_pydantic
        kwargs.update(overrides)
        return Task(**kwargs)


# ── HandoffEnvelope ──────────────────────────────────────────────────────────
class HandoffEnvelope(BaseModel):
    role: str
    status: Literal["completed", "needs_revision", "blocked", "failed"]
    summary: str
    artifacts: list[str] = Field(default_factory=list)
    success_criteria_met: bool = False
    requires_human_approval: bool = False
    # JSON string (not an open dict): an open dict[str, Any] cannot satisfy
    # OpenAI strict structured outputs, which require additionalProperties=false
    # on every object. Carry structured findings as a JSON-encoded string.
    payload: str = ""
    notes: str | None = None

    @field_validator("payload", mode="before")
    @classmethod
    def _coerce_payload(cls, v: Any) -> str:
        """Models naturally emit findings as a nested object; the schema wants a
        JSON string. Coerce dict/list → JSON string, None → "" so a good handoff
        isn't rejected over payload shape."""
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            import json as _json
            return _json.dumps(v)
        return v if isinstance(v, str) else str(v)

    @field_validator("artifacts", mode="before")
    @classmethod
    def _coerce_artifacts(cls, v: Any) -> Any:
        """A single artifact string → one-element list; None → []."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    @classmethod
    def failed(cls, role: str, reason: str) -> "HandoffEnvelope":
        return cls(
            role=role, status="failed",
            summary=f"Handoff validation failed: {reason}",
            success_criteria_met=False,
        )

    @classmethod
    def not_completed(cls, role: str, reason: str) -> "HandoffEnvelope":
        return cls(
            role=role, status="needs_revision", summary=reason[:2000],
            success_criteria_met=False,
            notes="[raw output wrapped — agent did not produce structured handoff]",
        )
