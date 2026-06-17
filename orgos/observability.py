"""Observability — per-run metrics + MAST failure-mode classification.

The report's central, measurable claim: multi-agent reliability is moved by
system design, not model swaps — and System Design Issues are 44% of failures
(MAST, Cemri et al. 2025). To act on "halt feature work if token/task trends up"
you have to *measure* token/task and *classify* failures.

This module:
  - classify_failure(): maps a failed/degraded HandoffEnvelope to a MAST failure
    mode, using the distinctive diagnostic strings the P0–P2 controls already
    emit (loop, budget, citation gate, malformed handoff).
  - compute_metrics(): per-run record (tokens, tool calls, steps, status,
    failure mode) read from the run's audit log + token usage.
  - record_metrics() / summarize_metrics(): append to metrics.jsonl and
    aggregate it (completion rate, avg/max tokens, failure-mode distribution).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .audit import AUDIT_DIR

METRICS_LOG = AUDIT_DIR / "metrics.jsonl"


# ── MAST failure taxonomy (subset orgos can detect) ───────────────────────────
# code -> (label, category). The full taxonomy has 14 modes in 3 categories;
# these are the ones orgos surfaces deterministically from its own controls.
MAST_MODES: dict[str, tuple[str, str]] = {
    "FM-1.1": ("disobey_task_specification", "Specification & System Design"),
    "FM-1.3": ("step_repetition", "Specification & System Design"),
    "FM-1.5": ("unaware_of_termination", "Specification & System Design"),
    "FM-3.1": ("premature_termination", "Verification & Termination"),
    "FM-3.3": ("incorrect_verification", "Verification & Termination"),
    "EXEC": ("execution_error", "Execution/Infrastructure"),
    "UNKNOWN": ("unclassified", "Unknown"),
}


class FailureMode(BaseModel):
    code: str
    label: str
    category: str

    @classmethod
    def of(cls, code: str) -> "FailureMode":
        label, category = MAST_MODES[code]
        return cls(code=code, label=label, category=category)


def classify_failure(envelope: Any) -> FailureMode | None:
    """Tag a non-completed handoff with a MAST failure mode, or None if it
    completed cleanly. Keys off the diagnostic strings the controls emit.

    Order matters — most specific signal first.
    """
    if getattr(envelope, "status", None) == "completed":
        return None

    text = (
        (getattr(envelope, "summary", "") or "")
        + " "
        + (getattr(envelope, "notes", "") or "")
    ).lower()

    if "loop detected" in text:
        code = "FM-1.3"  # step repetition
    elif "tool-call budget exceeded" in text or "run budget exceeded" in text:
        code = "FM-1.5"  # kept going, never terminated
    elif "budget exceeded" in text:
        code = "FM-1.5"
    elif "dead/fabricated citation" in text:
        code = "FM-3.3"  # the handoff's own citations didn't hold up
    elif "success_criteria_met was false" in text:
        code = "FM-3.1"  # claimed completion without meeting criteria
    elif "kickoff failed" in text:
        code = "EXEC"  # provider/infra error, not an agent decision
    elif (
        "not valid json" in text
        or "envelope validation" in text
        or "was not a dict" in text
        or "did not produce structured handoff" in text
        or "no output produced" in text
    ):
        code = "FM-1.1"  # broke the output contract
    else:
        code = "UNKNOWN"

    return FailureMode.of(code)


# ── Per-run metrics ───────────────────────────────────────────────────────────

class RunMetrics(BaseModel):
    run_id: str
    ts: str
    department: str = ""
    role: str = ""
    status: str = ""
    success_criteria_met: bool = False
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    steps: int = 0
    failure_mode: FailureMode | None = None


def compute_metrics(
    run_id: str,
    envelope: Any,
    token_usage: dict[str, int] | None,
    *,
    department: str = "",
    audit_dir: Path = AUDIT_DIR,
) -> RunMetrics:
    """Build a RunMetrics from the run's audit log + token usage + envelope.

    Tool calls / steps are counted from the per-run JSONL audit log (every role
    in a chain logs to the same file).
    """
    tool_calls = 0
    steps = 0
    log = audit_dir / f"{run_id}.jsonl"
    if log.exists():
        for line in log.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            steps += 1
            if rec.get("type") == "action":
                tool_calls += 1

    tu = token_usage or {}
    return RunMetrics(
        run_id=run_id,
        ts=datetime.now(timezone.utc).isoformat(),
        department=department,
        role=getattr(envelope, "role", "") or "",
        status=getattr(envelope, "status", "") or "",
        success_criteria_met=bool(getattr(envelope, "success_criteria_met", False)),
        total_tokens=tu.get("total_tokens", 0),
        prompt_tokens=tu.get("prompt_tokens", 0),
        completion_tokens=tu.get("completion_tokens", 0),
        tool_calls=tool_calls,
        steps=steps,
        failure_mode=classify_failure(envelope),
    )


def record_metrics(metrics: RunMetrics, *, path: Path = METRICS_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(metrics.model_dump_json() + "\n")


def summarize_metrics(*, path: Path = METRICS_LOG) -> dict[str, Any]:
    """Aggregate metrics.jsonl: completion rate, token trend, failure modes.

    This is the signal behind "halt if token/task trends up" — a rising
    avg_total_tokens or a clustering failure mode is the cue to fix orchestration.
    """
    if not Path(path).exists():
        return {"runs": 0}

    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    n = len(rows)
    if n == 0:
        return {"runs": 0}

    completed = sum(1 for r in rows if r.get("status") == "completed")
    toks = [r.get("total_tokens", 0) for r in rows]
    fm_counts: dict[str, int] = {}
    for r in rows:
        fm = r.get("failure_mode")
        if fm:
            key = f"{fm['code']} {fm['label']}"
            fm_counts[key] = fm_counts.get(key, 0) + 1

    return {
        "runs": n,
        "completion_rate": round(completed / n, 3),
        "avg_total_tokens": round(sum(toks) / n),
        "max_total_tokens": max(toks),
        "avg_tool_calls": round(sum(r.get("tool_calls", 0) for r in rows) / n, 1),
        "failure_modes": dict(sorted(fm_counts.items(), key=lambda kv: -kv[1])),
    }


if __name__ == "__main__":  # python -m orgos.observability → print the summary
    print(json.dumps(summarize_metrics(), indent=2))
