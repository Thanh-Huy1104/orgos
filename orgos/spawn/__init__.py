"""orgos.spawn — governance and cost primitives for agentic apps.

Top-level imports are lazy so that importing e.g. ``orgos.spawn.redaction`` does
not force CrewAI / LiteLLM to load. Access governance primitives via the
subpackage (``from orgos.spawn.governance import spawn``) or via the
convenience getattr below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.2.1"

# Public names re-exported from orgos.spawn.governance on demand.
_GOVERNANCE_EXPORTS = frozenset(
    {
        "CATEGORY_COMPUTE",
        "CATEGORY_ORCHESTRATE",
        "CATEGORY_PUBLISH",
        "CATEGORY_READ",
        "CATEGORY_SANDBOX",
        "TIER_POLICY",
        "GatedToolBase",
        "HandoffEnvelope",
        "PermissionTier",
        "RoleSpec",
        "SpawnResult",
        "TaskBrief",
        "TierPolicy",
        "spawn",
        "spawn_chain",
    }
)


def __getattr__(name: str) -> Any:
    if name in _GOVERNANCE_EXPORTS:
        from orgos.spawn import governance  # noqa: PLC0415 - lazy

        return getattr(governance, name)
    raise AttributeError(f"module 'orgos.spawn' has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover - for editors + mypy only
    from orgos.spawn.governance import (  # noqa: F401
        CATEGORY_COMPUTE,
        CATEGORY_ORCHESTRATE,
        CATEGORY_PUBLISH,
        CATEGORY_READ,
        CATEGORY_SANDBOX,
        TIER_POLICY,
        GatedToolBase,
        HandoffEnvelope,
        PermissionTier,
        RoleSpec,
        SpawnResult,
        TaskBrief,
        TierPolicy,
        spawn,
        spawn_chain,
    )


__all__ = ["__version__", *sorted(_GOVERNANCE_EXPORTS)]
