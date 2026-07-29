"""Tool framework primitives for the spawn engine.

``GatedToolBase`` is the base class for any tool whose execution must pass a
human-approval gate. The engine's tier policy (see
:mod:`orgos.spawn.governance.contracts`) decides *which* tools need gating;
:func:`orgos.spawn.governance.engine._wire_gates` then injects the approval
callback into each gated tool before the crew runs.

This module is intentionally dependency-light (only CrewAI + pydantic) so the
engine has no import edge into any consumer's concrete tools. Concrete tools
subclass ``GatedToolBase`` (or plain CrewAI ``BaseTool``) in the consumer app.
"""

from __future__ import annotations

from typing import Any, Callable

from crewai.tools import BaseTool
from pydantic import Field, PrivateAttr

ApprovalFn = Callable[[str, str, dict[str, Any]], bool]


class GatedToolBase(BaseTool):
    """Base class for tools that require human approval before execution.

    Fail-closed: if ``_gate_required`` is True (set by the engine's
    ``_wire_gates``) and no ``approval_fn`` is configured, every execution is
    denied. The engine refuses to launch a role whose tier requires gating but
    has no ``approval_fn``, so an ungated-but-required tool can never run.
    """

    approval_fn: ApprovalFn | None = Field(default=None, exclude=True)
    _agent_role: str = PrivateAttr(default="unknown")
    _gate_required: bool = PrivateAttr(default=False)

    def _check_gate(self, tool_input: dict[str, Any]) -> bool:
        """Return True if the action is permitted, False if denied."""
        if self.approval_fn is not None:
            return self.approval_fn(self._agent_role, self.name, tool_input)
        # No approval surface — fail closed if gating is required.
        return not self._gate_required

    def _run(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError("Subclass must implement _run")
