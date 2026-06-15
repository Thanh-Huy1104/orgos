"""Evolutive org — the self-improving company.

The OrgAnalyzer spawns an agent with full memory access (MCP). It reads
actual run summaries, failure patterns, and department outputs — not just
aggregate metrics. Based on deep analysis it proposes concrete changes:
  - Create new departments (complete with supervisor + members + system prompts)
  - Add roles to existing departments
  - Add SOPs, handoffs, policy rules
  - Adjust thresholds and cadences

Every proposal passes through legal review before reaching you.

Flow:
  analyze (reads memory) → propose (structured) → review (legal) → approve (you) → apply (writes org.yaml)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ── Proposal ──────────────────────────────────────────────────────────────────


class ProposalType(str, Enum):
    CREATE_DEPARTMENT = "create_department"
    ADD_ROLE = "add_role"
    ADD_SOP = "add_sop"
    ADD_HANDOFF = "add_handoff"
    MODIFY_THRESHOLD = "modify_threshold"
    MODIFY_CADENCE = "modify_cadence"
    ADD_POLICY_RULE = "add_policy_rule"
    NEEDS_TOOLS = "needs_tools"             # agent needs tools/MCPs
    NEEDS_CREDENTIALS = "needs_credentials" # agent needs API keys/tokens from owner


class Proposal(BaseModel):
    """A structured change to the org constitution."""

    id: str = ""
    type: ProposalType
    target: str  # department name, policy ID, etc.
    summary: str
    reasoning: str
    risk: str = "low"
    evidence: dict[str, Any] = Field(default_factory=dict)
    changes: dict[str, Any] = Field(default_factory=dict)

    # Tool/MCP gaps the analyzer detected from failure patterns
    recommended_tools: list[str] = Field(default_factory=list)
    recommended_mcps: list[str] = Field(default_factory=list)

    # Credentials the agent needs from the owner
    credential_needs: list[dict[str, str]] = Field(default_factory=list)

    created_at: str = ""

    def to_markdown(self) -> str:
        risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(self.risk, "⚪")
        lines = [
            f"## Proposal {self.id}: {self.summary}",
            f"**Type**: {self.type.value}  |  **Target**: {self.target}  |  **Risk**: {risk_icon} {self.risk}",
            "",
            f"### Reasoning",
            self.reasoning,
            "",
        ]
        if self.evidence:
            lines.append("### Evidence")
            for k, v in self.evidence.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        if self.changes:
            lines.append("### Changes")
            lines.append("```yaml")
            lines.append(yaml.dump(self.changes, default_flow_style=False, allow_unicode=True).strip())
            lines.append("```")
            lines.append("")
        if self.recommended_tools:
            lines.append("### Recommended Tools")
            for t in self.recommended_tools:
                lines.append(f"- `{t}`")
            lines.append("")
        if self.recommended_mcps:
            lines.append("### Recommended MCPs")
            for m in self.recommended_mcps:
                lines.append(f"- {m}")
            lines.append("")
        if self.credential_needs:
            lines.append("### Credentials Needed from Owner")
            for c in self.credential_needs:
                lines.append(f"- **{c.get('name', '?')}**: {c.get('purpose', '')}")
                if c.get('url'):
                    lines.append(f"  Get it at: {c['url']}")
            lines.append("")
        return "\n".join(lines)

    @classmethod
    def make(
        cls, type: ProposalType, target: str, summary: str, reasoning: str,
        changes: dict | None = None, risk: str = "low", evidence: dict | None = None,
        tools: list[str] | None = None, mcps: list[str] | None = None,
        credentials: list[dict[str, str]] | None = None,
    ) -> "Proposal":
        return cls(
            id=uuid.uuid4().hex[:8],
            type=type, target=target, summary=summary, reasoning=reasoning,
            changes=changes or {}, risk=risk, evidence=evidence or {},
            recommended_tools=tools or [],
            recommended_mcps=mcps or [],
            credential_needs=credentials or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )


# ── Org analyzer ──────────────────────────────────────────────────────────────


class OrgAnalyzer:
    """Analyzes org performance and generates improvement proposals.

    Two modes:
      - Deterministic (rule-based, zero tokens): catches obvious gaps.
      - LLM-powered (agent with memory MCP): reads run content, failure
        patterns, and proposes full departments with system prompts.
    """

    def __init__(self, org: Any):
        self.org = org
        self.memory = org.use_memory()

    # ── Deterministic proposals (zero tokens) ────────────────────────────

    def basic_proposals(self) -> list[Proposal]:
        """Rule-based proposals from surface metrics. Fast, free."""
        proposals: list[Proposal] = []

        for dept in self.org.departments:
            recent = self.memory.recent_runs(department=dept.name, limit=20)
            if not recent:
                continue

            fails = sum(1 for r in recent if r.status not in ("completed",))
            success_rate = round((len(recent) - fails) / len(recent) * 100, 1)
            spend_7d = self.memory.department_spend(dept.name, days=7)

            # High failure rate → needs attention
            if fails >= 3 and success_rate < 60:
                proposals.append(Proposal.make(
                    ProposalType.ADD_ROLE, dept.name,
                    f"Add a reviewer role to {dept.name} to catch failures",
                    f"{dept.name} has {fails}/{len(recent)} recent failures ({success_rate}%). "
                    "A reviewer/validator role could catch issues before they propagate.",
                    risk="medium",
                    evidence={"failures": fails, "success_rate": f"{success_rate}%"},
                ))

            # Credential / tool gaps detected from failure summaries
            _cred_keywords = ["missing", "cannot fetch", "no access", "unauthorized",
                             "api key", "credential", "token", "permission denied",
                             "not found", "connection refused", "auth", "login"]
            _tool_gap_keywords = ["no tool", "need", "missing data source",
                                 "cannot", "unable to", "require", "no module"]

            cred_needs = []
            tool_gaps = []
            for r in recent:
                if r.status in ("completed",):
                    continue
                summary_lower = r.summary.lower()
                if any(kw in summary_lower for kw in _cred_keywords):
                    cred_needs.append(r.summary[:200])
                if any(kw in summary_lower for kw in _tool_gap_keywords):
                    tool_gaps.append(r.summary[:200])

            if cred_needs and len(cred_needs) >= 2:
                proposals.append(Proposal.make(
                    ProposalType.NEEDS_CREDENTIALS, dept.name,
                    f"{dept.name} agents need credentials from owner",
                    f"Found {len(cred_needs)} failures related to missing credentials "
                    f"in {dept.name}. Recent: {cred_needs[-1][:120]}",
                    risk="high",
                    evidence={"credential_failures": len(cred_needs)},
                    credentials=[
                        {"name": "Required credentials", "purpose": c[:150]}
                        for c in cred_needs[-3:]
                    ],
                ))

            if tool_gaps and len(tool_gaps) >= 2:
                proposals.append(Proposal.make(
                    ProposalType.NEEDS_TOOLS, dept.name,
                    f"{dept.name} agents need additional tools or MCPs",
                    f"Found {len(tool_gaps)} failures related to missing tools/capabilities "
                    f"in {dept.name}. Recent: {tool_gaps[-1][:120]}",
                    risk="high",
                    evidence={"tool_gap_failures": len(tool_gaps)},
                    tools=["WebFetch (internet access)", "DataFetch MCP"],
                    mcps=["Internet/HTTP access MCP for external data"],
                ))

            # High token spend → reduce cadence
            budget = self.org.default_max_budget_tokens or 100000
            if spend_7d["total_tokens"] > budget * 0.5:
                proposals.append(Proposal.make(
                    ProposalType.MODIFY_CADENCE, dept.name,
                    f"Reduce {dept.name} SOP frequency to control costs",
                    f"{dept.name} spent {spend_7d['total_tokens']:,} tokens in 7 days "
                    f"({spend_7d['total_tokens'] / max(budget, 1) * 100:.0f}% of budget).",
                    changes={"department": dept.name, "recommendation": "reduce frequency or switch model"},
                    risk="medium",
                    evidence={"spend_7d": spend_7d["total_tokens"], "budget": budget},
                ))

            # No SOPs → needs structure
            if not dept.sops and len(dept.all_roles()) > 1:
                proposals.append(Proposal.make(
                    ProposalType.ADD_SOP, dept.name,
                    f"Add SOPs to {dept.name}",
                    f"{dept.name} has {len(dept.all_roles())} roles but zero SOPs. "
                    "Without recurring work, the department is idle.",
                    changes={
                        "sop_name": f"{dept.name}_daily_check",
                        "cadence": "daily",
                        "objective": f"Daily check-in for {dept.name} department.",
                    },
                    risk="low",
                ))

        # No legal department → critical gap
        if not self.org.find_department("legal"):
            proposals.append(Proposal.make(
                ProposalType.CREATE_DEPARTMENT, "legal",
                "Create a legal/compliance department",
                "Every org with publish actions needs compliance oversight. "
                "Legal provides veto power on risky actions and reviews all outputs.",
                changes={
                    "department": {
                        "name": "legal",
                        "description": "Cross-cutting compliance and policy review.",
                        "supervisor": {
                            "name": "legal-supervisor", "tier": "orchestrator",
                            "system_prompt": "You are the legal lead. Review all publish-class actions. Delegate to legal-reviewer for detailed analysis. You have veto power.",
                            "model": self.org.default_model, "max_iter": 15,
                        },
                        "members": [{
                            "name": "legal-reviewer", "tier": "validator",
                            "system_prompt": "Review actions against org policy. Cite specific rule IDs. Be precise.",
                            "model": self.org.default_model, "max_iter": 10,
                            "success_criteria": ["Every issue cited with specific policy reference"],
                        }],
                        "sops": [{
                            "name": "review_publish_action", "cadence": None,
                            "brief": {
                                "objective": "Review the provided artifact for policy compliance. Check all rules and return a verdict.",
                                "expected_output": "Structured verdict with policy references.",
                            },
                        }],
                    },
                    "handoffs": [],
                },
                risk="low",
            ))

        # Department with success but no handoffs → missing oversight
        for dept in self.org.departments:
            recent = self.memory.recent_runs(department=dept.name, limit=20)
            if len(recent) >= 5 and success_rate > 70:
                has_handoff = any(
                    h.get("from") == dept.name
                    for h in (getattr(self.org, "handoffs", []) or [])
                    if isinstance(h, dict)
                )
                legal = self.org.find_department("legal")
                if not has_handoff and legal:
                    proposals.append(Proposal.make(
                        ProposalType.ADD_HANDOFF, f"{dept.name} → legal",
                        f"Add legal review handoff for {dept.name}",
                        f"{dept.name} has {len(recent)} successful runs with no legal oversight. "
                        "Adding a handoff ensures compliance review.",
                        changes={
                            "from": dept.name, "to": "legal",
                            "artifact_type": f"{dept.name}_output",
                            "auto_trigger": True,
                        },
                        risk="low",
                    ))

        return proposals

    # ── LLM-powered deep analysis ────────────────────────────────────────

    def deep_analysis(
        self,
        *,
        verbose: bool = False,
    ) -> list[Proposal]:
        """Spawn an analyzer agent with memory access for deep investigation.

        The agent gets access to the memory MCP so it can:
        - Search run history for failure patterns
        - Read actual agent summaries
        - Cross-reference department outputs
        - Propose full departments with system prompts, roles, and tools
        """
        from .contracts import RoleSpec, TaskBrief, PermissionTier
        from .spawn import spawn
        from .memory import create_memory_mcp

        # Build the analysis prompt with full org context
        dept_summaries = []
        for dept in self.org.departments:
            spend = self.memory.department_spend(dept.name, days=30)
            recent = self.memory.recent_runs(department=dept.name, limit=10)
            dept_summaries.append({
                "name": dept.name,
                "description": dept.description,
                "roles": [{"name": r.name, "tier": r.tier.value} for r in dept.all_roles()],
                "sops": [{"name": s.name, "cadence": s.cadence} for s in dept.sops],
                "spend_30d_tokens": spend["total_tokens"],
                "recent_runs": len(recent),
                "recent_failures": sum(1 for r in recent if r.status not in ("completed",)),
                "last_3_summaries": [r.summary[:200] for r in recent[:3]],
            })

        handoffs = [
            {"from": h.get("from"), "to": h.get("to"), "type": h.get("artifact_type")}
            for h in (getattr(self.org, "handoffs", []) or [])
            if isinstance(h, dict)
        ]

        system_prompt = (
            "You are an organizational design consultant. Your job is to analyze "
            "the org's performance data and propose concrete improvements.\n\n"
            "## Available tools\n"
            "- Use recall_past_runs to search the org's run history for patterns.\n"
            "- Use get_department_status to check department metrics.\n"
            "- Use get_last_run to examine recent outputs.\n\n"
            "## What to look for\n"
            "1. **Tool/MCP gaps**: Agents failing because they lack tools (internet access, "
            "data fetching, file I/O). Propose specific tools or MCP servers they need.\n"
            "2. **Credential needs**: Agents failing due to missing API keys, tokens, or "
            "credentials. These must be surfaced to the owner explicitly with the credential "
            "name, purpose, and where to get it.\n"
            "3. **Missing roles**: Departments that need additional roles (QA, reviewer, "
            "analyst). Include complete RoleSpecs with system prompts.\n"
            "4. **Failures**: Recurring failures — read the actual summaries to "
            "understand WHY they fail.\n"
            "5. **Missing oversight**: Departments producing outputs with no legal review.\n\n"
            "## Output format\n"
            "Return a JSON array of proposals. Each proposal:\n"
            '{"type": "needs_tools|needs_credentials|create_department|add_role|...", '
            '"target": "...", "summary": "...", "reasoning": "...", '
            '"changes": {...}, "recommended_tools": [...], "recommended_mcps": [...], '
            '"credential_needs": [{"name": "...", "purpose": "...", "url": "..."}], '
            '"risk": "low|medium|high", "evidence": {...}}\n\n'
            "## Rules\n"
            "- Max 5 proposals.\n"
            "- For credential needs, ALWAYS include the credential name and where to get it.\n"
            "- For tool gaps, propose specific CrewAI-compatible tools or MCP server names.\n"
            "- NEVER propose removing owner approval or legal veto.\n"
            "- Be specific: name the department, name the role, write the prompt."
        )

        analyzer = RoleSpec(
            name="org-analyzer",
            tier=PermissionTier.WORKER,
            system_prompt=system_prompt,
            model=self.org.default_model,
            max_iter=20,
            mcp_servers=[create_memory_mcp(str(self.memory.db_path))],
        )

        brief = TaskBrief(
            objective=(
                "Analyze this org and propose improvements.\n\n"
                f"**Org departments**:\n```json\n{json.dumps(dept_summaries, indent=2)}\n```\n\n"
                f"**Handoff rules**:\n```json\n{json.dumps(handoffs, indent=2)}\n```\n\n"
                "Use the memory tools to investigate further: search for failure patterns, "
                "read recent summaries, check department status. Then propose concrete changes."
            ),
            expected_output="JSON array of proposals with complete details including system prompts for new roles.",
            success_criteria=[
                "Proposals cite specific data or search results",
                "No proposal removes safety mechanisms",
                "New departments include complete role definitions",
            ],
        )

        result = spawn(analyzer, brief, verbose=verbose)

        return self._parse_proposals(result.envelope)

    def _parse_proposals(self, envelope: Any) -> list[Proposal]:
        try:
            payload = getattr(envelope, "payload", "") or ""
            data = json.loads(payload) if payload else {}
        except (json.JSONDecodeError, TypeError):
            data = {}

        items = data if isinstance(data, list) else data.get("proposals", [])
        proposals: list[Proposal] = []

        # Map common LLM-generated type strings to ProposalType values
        _type_map: dict[str, ProposalType] = {
            "create_department": ProposalType.CREATE_DEPARTMENT,
            "add_department": ProposalType.CREATE_DEPARTMENT,
            "new_department": ProposalType.CREATE_DEPARTMENT,
            "add_role": ProposalType.ADD_ROLE,
            "new_role": ProposalType.ADD_ROLE,
            "gap": ProposalType.ADD_ROLE,  # LLM often says "gap" meaning missing role
            "add_sop": ProposalType.ADD_SOP,
            "new_sop": ProposalType.ADD_SOP,
            "add_handoff": ProposalType.ADD_HANDOFF,
            "new_handoff": ProposalType.ADD_HANDOFF,
            "modify_threshold": ProposalType.MODIFY_THRESHOLD,
            "adjust_threshold": ProposalType.MODIFY_THRESHOLD,
            "modify_cadence": ProposalType.MODIFY_CADENCE,
            "reduce_cadence": ProposalType.MODIFY_CADENCE,
            "add_policy_rule": ProposalType.ADD_POLICY_RULE,
            "new_policy": ProposalType.ADD_POLICY_RULE,
            "needs_tools": ProposalType.NEEDS_TOOLS,
            "missing_tools": ProposalType.NEEDS_TOOLS,
            "tool_gap": ProposalType.NEEDS_TOOLS,
            "needs_credentials": ProposalType.NEEDS_CREDENTIALS,
            "missing_credentials": ProposalType.NEEDS_CREDENTIALS,
            "credential_gap": ProposalType.NEEDS_CREDENTIALS,
            "need_api_key": ProposalType.NEEDS_CREDENTIALS,
            "need_access": ProposalType.NEEDS_CREDENTIALS,
        }

        for item in items:
            if not isinstance(item, dict):
                continue
            raw_type = item.get("type", "")
            ptype = _type_map.get(raw_type)
            if ptype is None:
                try:
                    ptype = ProposalType(raw_type)
                except ValueError:
                    ptype = ProposalType.MODIFY_THRESHOLD

            proposals.append(Proposal.make(
                type=ptype,
                target=item.get("target", "unknown"),
                summary=item.get("summary", ""),
                reasoning=item.get("reasoning", ""),
                changes=item.get("changes", {}),
                risk=item.get("risk", "low"),
                evidence=item.get("evidence", {}),
                tools=item.get("recommended_tools", []),
                mcps=item.get("recommended_mcps", []),
                credentials=item.get("credential_needs", []),
            ))

        return proposals


# ── Review ────────────────────────────────────────────────────────────────────


def review_proposals(
    proposals: list[Proposal],
    org: Any,
    *,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Send proposals through legal review. Returns verdicts."""
    from .legal import legal_review_with_agent
    from .contracts import HandoffEnvelope

    verdicts = []
    for p in proposals:
        env = HandoffEnvelope(
            role="org-analyzer", status="completed",
            summary=p.to_markdown(), success_criteria_met=True,
        )
        review = legal_review_with_agent(env, org, verbose=verbose)
        verdicts.append({
            "proposal_id": p.id,
            "approved": review["approved"],
            "verdict": review["verdict"],
            "requires_owner": review["requires_owner"],
            "reasoning": review.get("reasoning", ""),
            "denials": review.get("denials", []),
        })
    return verdicts


# ── Apply ─────────────────────────────────────────────────────────────────────


def apply_proposal(
    proposal: Proposal,
    org_yaml_path: str | Path = "org.yaml",
) -> dict[str, Any]:
    """Apply an approved proposal to the org.yaml file.

    Handles full department creation, role addition, and all other
    proposal types by modifying the YAML structure directly.
    """
    path = Path(org_yaml_path)
    if not path.exists():
        return {"applied": False, "message": f"org.yaml not found at {path}"}

    data = yaml.safe_load(path.read_text())
    dept_list: list = data.get("departments", [])

    try:
        if proposal.type == ProposalType.CREATE_DEPARTMENT:
            dept_def = proposal.changes.get("department", {})
            if dept_def.get("name"):
                # Check for duplicates
                existing = [d.get("name") for d in dept_list]
                if dept_def["name"] in existing:
                    return {"applied": False, "message": f"Department '{dept_def['name']}' already exists"}
                dept_list.append(dept_def)
                data["departments"] = dept_list

            # Also add handoffs if provided
            for h in proposal.changes.get("handoffs", []):
                handoffs = data.get("handoffs", [])
                handoffs.append(h)
                data["handoffs"] = handoffs

        elif proposal.type == ProposalType.ADD_ROLE:
            dept_name = proposal.target
            role_def = proposal.changes.get("role", {})
            for d in dept_list:
                if d.get("name") == dept_name:
                    members = d.get("members", [])
                    members.append(role_def)
                    d["members"] = members
                    data["departments"] = dept_list
                    break
            else:
                return {"applied": False, "message": f"Department '{dept_name}' not found"}

        elif proposal.type == ProposalType.ADD_SOP:
            dept_name = proposal.target
            for d in dept_list:
                if d.get("name") == dept_name:
                    sops = d.get("sops", [])
                    sop_def = {
                        "name": proposal.changes.get("sop_name", "new_sop"),
                        "cadence": proposal.changes.get("cadence", "daily"),
                        "brief": {
                            "objective": proposal.changes.get("objective", "New SOP"),
                            "expected_output": proposal.changes.get("expected_output", ""),
                        },
                    }
                    sops.append(sop_def)
                    d["sops"] = sops
                    break

        elif proposal.type == ProposalType.ADD_HANDOFF:
            handoffs = data.get("handoffs", [])
            handoffs.append(proposal.changes)
            data["handoffs"] = handoffs

        elif proposal.type in (ProposalType.MODIFY_THRESHOLD, ProposalType.MODIFY_CADENCE):
            dept_name = proposal.target
            for d in dept_list:
                if d.get("name") == dept_name:
                    supervisor = d.get("supervisor", {})
                    for k, v in proposal.changes.items():
                        if k in ("model", "max_iter", "max_budget_tokens", "max_execution_time"):
                            supervisor[k] = v
                    break

        elif proposal.type == ProposalType.ADD_POLICY_RULE:
            pending = data.get("pending_policy_changes", [])
            pending.append(proposal.changes)
            data["pending_policy_changes"] = pending

        elif proposal.type == ProposalType.NEEDS_TOOLS:
            pending_tools = data.get("pending_tool_requests", [])
            pending_tools.append({
                "proposal_id": proposal.id,
                "department": proposal.target,
                "recommended_tools": proposal.recommended_tools,
                "recommended_mcps": proposal.recommended_mcps,
                "reasoning": proposal.reasoning[:300],
            })
            data["pending_tool_requests"] = pending_tools
            output = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)
            path.write_text(output)
            return {"applied": True, "message": f"Tool request logged: {proposal.summary}"}

        elif proposal.type == ProposalType.NEEDS_CREDENTIALS:
            pending_creds = data.get("pending_credential_requests", [])
            pending_creds.append({
                "proposal_id": proposal.id,
                "department": proposal.target,
                "credential_needs": proposal.credential_needs,
                "reasoning": proposal.reasoning[:300],
            })
            data["pending_credential_requests"] = pending_creds
            output = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)
            path.write_text(output)
            return {"applied": True, "message": f"Credential request logged: {proposal.summary}"}

        else:
            return {"applied": False, "message": f"Cannot auto-apply {proposal.type.value} yet"}

        # Preserve YAML formatting: use block style
        output = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)
        path.write_text(output)

        return {"applied": True, "message": f"Applied {proposal.id}: {proposal.summary}"}

    except Exception as exc:
        return {"applied": False, "message": f"Error: {exc}"}
