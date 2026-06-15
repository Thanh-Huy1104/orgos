"""Phase 1 smoke harness — live runtime checks for orgos.

This is NOT the enforcement suite. tests/test_enforcement.py locks the *policy*
layer with no LLM key. This harness spends real tokens to probe the *runtime*
behaviors that only show up against a live model + the CrewAI engine:

  1. envelope_validation  — spawn_chain returns a real, validated HandoffEnvelope
  2. audit_capture        — the step_callback actually logs structured steps
                            (not all "unknown" — i.e. CrewAI's step object exposes
                            the attrs audit.py assumes for THIS crewai version)
  3. budget_abort         — real cumulative tokens tracked at the LLM-call
                             boundary, BudgetExceeded propagates out of kickoff()
  4. gate_denies_live     — a publisher's gated tool is actually blocked at runtime
  5. hierarchical_path    — the manager + synthesis-task arrangement yields a
                            validated envelope (the non-idiomatic CrewAI path)

Run it from the repo root (the dir holding orgos/ and examples/):

    export OPENAI_API_KEY=sk-...                 # or set ORGOS_SMOKE_MODEL + that provider's key
    python smoke_phase1.py                        # all checks
    python smoke_phase1.py --quick                # skip the slow hierarchical check
    ORGOS_SMOKE_MODEL=gpt-4o-mini python smoke_phase1.py

Exit code is 0 only if every selected check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

# Make `import orgos` / `import examples.…` work when run as a script from the
# repo root, regardless of the caller's CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orgos import (
    HandoffEnvelope,
    PermissionTier,
    RoleSpec,
    TaskBrief,
    spawn,
    spawn_chain,
)
from orgos.tools import BashTool

MODEL = os.environ.get("ORGOS_SMOKE_MODEL", "gpt-4o-mini")
VALID_STATUS = {"completed", "needs_revision", "blocked", "failed"}
SMALL_UNIVERSE = ["SPY", "QQQ", "IWM"]

auto_approve = lambda *_: True   # noqa: E731 — trivial non-interactive approver
auto_deny = lambda *_: False     # noqa: E731 — always-deny, for the gate test


# --------------------------------------------------------------------------- #
# tiny reporting harness
# --------------------------------------------------------------------------- #
_results: list[tuple[str, str, str]] = []  # (name, PASS|FAIL|ERROR, detail)


def record(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, "PASS" if ok else "FAIL", detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def guarded(name: str, fn) -> None:
    """Run a check; any exception is a recorded ERROR, not a harness crash.
    For some checks (hierarchical) the exception IS the finding we want."""
    print(f"\n▶ {name} …")
    try:
        fn(name)
    except Exception as exc:  # noqa: BLE001 — we want to capture and continue
        tb = traceback.format_exc().strip().splitlines()
        _results.append((name, "ERROR", f"{type(exc).__name__}: {exc}"))
        print(f"  [ERROR] {name} — {type(exc).__name__}: {exc}")
        print("         " + "\n         ".join(tb[-3:]))


# --------------------------------------------------------------------------- #
# shared finance department (imported from the example, shrunk for cost/speed)
# --------------------------------------------------------------------------- #
def _finance_roles():
    """Import the canonical finance roles and shrink them to a cheap model and
    a small iteration budget. Done lazily so budget/gate checks still run even
    if the example module's symbols have been renamed."""
    from examples.quant_pair_scanner import (
        finance_supervisor,
        pair_scanner,
        pair_validator,
    )

    scanner = pair_scanner.model_copy(update={"model": MODEL, "max_iter": 12})
    validator = pair_validator.model_copy(update={"model": MODEL, "max_iter": 8})
    supervisor = finance_supervisor.model_copy(update={"model": MODEL, "max_iter": 12})
    return scanner, validator, supervisor


_SCAN_BRIEF = TaskBrief(
    objective=(
        f"Test these tickers for cointegrated pairs using the cointegration tool, "
        f"each pair once: {', '.join(SMALL_UNIVERSE)}."
    ),
    expected_output="A short list of candidate pairs with ADF p-value and half-life.",
    success_criteria=["Each tested pair has an ADF p-value and a half-life estimate"],
)
_VALIDATE_BRIEF = TaskBrief(
    objective="Review the scanner's proposed pairs; mark each verified or rejected with a reason.",
    expected_output="A short validation verdict per pair.",
    success_criteria=["Every input pair is marked verified or rejected with a reason"],
)
_ORCH_BRIEF = TaskBrief(
    objective=(
        f"Produce a validated shortlist of cointegrated pairs from: "
        f"{', '.join(SMALL_UNIVERSE)}. Delegate discovery, then validation."
    ),
    expected_output="A final validated shortlist with verdicts.",
    success_criteria=["Final shortlist is validated and each pair has a verdict"],
)


# Cache the chain result so envelope + audit checks share one (paid) run.
_chain_result = {}


def _run_chain_once():
    if "res" not in _chain_result:
        scanner, validator, _ = _finance_roles()
        _chain_result["res"] = spawn_chain(
            [(scanner, _SCAN_BRIEF), (validator, _VALIDATE_BRIEF)],
            approval_fn=auto_approve,
            verbose=False,
        )
    return _chain_result["res"]


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_envelope_validation(name: str) -> None:
    res = _run_chain_once()
    ok = isinstance(res.envelope, HandoffEnvelope) and res.envelope.status in VALID_STATUS
    record(
        name,
        ok,
        f"status={res.envelope.status!r}, run_id={res.run_id}, tokens={res.token_usage}",
    )


def check_audit_capture(name: str) -> None:
    res = _run_chain_once()
    log = Path("_audit_logs") / f"{res.run_id}.jsonl"
    if not log.exists() or log.stat().st_size == 0:
        record(name, False, f"no audit log written at {log}")
        return
    records = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    types = {r.get("type") for r in records}
    structured = bool(types & {"action", "finish"})
    record(
        name,
        structured,
        f"{len(records)} steps logged, types={types}"
        + ("" if structured else "  ← all 'unknown': step_callback attrs don't match this CrewAI version"),
    )


def check_budget_abort(name: str) -> None:
    # max_budget_tokens=1 guarantees the very first step trips the cap. If the
    # envelope comes back 'failed' with a budget message, the exception
    # propagated and was caught. Anything else means CrewAI swallowed it.
    canary = RoleSpec(
        name="budget-canary",
        description="Deliberately verbose role used to trip the token budget.",
        tier=PermissionTier.WORKER,
        system_prompt="You are extremely verbose. Always write long, detailed answers.",
        model=MODEL,
        max_iter=4,
        max_budget_tokens=1,
    )
    res = spawn(
        canary,
        TaskBrief(objective="Write five long, detailed paragraphs about how bond markets work."),
        verbose=False,
    )
    ok = res.envelope.status == "failed" and "budget" in (res.envelope.summary or "").lower()
    detail = f"status={res.envelope.status!r}, summary={res.envelope.summary[:90]!r}"
    if not ok:
        detail += "  ← budget abort did NOT surface; CrewAI may be swallowing step_callback exceptions"
    record(name, ok, detail)


def check_gate_denies_live(name: str) -> None:
    # A publisher with a gated Bash tool + an always-deny approver. The model is
    # told to create a sentinel file. If the gate works, the file never appears —
    # this assertion is independent of whether the model cooperates.
    sentinel = Path(tempfile.gettempdir()) / f"orgos_gate_{uuid.uuid4().hex[:8]}.txt"
    sentinel.unlink(missing_ok=True)
    guard = RoleSpec(
        name="gate-canary",
        description="Attempts a shell command; used to prove the gate blocks it.",
        tier=PermissionTier.PUBLISHER,
        system_prompt="You must use the Bash tool to run the command you are given.",
        tools=[BashTool()],
        model=MODEL,
        max_iter=4,
    )
    try:
        res = spawn(
            guard,
            TaskBrief(objective=f"Use the Bash tool to run exactly: touch {sentinel}"),
            approval_fn=auto_deny,
            verbose=False,
        )
        created = sentinel.exists()
        denied_seen = "DENIED" in (res.raw_output or "")
        ok = not created
        if not ok:
            detail = "SENTINEL CREATED — gate was bypassed at runtime!"
        elif denied_seen:
            detail = "gate held; saw DENIED in output (corroborated)"
        else:
            detail = "gate held (file absent); note: necessary-not-sufficient if model never called the tool"
        record(name, ok, detail)
    finally:
        sentinel.unlink(missing_ok=True)


def check_hierarchical_path(name: str) -> None:
    scanner, validator, supervisor = _finance_roles()
    res = spawn(
        supervisor,
        _ORCH_BRIEF,
        subordinates=[scanner, validator],
        approval_fn=auto_approve,
        verbose=False,
    )
    ok = isinstance(res.envelope, HandoffEnvelope) and res.envelope.status in VALID_STATUS
    record(name, ok, f"status={res.envelope.status!r}, run_id={res.run_id}, tokens={res.token_usage}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def _has_provider_key() -> bool:
    keys = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY")
    return any(os.environ.get(k) for k in keys)


def main() -> int:
    parser = argparse.ArgumentParser(description="orgos Phase 1 live smoke harness")
    parser.add_argument("--quick", action="store_true", help="skip the slow hierarchical check")
    args = parser.parse_args()

    if not _has_provider_key():
        print("No LLM provider key found in env (OPENAI_API_KEY / ANTHROPIC_API_KEY / …).")
        print("This harness makes real model calls. Set a key and re-run.")
        return 2

    print(f"orgos Phase 1 smoke — model={MODEL}, universe={SMALL_UNIVERSE}")
    print("(spends real tokens; uses gpt-4o-mini by default to keep it cheap)")

    guarded("envelope_validation", check_envelope_validation)
    guarded("audit_capture", check_audit_capture)
    guarded("budget_abort", check_budget_abort)
    guarded("gate_denies_live", check_gate_denies_live)
    if not args.quick:
        guarded("hierarchical_path", check_hierarchical_path)

    print("\n" + "═" * 64)
    width = max(len(n) for n, _, _ in _results)
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    for n, status, detail in _results:
        print(f"  {status:5}  {n:<{width}}  {detail}")
    print("═" * 64)
    print(f"  {passed}/{len(_results)} passed")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
