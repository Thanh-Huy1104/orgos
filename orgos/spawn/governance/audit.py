"""Observability + budget abort + human approval prompt.

Three concerns:
  1. Append-only audit log (step_callback).
  2. Token-budget abort — raises BudgetExceeded to stop a runaway.
  3. Terminal approval prompt for gated tools.

The approval gate itself lives in tools.py (GatedToolBase); spawn.py wires
approval_fn into those tools based on tier policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..redaction import scrub_secrets

# Configurable via env so trails don't scatter per working directory.
AUDIT_DIR = Path(os.environ.get("ORGOS_AUDIT_DIR", "./_audit_logs"))

# What append_record scrubs before persisting: "secrets" (default —
# high-precision rules only: keys/JWT/PEM), "all" (adds the shape-based PII
# rules), or "off".
AUDIT_REDACTION = os.environ.get("ORGOS_AUDIT_REDACTION", "secrets")

_GENESIS = "genesis"

# Appends are serialized in-process and the last chain hash is cached per
# log path — this makes the chain safe under threads and O(1) per append.
# Cross-PROCESS appends to one run_id remain unsupported (documented): two
# processes can still fork the chain. Single-writer-per-run_id is the
# contract.
_append_lock = threading.Lock()
_last_chain_cache: dict[Path, str] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Hash-chained append + verification
# ═══════════════════════════════════════════════════════════════════════════════

def _canonical(record: dict[str, Any]) -> str:
    """Deterministic serialization of a record, excluding its own chain field."""
    payload = {k: v for k, v in record.items() if k != "chain"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _chain_hash(prev_chain: str, record: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_chain.encode())
    h.update(_canonical(record).encode())
    return h.hexdigest()


def _last_chain(audit_log: Path) -> str:
    """The chain value of the log's last record, or genesis for a new log."""
    if not audit_log.exists():
        return _GENESIS
    last = ""
    with audit_log.open() as f:
        for line in f:
            if line.strip():
                last = line
    if not last:
        return _GENESIS
    try:
        return json.loads(last).get("chain", _GENESIS)
    except json.JSONDecodeError:
        return _GENESIS


def _scrub_value(value: Any) -> Any:
    """Recursively scrub string leaves of a record per AUDIT_REDACTION."""
    if isinstance(value, str):
        if AUDIT_REDACTION == "all":
            from ..redaction import scrub  # noqa: PLC0415

            return scrub(value)
        return scrub_secrets(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


def append_record(run_id: str, record: dict[str, Any]) -> None:
    """Append one record to the run's audit log, extending the hash chain.

    Every record gets ``chain = sha256(prev_chain + canonical(record))``,
    with a fixed genesis value for the first record. Editing, deleting, or
    reordering any historical line breaks recomputation for every line
    after it — see :func:`verify_trail`.

    Secrets are scrubbed from string fields before hashing/persisting
    (``ORGOS_AUDIT_REDACTION``: "secrets" default / "all" / "off") —
    scrubbing happens *before* the chain hash so verification stays valid.

    Thread-safe within one process (serialized, cached last-chain). NOT
    safe for multiple *processes* appending to one run_id — that remains a
    documented limitation.
    """
    audit_log = AUDIT_DIR / f"{run_id}.jsonl"
    if AUDIT_REDACTION != "off":
        record = _scrub_value(dict(record))
    else:
        record = dict(record)
    with _append_lock:
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        prev = _last_chain_cache.get(audit_log)
        if prev is None:
            prev = _last_chain(audit_log)
        record["chain"] = _chain_hash(prev, record)
        with audit_log.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        _last_chain_cache[audit_log] = record["chain"]


def verify_trail(run_id: str) -> tuple[bool, int | None]:
    """Recompute a trail's hash chain. Returns (ok, first_bad_line).

    ``first_bad_line`` is 1-indexed; None when the trail verifies (an
    absent or empty log verifies trivially — there is nothing to tamper).
    Trails written before hash-chaining (records without a ``chain``
    field) fail at their first unchained line.
    """
    audit_log = AUDIT_DIR / f"{run_id}.jsonl"
    if not audit_log.exists():
        return True, None
    prev = _GENESIS
    with audit_log.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return False, lineno
            claimed = record.get("chain")
            if claimed != _chain_hash(prev, record):
                return False, lineno
            prev = claimed
    return True, None


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


class ToolBudgetExceeded(Exception):
    """Raised when an agent makes more tool calls than its brief's call budget.

    The cure for vague delegation (Anthropic): a brief should cap how many tool
    calls a worker may spend so it can't fan out unboundedly. Distinct from
    LoopDetected — this trips even on *varied* calls once the total exceeds the
    budget (e.g. fetching 20 different URLs when the brief allotted 6).
    """


# Delegation depth registry: run_id -> {role_name: ordinal}.
# Process-wide; entries are not cleared automatically — tests clear it.
_depth_registry: dict[str, dict[str, int]] = {}


class DelegationDepthExceeded(RuntimeError):
    """Raised when a spawn would push delegation past the configured depth cap.

    The cap exists to prevent runaway recursive sub-spawning, which is MAST's
    inter-agent misalignment failure mode (Cemri et al., arXiv:2503.13657).
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

def make_audit_callback(
    role_name: str,
    run_id: str,
    *,
    max_repeats: int = 4,
    max_actions: int | None = None,
    max_depth: int = 2,
):
    """Create a step_callback that logs every agent step and bounds its actions.

    Appends each step to a JSONL audit log, then enforces two action limits:
      - loop guard: if the same ``(tool, tool_input)`` action recurs more than
        ``max_repeats`` times, raise ``LoopDetected`` (catches cheap loops).
      - call budget: if total tool calls exceed ``max_actions`` (the brief's
        ``tool_call_budget``, when set), raise ``ToolBudgetExceeded`` — this
        trips even on *varied* calls (the cure for unbounded fan-out).
    Also enforces a delegation-depth cap: each new role within the same run
    increments the depth counter; if the counter exceeds ``max_depth``,
    raises ``DelegationDepthExceeded`` before any agent runs.
    """
    by_run = _depth_registry.setdefault(run_id, {})
    if role_name not in by_run:
        by_run[role_name] = len(by_run) + 1
        if by_run[role_name] > max_depth:
            raise DelegationDepthExceeded(
                f"Depth {by_run[role_name]} > max_depth={max_depth} for "
                f"run_id={run_id!r} role={role_name!r}"
            )
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
                append_record(run_id, {**record, "type": "loop_detected",
                                       "repeats": action_counts[sig]})
                raise LoopDetected(
                    f"Loop detected: role '{role_name}' issued the same action "
                    f"'{step_output.tool}' with identical input {action_counts[sig]} "
                    f"times (>{max_repeats}). Run aborted. Input: {tool_input[:200]}"
                )
            total_actions = sum(action_counts.values())
            if max_actions is not None and total_actions > max_actions:
                append_record(run_id, {**record, "type": "tool_budget_exceeded",
                                       "total_actions": total_actions})
                raise ToolBudgetExceeded(
                    f"Tool-call budget exceeded: role '{role_name}' made "
                    f"{total_actions} tool calls (>{max_actions} allotted by the "
                    f"brief). Run aborted."
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

        append_record(run_id, record)

    return _log_step


def trace_tool(tool: Any, role_name: str, run_id: str) -> Any:
    """Wrap a tool's ``_run`` so every call is logged to the run's audit log.

    CrewAI 1.14's native function-calling executor batches tool calls and never
    routes them through ``step_callback`` as ``AgentAction`` steps, so the audit
    log captured zero tool calls. We intercept at the tool layer instead — this
    is version-proof and also records the tool's *output*, which step_callback
    never gave us. ``to_structured_tool()`` captures ``self._run`` at kickoff, so
    shadowing the bound method on the instance (before the crew runs) is enough.
    """
    audit_log = AUDIT_DIR / f"{run_id}.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    tool_name = getattr(tool, "name", tool.__class__.__name__)
    original = tool._run

    def _traced(*args: Any, **kwargs: Any) -> Any:
        ts = datetime.now(timezone.utc).isoformat()
        # Native calls pass kwargs; fall back to positional for ReAct.
        tool_input = kwargs if kwargs else (args[0] if len(args) == 1 else list(args))
        try:
            result = original(*args, **kwargs)
            ok, preview = True, str(result)[:1200]
            return result
        except Exception as exc:  # noqa: BLE001 — never let tracing swallow/alter behaviour
            ok, preview = False, f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                record = {
                    "ts": ts, "run_id": run_id, "role": role_name,
                    "type": "tool_call", "tool": tool_name,
                    "tool_input": _safe_json(tool_input), "ok": ok,
                    "output_preview": preview,
                }
                append_record(run_id, record)
            except Exception:  # noqa: BLE001 — logging must never break the run
                pass

    object.__setattr__(tool, "_run", _traced)
    return tool


def _safe_json(value: Any) -> Any:
    """Coerce a tool input into something JSON-serialisable for the audit log."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)[:1000]


_TRAIL_TYPES = frozenset({"tool_call", "approval", "aborted"})


def read_trail(run_id: str) -> list[dict[str, Any]]:
    """Read a run's action trail from its audit log.

    Returns the ordered ``tool_call``, ``approval`` (grants AND denials —
    the records a reviewer cares most about), and ``aborted`` records.
    Empty list if the log is missing (e.g. a run that made no tool calls,
    or was never executed).
    """
    audit_log = AUDIT_DIR / f"{run_id}.jsonl"
    if not audit_log.exists():
        return []
    trail: list[dict[str, Any]] = []
    with audit_log.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") in _TRAIL_TYPES:
                trail.append(rec)
    return trail


def recent_trails(n: int = 25) -> list[dict[str, Any]]:
    """List recent runs that have an audit log, newest first.

    Each entry summarises one run's tool trail — run_id, when it last ran, and how
    many tool calls it made (and how many succeeded) — so a UI can browse runs and
    drill into any one via ``read_trail``.
    """
    if not AUDIT_DIR.exists():
        return []
    files = sorted(AUDIT_DIR.glob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    out: list[dict[str, Any]] = []
    for p in files:
        calls = [r for r in read_trail(p.stem) if r.get("type") == "tool_call"]
        out.append({
            "run_id": p.stem,
            "ts": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            "tool_calls": len(calls),
            "ok": sum(1 for c in calls if c.get("ok")),
        })
    return out


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
        append_record(run_id, record)

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
