"""Observability + budget abort + human approval prompt.

Three concerns:
  1. Append-only audit log (step_callback).
  2. Token-budget abort — raises BudgetExceeded to stop a runaway.
  3. Terminal approval prompt for gated tools.

The approval gate itself lives in tools.py (GatedToolBase); spawn.py wires
approval_fn into those tools based on tier policy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_DIR = Path("./_audit_logs")


# ═══════════════════════════════════════════════════════════════════════════════
# Shared exception — imported by spawn.py
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetExceeded(Exception):
    """Raised when cumulative tokens exceed the per-agent or per-run budget."""


class LoopDetected(Exception):
    """Raised when an agent repeats the same (tool, input) action too many times.

    Catches the failure the token budget can't: a *cheap* loop. Cache-hit
    re-feeds keep token counts low while an agent re-issues an identical tool
    call (e.g. re-fetching the same URL), so the budget cap may never trip even
    as the run spins. This is MAST's top failure mode (Step Repetition, 15.7%),
    and unlike a budget abort it names the offending action.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Chain-level token budget
# ═══════════════════════════════════════════════════════════════════════════════

class RunBudget:
    """A token ceiling shared across every role in a single spawn run.

    The per-role ``budget_llm`` cap is enforced on each role's own LLM instance,
    so an N-step chain has an effective ceiling of N × per_role_cap with nothing
    watching the aggregate (a 4-member chain at 150K each = a 600K run). RunBudget
    closes that gap: each budgeted LLM call adds its token *delta* here and aborts
    the whole run if the shared total exceeds ``cap``.
    """

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.used = 0

    def add(self, delta: int, role_name: str) -> None:
        self.used += max(0, delta)
        if self.used > self.cap:
            raise BudgetExceeded(
                f"Run budget exceeded: {self.used} real tokens > {self.cap} "
                f"chain cap (overflowed while running role '{role_name}'). "
                f"Run aborted."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Audit log
# ═══════════════════════════════════════════════════════════════════════════════

def make_audit_callback(role_name: str, run_id: str, *, max_repeats: int = 4):
    """Create a step_callback that logs every agent step and detects loops.

    Appends each step to a JSONL audit log, and tracks how often each distinct
    ``(tool, tool_input)`` action recurs within this agent's reasoning loop.
    After the same action fires more than ``max_repeats`` times, raises
    ``LoopDetected`` to abort the run with the offending signature named.
    """
    audit_log = AUDIT_DIR / f"{run_id}.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    action_counts: dict[str, int] = {}

    def _log_step(step_output: Any) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        record: dict[str, Any] = {"ts": ts, "run_id": run_id, "role": role_name}

        if hasattr(step_output, "tool") and step_output.tool:
            tool_input = str(getattr(step_output, "tool_input", ""))
            record.update({
                "type": "action",
                "thought": getattr(step_output, "thought", ""),
                "tool": step_output.tool,
                "tool_input": tool_input,
            })
            sig = f"{step_output.tool}::{tool_input}"
            action_counts[sig] = action_counts.get(sig, 0) + 1
            if action_counts[sig] > max_repeats:
                with audit_log.open("a") as f:
                    f.write(json.dumps({**record, "type": "loop_detected",
                                        "repeats": action_counts[sig]}) + "\n")
                raise LoopDetected(
                    f"Loop detected: role '{role_name}' issued the same action "
                    f"'{step_output.tool}' with identical input {action_counts[sig]} "
                    f"times (>{max_repeats}). Run aborted. Input: {tool_input[:200]}"
                )
        elif hasattr(step_output, "output"):
            record.update({
                "type": "finish",
                "thought": getattr(step_output, "thought", ""),
                "output": str(step_output.output)[:2000],
            })
        else:
            record.update({
                "type": "unknown",
                "content": str(step_output)[:2000],
            })

        with audit_log.open("a") as f:
            f.write(json.dumps(record) + "\n")

    return _log_step


def make_task_callback(run_id: str):
    """Create a task_callback that logs each completed task to the same JSONL log.

    step_callback only fires during multi-step/tool reasoning loops — a tool-less
    agent that answers in one shot never triggers it. The Crew-level task_callback
    fires once per completed task regardless, guaranteeing an audit record.
    """
    audit_log = AUDIT_DIR / f"{run_id}.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)

    def _log_task(task_output: Any) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        agent = getattr(task_output, "agent", "") or ""
        record = {
            "ts": ts,
            "run_id": run_id,
            "role": str(agent),
            "type": "task",
            "name": getattr(task_output, "name", "") or "",
            "output": str(getattr(task_output, "raw", ""))[:2000],
        }
        with audit_log.open("a") as f:
            f.write(json.dumps(record) + "\n")

    return _log_task


# ═══════════════════════════════════════════════════════════════════════════════
# Token budget
# ═══════════════════════════════════════════════════════════════════════════════

def make_budget_callback(role_name: str, max_tokens: int):
    """Step callback that aborts if estimated token usage exceeds max_tokens.

    Estimates tokens as len(text)//4 from agent outputs/thoughts. This ignores
    prompt tokens and re-fed context, so real usage may exceed the estimate.
    Set conservatively and lean on max_iter as the primary brake.
    """
    _tokens: list[int] = [0]

    def _check_budget(step_output: Any) -> None:
        text = ""
        if hasattr(step_output, "output"):
            text = str(step_output.output)
        elif hasattr(step_output, "thought"):
            text = str(getattr(step_output, "thought", ""))
        _tokens[0] += max(1, len(text) // 4)

        if _tokens[0] > max_tokens:
            raise BudgetExceeded(
                f"Budget exceeded: {_tokens[0]} estimated tokens > {max_tokens} "
                f"cap for role '{role_name}'. Run aborted."
            )

    return _check_budget


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal approval
# ═══════════════════════════════════════════════════════════════════════════════

def cli_approval(role_name: str, tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Terminal approval prompt. Replace with Slack/email/webhook for production."""
    print(f"\n[APPROVAL] {role_name} wants to run '{tool_name}':")
    print(f"           {json.dumps(tool_input)[:500]}")
    answer = input("           approve? [y/N] ").strip().lower()
    return answer == "y"
