"""Pure tier-policy enforcement over duck-typed tools.

Mirrors the CrewAI engine's ``_enforce_tier`` checks (deny → allow →
category → publish) but is framework-free: a "tool" here is anything with a
``name`` (str) and optionally a ``tool_category`` (str). Used by the
backend-based runner; the CrewAI engine keeps its own copy because its
gate-wiring step is coupled to ``GatedToolBase``.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from .contracts import TIER_POLICY, RoleSpec
from .result import TierViolation


def tool_matches(name: str, pattern: str) -> bool:
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", "unnamed"))
    return str(getattr(tool, "name", tool.__class__.__name__))


def tool_category(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("tool_category", "") or "").lower()
    return str(getattr(tool, "tool_category", "") or "").lower()


def requires_approval(role: RoleSpec, tool: Any) -> bool:
    """True if this tier gates this tool behind human approval."""
    policy = TIER_POLICY[role.tier]
    name = tool_name(tool)
    if tool_category(tool) == "publish":
        return True
    return any(tool_matches(name, p) for p in policy.requires_approval)


def filter_tools_for_tier(
    role: RoleSpec, tools: list[Any], *, has_approval_fn: bool
) -> list[Any]:
    """Validate tools against the role's tier policy; raise TierViolation.

    Same deny/allow/category/publish semantics as the CrewAI engine. The
    gateability check differs: the runner gates at the tool-call boundary
    itself, so instead of requiring GatedToolBase it requires that an
    ``approval_fn`` was supplied whenever any tool needs gating (fail-closed).
    """
    policy = TIER_POLICY[role.tier]
    result: list[Any] = []

    for tool in tools:
        name = tool_name(tool)
        category = tool_category(tool)

        for pat in policy.denied_tools:
            if tool_matches(name, pat):
                raise TierViolation(
                    f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                    f"tool '{name}' — denied by tier (pattern: '{pat}')"
                )

        if policy.allowed_tools != ["*"]:
            if not any(tool_matches(name, p) for p in policy.allowed_tools):
                raise TierViolation(
                    f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                    f"tool '{name}' — not in allowed_tools: {policy.allowed_tools}"
                )

        if policy.allowed_categories is not None:
            if category not in policy.allowed_categories:
                raise TierViolation(
                    f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                    f"tool '{name}' — category '{category or 'unknown'}' "
                    f"not in allowed {policy.allowed_categories}"
                )

        if category == "publish" and not policy.can_publish:
            raise TierViolation(
                f"Role '{role.name}' (tier={role.tier.value}) cannot use "
                f"publish-class tool '{name}' — only publisher tier may publish"
            )

        if requires_approval(role, tool) and not has_approval_fn:
            raise TierViolation(
                f"Role '{role.name}' (tier={role.tier.value}) holds tool "
                f"'{name}' that must be approval-gated, but no approval_fn was "
                f"supplied — refusing to run ungated (fail-closed)."
            )

        result.append(tool)

    return result
