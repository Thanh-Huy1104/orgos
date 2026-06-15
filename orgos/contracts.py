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

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from crewai import Agent, LLM, Task
from pydantic import BaseModel, Field


# ── Category constants ───────────────────────────────────────────────────────
CATEGORY_READ = "read"
CATEGORY_SANDBOX = "sandbox"
CATEGORY_COMPUTE = "compute"
CATEGORY_PUBLISH = "publish"
CATEGORY_ORCHESTRATE = "orchestrate"
READONLY_CATEGORIES: set[str] = {CATEGORY_READ}


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
        allowed_categories=set(),  # no tools — delegates only
    ),
}


# ── LLM-layer token budget ───────────────────────────────────────────────────


def budget_llm(llm: LLM, role_name: str, max_tokens: int) -> LLM:
    """Wrap an LLM to enforce a cumulative token budget at the call boundary.

    Mirrors the Anthropic SDK approach: enforcement lives on the LLM-call
    boundary, counting real token usage (not char-length estimates), so it
    fires for tool-less and tool-using agents alike.

    The wrapper monkey-patches ``llm.call`` to read ``_token_usage`` before
    and after each invocation; if cumulative usage exceeds *max_tokens* it
    raises ``BudgetExceeded``, which propagates out through ``kickoff()``.
    """
    original_call = llm.call  # bound method — already has self bound

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
        if used > max_tokens:
            from .audit import BudgetExceeded

            raise BudgetExceeded(
                f"Budget exceeded: {used} real tokens > {max_tokens} cap "
                f"for role '{role_name}'. Run aborted."
            )
        return result

    llm.call = _budgeted_call
    return llm


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

    def _build_llm(self) -> LLM | str | None:
        llm: LLM | None = None
        if isinstance(self.model, LLM):
            llm = self.model
        elif isinstance(self.model, str):
            llm = LLM(model=self.model)
        else:
            return None

        if self.max_budget_tokens is not None:
            llm = budget_llm(llm, self.name, self.max_budget_tokens)
        return llm

    def _build_system_prompt(self) -> str:
        tier = self.tier.value.upper()
        return f"[ROLE: {self.name}] [TIER: {tier}]\n\n{self.system_prompt}"

    def to_agent(self, **overrides: Any) -> Agent:
        """Compile this RoleSpec into a CrewAI Agent.

        Keyword overrides (tools=, step_callback=, llm=, verbose=, skills=,
        mcps=) take precedence over the defaults derived from this RoleSpec.
        """
        llm = overrides.pop("llm", self._build_llm())
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

    def render_description(self, role: RoleSpec | None = None) -> str:
        crit = self.success_criteria or (role.success_criteria if role else [])
        parts = [f"# Objective\n{self.objective}"]
        if self.inputs:
            parts.append("\n# Inputs")
            for k, v in self.inputs.items():
                parts.append(f"- {k}: {v}")
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
