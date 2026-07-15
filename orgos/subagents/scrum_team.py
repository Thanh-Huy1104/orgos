"""Five-role autonomous scrum team factories.

These factories load agent identities from persona files under agents/
using Plan 1's layered loader. Each factory accepts an optional model override.

Roles:
  po_role()            — Product Owner (Morgan, PO_Agent)
  scrum_master_role()  — Scrum Master (River, SM_Agent)
  architect_role()     — Architect (Architect_Agent) — delivery worker
  test_role()          — Test (Test_Agent) — delivery worker
  devsecops_role()     — DevSecOps (DevSecOps_Agent) — delivery worker

For Plan 5 dual-team benchmarking, these factories point to agents/ by default
but can be swapped to a different agents_root via the module-level variable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orgos.spawn import RoleSpec

_AGENTS_ROOT = Path(__file__).resolve().parent.parent.parent / "agents"


def _load_agent(name: str, model: str | None = None) -> RoleSpec:
    role = RoleSpec.from_agent_dir(_AGENTS_ROOT, name)
    if model is not None:
        role.model = model
    return role


def po_role(model: str | None = None) -> RoleSpec:
    return _load_agent("po", model)


def scrum_master_role(model: str | None = None) -> RoleSpec:
    return _load_agent("scrum_master", model)


def architect_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    role = _load_agent("architect", model)
    if extra_tools:
        role.tools = list(extra_tools)
    return role


def test_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    role = _load_agent("test", model)
    if extra_tools:
        role.tools = list(extra_tools)
    return role


def devsecops_role(
    model: str | None = None, extra_tools: list[Any] | None = None,
) -> RoleSpec:
    role = _load_agent("devsecops", model)
    if extra_tools:
        role.tools = list(extra_tools)
    return role
