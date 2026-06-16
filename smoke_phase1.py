"""Phase 1 smoke harness — probes the runtime behaviours that static review and
the no-key enforcement suite cannot reach. This one spends real tokens.

Run:
    export OPENAI_API_KEY=sk-...          # or any LiteLLM-supported provider
    python smoke_phase1.py                # full run
    python smoke_phase1.py --quick        # skip the hierarchical path
    python smoke_phase1.py --model gpt-4o-mini

Unlike tests/test_enforcement.py, these checks are *allowed* to fail on first
contact — each failure is a precise diagnostic of one runtime unknown:

  envelope_validation  the chain returns a schema-validated HandoffEnvelope
  audit_capture        the step_callback logs real steps, not all "unknown"
  budget_abort         a raised BudgetExceeded actually aborts kickoff()
  gate_denies_live     a denied approval really blocks the tool at runtime
  hierarchical_path    the manager+synthesis arrangement yields an envelope
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from orgos import PermissionTier, RoleSpec, TaskBrief, spawn, spawn_chain
from orgos.audit import AUDIT_DIR
from orgos.tools import BashTool

DEFAULT_MODEL = "gpt-4o-mini"

# Providers that reject OpenAI json_schema — use json_object mode instead of
# paying a wasted structured-output probe. Extend as needed.
_NO_JSON_SCHEMA = ("deepseek/", "ollama/")


def _structured_for(model: str) -> bool:
    """False for providers that don't support OpenAI json_schema outputs."""
    return not any(model.lower().startswith(p) for p in _NO_JSON_SCHEMA)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _audit_records(run_id: str) -> list[dict]:
    path = AUDIT_DIR / f"{run_id}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ── 1+2: envelope validation + audit capture (one shared paid run) ───────────
def check_envelope_and_audit(model: str) -> list[Check]:
    worker = RoleSpec(
        name="smoke-writer",
        tier=PermissionTier.WORKER,
        system_prompt="You write a one-line summary, then report your handoff.",
        model=model,
        structured_output=_structured_for(model),
        max_iter=4,
    )
    brief = TaskBrief(
        objective="Say 'hello from orgos' and report a completed handoff.",
        success_criteria=["The summary contains the word hello"],
    )
    result = spawn_chain([(worker, brief)], verbose=False)

    env = result.envelope
    env_ok = env.status in ("completed", "needs_revision") and bool(env.summary)
    env_detail = f"status={env.status} criteria_met={env.success_criteria_met}"

    records = _audit_records(result.run_id)
    non_unknown = [r for r in records if r.get("type") != "unknown"]
    audit_ok = bool(records) and bool(non_unknown)
    types = sorted({r.get("type", "?") for r in records})
    audit_detail = (
        f"{len(records)} records, {len(non_unknown)} typed; types={types}"
        if records
        else "no audit log written"
    )

    return [
        Check("envelope_validation", env_ok, env_detail),
        Check("audit_capture", audit_ok, audit_detail),
    ]


# ── 3: budget abort ──────────────────────────────────────────────────────────
def check_budget_abort(model: str) -> Check:
    greedy = RoleSpec(
        name="smoke-greedy",
        tier=PermissionTier.WORKER,
        system_prompt="Write a long detailed essay about the ocean.",
        model=model,
        structured_output=_structured_for(model),
        max_iter=6,
        max_budget_tokens=1,  # trips on the first call
    )
    brief = TaskBrief(objective="Write at length about the ocean.")
    result = spawn(greedy, brief, verbose=False)
    env = result.envelope
    passed = env.status == "failed" and "udget" in (env.summary or "")
    detail = f"status={env.status} summary={env.summary[:80]!r}"
    if not passed:
        detail += "  <-- BudgetExceeded may have been swallowed by kickoff()"
    return Check("budget_abort", passed, detail)


# ── 4: live gate denial ──────────────────────────────────────────────────────
def check_gate_denies_live(model: str) -> Check:
    sentinel = Path("./_smoke_sentinel.txt")
    sentinel.unlink(missing_ok=True)

    invocations: list[str] = []  # records each time the gate is consulted

    def always_deny(role_name: str, tool_name: str, tool_input: dict) -> bool:
        invocations.append(tool_name)
        return False

    publisher = RoleSpec(
        name="smoke-publisher",
        tier=PermissionTier.PUBLISHER,  # requires_approval=["*"] gates every tool
        system_prompt=(
            "You must create the sentinel file by running the Bash tool with "
            f"command: echo hi > {sentinel}. Always attempt it."
        ),
        tools=[BashTool()],
        model=model,
        structured_output=_structured_for(model),
        max_iter=4,
    )
    brief = TaskBrief(
        objective=f"Create the file {sentinel} using the Bash tool.",
    )
    result = spawn(publisher, brief, approval_fn=always_deny, verbose=False)

    file_absent = not sentinel.exists()
    gate_invoked = len(invocations) > 0  # the model actually attempted the tool
    sentinel.unlink(missing_ok=True)

    # Security property: the side effect must not happen (file_absent). The gate
    # being invoked is the corroboration that the wire was actually exercised
    # (vs. the model never trying the tool). saw_DENIED is unreliable because the
    # denial string lives in the tool's intermediate return, not the final answer.
    passed = file_absent
    detail = f"file_absent={file_absent} gate_invoked={gate_invoked} (x{len(invocations)})"
    if file_absent and not gate_invoked:
        detail += "  (file absent, but model never called the tool — gate not exercised)"
    return Check("gate_denies_live", passed, detail)


# ── 5: hierarchical path ─────────────────────────────────────────────────────
def check_hierarchical(model: str) -> Check:
    worker = RoleSpec(
        name="smoke-sub",
        tier=PermissionTier.WORKER,
        system_prompt="You answer one factual question concisely.",
        model=model,
        structured_output=_structured_for(model),
        max_iter=4,
    )
    boss = RoleSpec(
        name="smoke-boss",
        tier=PermissionTier.ORCHESTRATOR,
        system_prompt="Delegate the question to your worker, then synthesise.",
        model=model,
        structured_output=_structured_for(model),
        max_iter=6,
    )
    brief = TaskBrief(objective="What is the capital of France? Delegate, then report.")
    try:
        result = spawn(boss, brief, subordinates=[worker], verbose=False)
    except Exception as exc:  # noqa: BLE001 — capturing the live failure is the point
        return Check("hierarchical_path", False, f"raised {type(exc).__name__}: {exc}")
    env = result.envelope
    passed = env.status in ("completed", "needs_revision") and bool(env.summary)
    return Check("hierarchical_path", passed, f"status={env.status}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--quick", action="store_true", help="skip hierarchical path")
    args = ap.parse_args()

    print(f"== Phase 1 smoke harness (model={args.model}) ==\n")
    checks: list[Check] = []
    checks.extend(check_envelope_and_audit(args.model))
    checks.append(check_budget_abort(args.model))
    checks.append(check_gate_denies_live(args.model))
    if not args.quick:
        checks.append(check_hierarchical(args.model))

    print()
    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = "PASS" if c.passed else "FAIL"
        print(f"  [{mark}] {c.name.ljust(width)}  {c.detail}")

    n_pass = sum(c.passed for c in checks)
    print(f"\n{n_pass}/{len(checks)} runtime checks passed")
    print("(failures are diagnostics, not crashes — read the detail line)")
    return 0 if n_pass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
