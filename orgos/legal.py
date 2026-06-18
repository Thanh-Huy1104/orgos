"""Legal / compliance — the cross-cutting veto layer.

The legal department is an LLM-powered reviewer: every publish-class action
is sent to the legal-reviewer agent, which reasons over the full policy set
and returns a structured verdict (approved/denied/needs_changes).

A fast deterministic pre-filter catches obvious hard-denies (rm -rf,
passwords) before spending tokens on the LLM.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Policy rules ──────────────────────────────────────────────────────────────


class LegalPolicyRule(BaseModel):
    """A single compliance rule.  Injected into the legal reviewer's context."""

    id: str
    title: str
    rule: str  # the rule text the LLM reasons about
    verdict: Literal["deny", "require_owner", "warn"] = "require_owner"
    examples: str = ""
    keywords: str = ""  # comma-separated trigger words for the pre-filter


class LegalPolicy(BaseModel):
    """The legal department's policy manual."""

    name: str = "Default Compliance Policy"
    version: str = "1.0.0"
    rules: list[LegalPolicyRule] = Field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Render the full policy set as markdown for the legal agent's context."""
        lines = [
            f"# {self.name} (v{self.version})",
            "",
            "You are a compliance reviewer. Apply these rules to every proposed action:",
            "",
        ]
        for r in self.rules:
            verdict_icon = {"deny": "🚫 BLOCK", "require_owner": "👤 OWNER", "warn": "⚠️ WARN"}[r.verdict]
            lines.append(f"## {r.id}: {r.title}  [{verdict_icon}]")
            lines.append(f"**Rule**: {r.rule}")
            if r.examples:
                lines.append(f"**Examples**: {r.examples}")
            lines.append("")
        lines.extend([
            "## Your task",
            "1. Read the proposed action carefully.",
            "2. Check it against EVERY rule above — cite specific rule IDs.",
            "3. Return a verdict: **approved**, **denied** (cite which rule), or **needs_changes** (specify what).",
            "4. If the owner must approve, say 'requires_owner' and cite the rule.",
            "5. Be precise. A denied action must cite a specific policy ID. No vague denials.",
        ])
        return "\n".join(lines)

    def pre_filter(self, text: str) -> list[str]:
        """Catch obvious hard-denies by matching keywords in the action text.

        This is the zero-token gate — it checks each deny-verdict rule's
        keywords against the proposed action.  If a keyword matches, the
        action is denied immediately without calling the LLM.

        For the LLM to catch more subtle violations (context, intent, risk),
        use legal_review_with_agent().
        """
        text_lower = text.lower()
        hard_denies: list[str] = []

        for r in self.rules:
            if r.verdict != "deny":
                continue
            if not r.keywords:
                continue
            for kw in r.keywords.split(","):
                kw = kw.strip().lower()
                if kw and kw in text_lower:
                    hard_denies.append(f"[{r.id}] {r.title}: matched keyword '{kw}'")
                    break  # one keyword match is enough per rule

        return hard_denies


# ── Policies ──────────────────────────────────────────────────────────────────


DEFAULT_POLICY = LegalPolicy(
    name="OrgOS Default Compliance Policy",
    version="1.0.0",
    rules=[
        LegalPolicyRule(
            id="LGL-001",
            title="Publishing Requires Owner Approval",
            rule="Any action that publishes data, deploys code, sends external communications, or writes to production systems must have explicit owner approval before execution.",
            verdict="require_owner",
            examples="Deploying to production, sending a newsletter, posting to social media, writing to a production database.",
        ),
        LegalPolicyRule(
            id="LGL-002",
            title="No Destructive Operations",
            rule="Destructive operations — deleting data, removing files, dropping tables, force-pushing, or running destructive shell commands (rm -rf, DROP TABLE, etc.) — are strictly prohibited unless explicitly authorized by the owner in writing for the specific operation.",
            verdict="deny",
            examples="rm -rf /important, DROP TABLE users, git push --force to main, formatting a disk.",
            keywords="rm -rf, DROP TABLE, drop table, git push --force, force push, format, truncate, DELETE FROM, shred, wipe",
        ),
        LegalPolicyRule(
            id="LGL-003",
            title="Financial Transactions Require Owner",
            rule="Any action involving financial transactions — trading, transferring funds, executing orders, deploying capital, or modifying financial allocations — requires explicit owner sign-off before execution. Proposing or analyzing is fine; executing is not.",
            verdict="require_owner",
            examples="Buying/selling securities, transferring money between accounts, allocating capital to a strategy, executing a smart contract that moves funds.",
        ),
        LegalPolicyRule(
            id="LGL-004",
            title="External API Writes Require Review",
            rule="Writing to external APIs (POST, PUT, PATCH, DELETE) — especially webhooks, third-party services, or cloud infrastructure — requires owner approval. Read-only API calls (GET) are permitted without review.",
            verdict="require_owner",
            examples="POSTing to Slack webhook, PUT to update a DNS record, DELETE from a cloud bucket.",
        ),
        LegalPolicyRule(
            id="LGL-005",
            title="User Data and PII Protection",
            rule="Accessing, processing, or transmitting user data, personally identifiable information (PII), passwords, secrets, or authentication tokens is prohibited without explicit data-handling authorization. This includes reading, writing, or forwarding such data.",
            verdict="deny",
            examples="Reading a file with email addresses, sending PII in a notification, logging passwords, forwarding user data to an external service.",
            keywords="password, PII, personally identifiable, user data, secret, token, credential, email address, SSN, social security, credit card, API key, auth token, private key",
        ),
        LegalPolicyRule(
            id="LGL-006",
            title="Model Training and Fine-Tuning Requires Owner",
            rule="Any action that trains, fine-tunes, or modifies machine learning models — including uploading training data, adjusting model weights, or changing model configurations in production — requires owner approval.",
            verdict="require_owner",
            examples="Fine-tuning a production model, uploading a new training dataset, changing model hyperparameters in prod.",
        ),
        LegalPolicyRule(
            id="LGL-007",
            title="Infrastructure Changes Require Owner",
            rule="Modifying infrastructure — creating/deleting VMs, changing firewall rules, updating DNS, modifying Kubernetes deployments, or altering cloud resource configurations — requires owner approval.",
            verdict="require_owner",
            examples="Creating a new EC2 instance, modifying security group rules, scaling a cluster, changing IAM policies.",
        ),
        LegalPolicyRule(
            id="LGL-008",
            title="No Circumvention of Review Process",
            rule="Attempting to bypass the legal review process — splitting a prohibited action into smaller steps, using indirect methods, encoding commands, or social engineering — is itself a policy violation and will be denied.",
            verdict="deny",
            examples="Splitting 'deploy and trade' into two separate requests, encoding a forbidden command in base64, asking another agent to perform a blocked action.",
            keywords="bypass, circumvent, split into, encode, base64, social engineer, trick, pretend",
        ),
    ],
)


# ── Structured verdict ────────────────────────────────────────────────────────


class LegalVerdict(BaseModel):
    """Structured output from the legal reviewer — enforced by output_pydantic."""

    verdict: Literal["approved", "denied", "needs_changes"] = "approved"
    requires_owner: bool = False
    policy_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    required_changes: str = ""
    risk_level: Literal["low", "medium", "high", "critical"] = "low"


# ── Legal review ──────────────────────────────────────────────────────────────


def legal_review(
    envelope: Any,
    *,
    policy: LegalPolicy | None = None,
) -> dict[str, Any]:
    """Fast deterministic pre-filter — catches obvious hard-denies.

    Does NOT replace the LLM review.  This is the zero-cost gate that
    stops 'rm -rf' and password exposure before any tokens are spent.

    Returns the same shape as the LLM review for uniform handling:
        {"approved": bool, "verdict": str, "denials": [...], "pre_filter": True}
    """
    policy = policy or DEFAULT_POLICY

    summary = getattr(envelope, "summary", "")
    artifacts = " ".join(getattr(envelope, "artifacts", []))
    payload = getattr(envelope, "payload", "")

    denials = policy.pre_filter(f"{summary} {artifacts} {payload}")
    return {
        "approved": len(denials) == 0,
        "verdict": "denied" if denials else "approved",
        "denials": denials,
        "pre_filter": True,
    }


def legal_review_with_agent(
    envelope: Any,
    org: Any,
    *,
    policy: LegalPolicy | None = None,
    approval_fn: Any | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Full legal review — deterministic pre-filter + LLM-powered analysis.

    1. Runs pre_filter() — catches hard-denies instantly (zero tokens).
    2. Spawns the org's legal department with the full policy set in context.
    3. The legal-reviewer agent examines the proposed action, reasons
       over all applicable policies, and returns a structured LegalVerdict.
    4. The verdict is merged with pre-filter results and returned.

    Args:
        envelope: The HandoffEnvelope from the agent proposing the action.
        org: The Org instance (must have a 'legal' department with a
             legal-reviewer agent).
        policy: Custom LegalPolicy (defaults to DEFAULT_POLICY).
        approval_fn: Optional approval callback (not typically needed for review).
        verbose: Pass through to spawn.

    Returns:
        {"approved": bool, "verdict": str, "requires_owner": bool,
         "policy_ids": [...], "reasoning": str, "required_changes": str,
         "risk_level": str, "denials": [...], "reviewer_notes": str}
    """
    policy = policy or DEFAULT_POLICY

    # ── 1. Deterministic pre-filter (zero tokens) ─────────────────────────
    pre = legal_review(envelope, policy=policy)
    if not pre["approved"]:
        pre["requires_owner"] = False
        pre["reviewer_notes"] = (
            f"Pre-filter denied: {'; '.join(pre['denials'])}. LLM review skipped."
        )
        return pre

    # ── 2. Check if legal department exists ───────────────────────────────
    legal_dept = org.find_department("legal") if org else None
    if legal_dept is None:
        pre["requires_owner"] = False
        pre["reviewer_notes"] = "No legal department configured — pre-filter passed."
        return pre

    # ── 3. Inject policy into legal reviewer's system prompt ──────────────
    reviewer = legal_dept.members[0]  # legal-reviewer
    policy_block = policy.to_prompt_block()
    reviewer = reviewer.model_copy(update={
        "system_prompt": (
            f"{policy_block}\n\n"
            f"---\n\n"
            f"{reviewer.system_prompt}"
        ),
    })
    legal_dept.members[0] = reviewer

    # ── 4. Build the review brief ─────────────────────────────────────────
    from .spawn import TaskBrief

    summary = getattr(envelope, "summary", "")
    artifacts = getattr(envelope, "artifacts", [])
    payload = getattr(envelope, "payload", "")
    role = getattr(envelope, "role", "unknown")
    status = getattr(envelope, "status", "unknown")

    review_brief = TaskBrief(
        objective=(
            f"Review this proposed action for policy compliance.\n\n"
            f"**Proposing role**: {role}\n"
            f"**Action status**: {status}\n"
            f"**Summary**: {summary[:800]}\n"
            f"**Artifacts**: {artifacts}\n"
            f"**Payload**: {payload[:800]}\n\n"
            "Apply EVERY policy rule above. For each rule, determine if the "
            "proposed action violates it, requires owner approval, or is compliant. "
            "Cite specific policy IDs (e.g. LGL-001) in your reasoning."
        ),
        expected_output=(
            "A structured legal verdict with: verdict (approved/denied/needs_changes), "
            "requires_owner (bool), policy_ids (list of applicable rule IDs), "
            "reasoning (detailed analysis), required_changes (if needs_changes), "
            "risk_level (low/medium/high/critical)."
        ),
        success_criteria=[
            "Every applicable policy rule is checked and cited by ID",
            "Verdict is specific — denied actions cite which rule they violate",
            "Risk level is assessed",
        ],
    )

    # ── 5. Spawn legal reviewer as solo agent with structured output ─────
    from .spawn import spawn

    # Spawn the reviewer directly (not the department) so we can enforce
    # output_pydantic=LegalVerdict for clean, parsable results.
    # We build a single-agent spawn — no delegation needed for review.
    from .spawn import TaskBrief as TB

    try:
        review_result = spawn(
            reviewer,
            review_brief,
            verbose=verbose,
        )
    except Exception as exc:
        return {
            "approved": False,
            "verdict": "denied",
            "requires_owner": True,
            "policy_ids": [],
            "reasoning": f"Legal review infrastructure error: {exc}",
            "required_changes": "",
            "risk_level": "critical",
            "denials": [f"LEGAL-INFRA: {exc}"],
            "reviewer_notes": f"Legal review failed with error: {exc}",
        }

    ai_env = review_result.envelope
    ai_summary = ai_env.summary

    # ── 6. Parse the AI verdict from the envelope ─────────────────────────
    # The reviewer returns a HandoffEnvelope (not a LegalVerdict directly
    # since the spawn path uses HandoffEnvelope schema).  We extract the
    # verdict fields from the payload and summary.
    try:
        import json
        if ai_env.payload and ai_env.payload.strip():
            ai_data = json.loads(ai_env.payload)
        else:
            ai_data = {}
    except (json.JSONDecodeError, TypeError):
        ai_data = {}

    ai_summary_lower = ai_summary.lower()

    # Determine the verdict from the model's output
    is_denied = (
        "denied" in ai_summary_lower
        or "violat" in ai_summary_lower
        or ai_data.get("verdict") in ("denied", "deny")
        or ai_env.status in ("failed", "blocked")
    )
    is_needs_changes = (
        "needs_changes" in ai_summary_lower
        or ai_data.get("verdict") == "needs_changes"
    )
    is_requires_owner = (
        "requires_owner" in ai_summary_lower
        or "owner approval" in ai_summary_lower
        or "requires owner" in ai_summary_lower
        or ai_data.get("requires_owner", False)
    )

    return {
        "approved": not is_denied and not is_needs_changes,
        "verdict": (
            "denied" if is_denied
            else "needs_changes" if is_needs_changes
            else "approved"
        ),
        "requires_owner": is_requires_owner or (ai_env.status == "completed" and not is_denied),
        "policy_ids": ai_data.get("policy_ids", []),
        "reasoning": ai_data.get("reasoning", ai_summary[:500]),
        "required_changes": ai_data.get("required_changes", ""),
        "risk_level": ai_data.get("risk_level", "medium"),
        "denials": pre.get("denials", []),
        "reviewer_notes": f"LLM review: {ai_summary[:500]}",
    }
