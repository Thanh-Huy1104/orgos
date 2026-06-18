"""Concrete agent tools — the hands that agents use to act.

  - BashTool: shell command execution behind an approval gate.

The tool *framework* (``GatedToolBase``, ``ApprovalFn``) lives in the engine at
:mod:`orgos.spawn.toolbase`; tool *categories* used for tier enforcement
("read", "sandbox", "compute", "publish", "orchestrate") live in
:mod:`orgos.spawn.contracts`.
"""

from __future__ import annotations

import subprocess

from pydantic import BaseModel, Field

from orgos.spawn.toolbase import GatedToolBase


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
