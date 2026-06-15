"""Tools for orgos — the hands that agents use to act.

Provides:
  - GatedToolBase: BaseTool subclass that requires recorded human approval before
    executing. Fail-closed: if _gate_required is True and no approval_fn is set,
    every execution is denied.
  - BashTool: shell command execution with approval gate.

Tool categories (tool_category) for tier enforcement in spawn.py:
  "read", "sandbox", "compute", "publish", "orchestrate"
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr


ApprovalFn = Callable[[str, str, dict[str, Any]], bool]


class GatedToolBase(BaseTool):
    """Base class for tools that require human approval before execution.

    Fail-closed: if _gate_required is True (set by spawn's _wire_gates) and
    no approval_fn is configured, every execution is denied. Spawn refuses to
    launch a role whose tier requires gating but has no approval_fn.
    """

    approval_fn: ApprovalFn | None = Field(default=None, exclude=True)
    _agent_role: str = PrivateAttr(default="unknown")
    _gate_required: bool = PrivateAttr(default=False)

    def _check_gate(self, tool_input: dict[str, Any]) -> bool:
        """Returns True if the action is permitted, False if denied."""
        if self.approval_fn is not None:
            return self.approval_fn(self._agent_role, self.name, tool_input)
        # No approval surface — fail closed if gating is required
        return not self._gate_required

    def _run(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError("Subclass must implement _run")


# ── Bash tool ────────────────────────────────────────────────────────────────

class _BashInput(BaseModel):
    command: str = Field(..., description="The shell command to execute.")
    working_dir: str = Field(default=".", description="Working directory.")
    timeout_sec: int = Field(default=30, description="Max execution time in seconds.")


class BashTool(GatedToolBase):
    """Execute a shell command. Requires human approval before execution.

    NOTE: 'sandbox' here means a locked working directory — this is NOT a
    container/VM sandbox. For production, replace subprocess.run with a
    container executor or chroot jail.
    """

    name: str = "Bash"
    description: str = (
        "Execute a shell command in a locked working directory. "
        "Requires human approval before every execution. "
        "Input: command (string), working_dir (string, optional), timeout_sec (int, optional)."
    )
    args_schema: type[BaseModel] = _BashInput
    tool_category: str = "sandbox"

    def _run(self, command: str, working_dir: str = ".", timeout_sec: int = 30) -> str:
        if not self._check_gate({"command": command, "working_dir": working_dir}):
            return (
                f"DENIED: Bash command '{command[:80]}' requires human approval. "
                "No approval was granted."
            )

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=working_dir, timeout=timeout_sec,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Command timed out after {timeout_sec}s"
        except Exception as exc:
            return f"ERROR: {exc}"
