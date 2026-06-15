"""Cross-department handoffs — the artifact bus that makes departments a company.

Departments publish artifacts (reports, signals, deploy requests) to a
shared bus.  Other departments subscribe to artifact types.  When a
subscription matches, the subscriber department is auto-triggered with
the source artifact as context.

This is the final piece that connects departments — without it, each
department is an isolated cron job.  With it, they form a connected org.

Design:
  - HandoffRule: declarative trigger (YAML-configurable).
  - HandoffBus: publish/subscribe backed by OrgMemory.
  - publish(): called after a department run completes.
  - check_triggers(): called by the scheduler, spawns follow-up work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# ── Handoff rule (YAML-configurable) ──────────────────────────────────────────


class HandoffRule(BaseModel):
    """A rule that triggers one department when another publishes an artifact.

    Example YAML::

        handoffs:
          - from: finance
            artifact_type: risk_report
            to: legal
            auto_trigger: true
            sop: review_publish_action
    """

    from_department: str = Field(alias="from")
    artifact_type: str
    to_department: str = Field(alias="to")
    auto_trigger: bool = True
    sop: str | None = None  # SOP name to run in the target department
    require_owner: bool = False
    note: str = ""


# ── Handoff artifact ──────────────────────────────────────────────────────────


@dataclass
class HandoffArtifact:
    """A published artifact on the bus."""

    id: str
    from_department: str
    artifact_type: str
    run_id: str
    summary: str
    payload: str
    status: str
    token_usage: dict[str, int] | None = None
    created_at: str = ""


# ── Handoff bus ───────────────────────────────────────────────────────────────


class HandoffBus:
    """Publish/subscribe artifact bus backed by OrgMemory.

    Usage::

        bus = HandoffBus(org)
        bus.publish("finance", "risk_report", result.envelope, result.run_id)
        triggered = bus.check_triggers()  # returns list of (rule, dept) to spawn
    """

    def __init__(self, org: Any):
        self.org = org
        self.memory = org.use_memory()
        self.rules: list[HandoffRule] = []

    def add_rule(self, rule: HandoffRule) -> None:
        self.rules.append(rule)

    def load_rules_from_org(self) -> None:
        """Load handoff rules from org.handoffs if present."""
        handoffs = getattr(self.org, "handoffs", None)
        if handoffs:
            for h in handoffs:
                if isinstance(h, dict):
                    self.rules.append(HandoffRule.model_validate(h))
                elif isinstance(h, HandoffRule):
                    self.rules.append(h)

    def publish(
        self,
        from_department: str,
        artifact_type: str,
        envelope: Any,
        run_id: str,
        token_usage: dict[str, int] | None = None,
    ) -> HandoffArtifact:
        """Publish an artifact to the bus. Recorded in OrgMemory."""
        import uuid
        from datetime import datetime, timezone

        aid = f"artifact-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        artifact = HandoffArtifact(
            id=aid,
            from_department=from_department,
            artifact_type=artifact_type,
            run_id=run_id,
            summary=getattr(envelope, "summary", "")[:1000],
            payload=getattr(envelope, "payload", ""),
            status=getattr(envelope, "status", "unknown"),
            token_usage=token_usage,
            created_at=now,
        )

        # Store in preferences as a JSON list keyed by artifact type
        key = f"handoff:{artifact_type}"
        existing = self.memory.get_preference(key, [])
        existing.append({
            "id": artifact.id,
            "from": artifact.from_department,
            "type": artifact.artifact_type,
            "run_id": artifact.run_id,
            "summary": artifact.summary[:500],
            "status": artifact.status,
            "created_at": artifact.created_at,
        })
        # Keep last 100 per type
        if len(existing) > 100:
            existing = existing[-100:]
        self.memory.set_preference(key, existing)

        return artifact

    def check_triggers(
        self,
        from_department: str | None = None,
        artifact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find matching handoff rules that should be triggered.

        Returns list of {"rule": HandoffRule, "department": Department, "artifact": HandoffArtifact}
        """
        triggered: list[dict[str, Any]] = []

        for rule in self.rules:
            if from_department and rule.from_department != from_department:
                continue
            if artifact_type and rule.artifact_type != artifact_type:
                continue
            if not rule.auto_trigger:
                continue

            target_dept = self.org.find_department(rule.to_department)
            if target_dept is None:
                continue

            # Get the latest artifact matching this rule
            key = f"handoff:{rule.artifact_type}"
            artifacts = self.memory.get_preference(key, [])
            matching = [
                a for a in artifacts
                if a.get("from") == rule.from_department
            ]
            latest = matching[-1] if matching else None

            triggered.append({
                "rule": rule,
                "department": target_dept,
                "latest_artifact": latest,
            })

        return triggered

    def get_pending_artifacts(
        self, department: str, artifact_type: str | None = None, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get artifacts relevant to a department (incoming handoffs)."""
        results: list[dict[str, Any]] = []
        for rule in self.rules:
            if rule.to_department != department:
                continue
            if artifact_type and rule.artifact_type != artifact_type:
                continue
            key = f"handoff:{rule.artifact_type}"
            artifacts = self.memory.get_preference(key, [])
            for a in artifacts:
                if a.get("from") == rule.from_department:
                    a["_rule"] = rule.model_dump()
                    results.append(a)
        return results[-limit:]

    def recent_activity(self, limit: int = 20) -> list[dict[str, Any]]:
        """All recent handoff activity across departments."""
        # Scan all handoff:* keys
        all_artifacts: list[dict[str, Any]] = []
        for rule in self.rules:
            key = f"handoff:{rule.artifact_type}"
            artifacts = self.memory.get_preference(key, [])
            for a in artifacts:
                a["_artifact_type"] = rule.artifact_type
                all_artifacts.append(a)
        all_artifacts.sort(key=lambda a: a.get("created_at", ""), reverse=True)
        return all_artifacts[:limit]

    def execute_trigger(
        self,
        rule: HandoffRule,
        *,
        approval_fn: Any | None = None,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Execute a triggered handoff — spawn the target department.

        Returns the spawn result or error info.
        """
        from .departments import spawn_department
        from .contracts import TaskBrief

        target_dept = self.org.find_department(rule.to_department)
        if target_dept is None:
            return {"error": f"Department '{rule.to_department}' not found"}

        source_dept = self.org.find_department(rule.from_department)
        source_name = rule.from_department

        # Get latest artifact for context
        key = f"handoff:{rule.artifact_type}"
        artifacts = self.memory.get_preference(key, [])
        matching = [a for a in artifacts if a.get("from") == source_name]
        latest = matching[-1] if matching else {}

        if rule.sop and target_dept.find_sop(rule.sop):
            brief = target_dept.find_sop(rule.sop).brief
        else:
            brief = TaskBrief(
                objective=(
                    f"Review the following artifact from the {source_name} department.\n\n"
                    f"**Artifact type**: {rule.artifact_type}\n"
                    f"**Summary**: {latest.get('summary', 'No summary available')}\n"
                    f"**Status**: {latest.get('status', 'unknown')}\n\n"
                    f"Apply your department's review process. Return a verdict."
                ),
                expected_output="A structured review with verdict and specific findings.",
            )

        try:
            result = spawn_department(
                target_dept,
                brief,
                approval_fn=approval_fn,
                verbose=verbose,
            )
            return {
                "triggered": True,
                "from": rule.from_department,
                "to": rule.to_department,
                "artifact_type": rule.artifact_type,
                "spawn_status": result.envelope.status,
                "summary": result.envelope.summary[:300],
                "token_usage": result.token_usage,
            }
        except Exception as exc:
            return {
                "triggered": False,
                "error": str(exc),
            }
