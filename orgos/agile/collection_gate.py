"""Post-merge integration collection check (Fix §H9).

Root cause we're addressing: v3/v5 both showed LLM-produced test files
with syntax errors (unclosed brackets, bad indentation) that made it
past the AC gate because the gate only inspects the story's own diff —
it doesn't check whether the WHOLE integration branch's tests still
parse cleanly.

Result: pytest --collect-only aborts, the story is "done" but the
integration branch is broken. Later runs of `orgos verify` see "0 passed"
until we added §H8's --ignore workaround.

This module implements the CI-in-the-loop pattern that real dev teams
use — after each successful merge, run a lightweight collect-only pass.
If broken:

  1. Emit `integration_collection_broken` event with the offending file
     + a truncated error snippet.
  2. Transition the just-merged story from `pending_acceptance` back to
     `ready` with the collection error injected into its body.
  3. This triggers the §H1 AC-retry-loop mechanics: next puller sees
     "PREVIOUS ATTEMPT FAILED — collection broken: <file> — <error>" and
     fixes it.

Kept in its own module so it's easy to test without spinning up the
whole runtime.
"""

from __future__ import annotations

import re as _re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from orgos.agile.environment import detect_environment


# `pytest --collect-only` for a real repo can be slow (imports, plugins).
# We bound it so the merge worker never blocks on a broken pyproject.
DEFAULT_COLLECT_TIMEOUT = 30

# Non-Python repos run their full test command (there is no generic
# "collect-only" across toolchains), which may include a compile step —
# e.g. `npm test` = tsc + node --test. Needs a wider bound.
NON_PYTHON_TEST_TIMEOUT = 180


def _find_venv_python(worktree: Path) -> Optional[str]:
    """Prefer the team's .orgos_venv/bin/python if it exists (already
    has the built package pip-installed); fall back to sys.executable."""
    v = worktree / ".orgos_venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    if v.exists():
        return str(v)
    return sys.executable


def gate_command(worktree: Path) -> str:
    """Human-readable description of what the gate runs for this repo —
    used in events and story feedback so agents see the real command."""
    env = detect_environment(Path(worktree))
    if env.language in ("python", "unknown"):
        return "pytest --collect-only"
    return env.test_cmd or "(no test command detected)"


def _check_test_cmd(
    worktree: Path, test_cmd: str, timeout: int,
) -> tuple[bool, list[str], str]:
    """Non-Python gate: run the repo's detected test command.

    Fail-open cases (return OK) mirror the Python path's philosophy —
    infrastructure problems must not block merges, only broken code should:
      - no test command detected
      - subprocess machinery fails (missing shell, timeout, OSError)
      - exit 127 / "command not found" — toolchain not installed in this
        worktree (e.g. integration worktree without node_modules)
    """
    if not test_cmd:
        return True, [], ""
    try:
        r = subprocess.run(
            test_cmd, shell=True, cwd=str(worktree),
            capture_output=True, text=True,
            timeout=max(timeout, NON_PYTHON_TEST_TIMEOUT),
        )
    except (subprocess.SubprocessError, OSError):
        return True, [], ""

    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    tail = combined[-800:]
    if r.returncode == 0:
        return True, [], tail
    if r.returncode == 127 or "command not found" in combined:
        return True, [], tail
    return False, [], tail


def check_collection(
    worktree: Path, timeout: int = DEFAULT_COLLECT_TIMEOUT,
) -> tuple[bool, list[str], str]:
    """Post-merge health check on the integration worktree.

    Language-aware (the 2026-07-22 TS acceptance run had 2 failing tests
    merge silently because this gate was pytest-only):
      - python / unknown → `pytest --collect-only -q` (import/syntax check,
        historical behavior — a full-suite run per merge would be too slow)
      - any other language detect_environment recognizes (node, go, rust,
        ruby, java) → run the detected test command. Stronger than the
        Python gate (catches failing tests, not just broken imports);
        deliberate asymmetry — the test command is the only generic health
        signal other toolchains expose.

    Returns (ok, broken_files, error_tail):
      ok:            True if the check passed (or nothing to check)
      broken_files:  paths pytest reported as unparseable (Python only;
                     other toolchains report through error_tail)
      error_tail:    trailing ~800 chars of stderr+stdout for diagnostics
    """
    env = detect_environment(Path(worktree))
    if env.language not in ("python", "unknown"):
        return _check_test_cmd(worktree, env.test_cmd, timeout)

    py = _find_venv_python(worktree)
    try:
        r = subprocess.run(
            [py, "-m", "pytest", "--collect-only", "-q",
             "--no-header", "--disable-warnings"],
            cwd=str(worktree), capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        # Any subprocess failure: assume OK (fail-open — don't block merges
        # on infrastructure issues).
        return True, [], ""

    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    tail = combined[-800:]

    # exit code 5 = "no tests collected" → treat as OK (nothing to break yet)
    # exit code 0 = collection succeeded
    if r.returncode in (0, 5):
        return True, [], tail

    # Extract file paths from lines like "ERROR tests/foo/test_bar.py"
    broken: list[str] = []
    for line in combined.splitlines():
        m = _re.match(r"^ERROR\s+(\S+\.py)", line.strip())
        if m and m.group(1) not in broken:
            broken.append(m.group(1))
    return False, broken, tail


def apply_collection_gate(
    workspace: Any, board: Any, story_id: str, emitter: Any,
    *, timeout: int = DEFAULT_COLLECT_TIMEOUT,
) -> bool:
    """Run collection check on integration; on failure, send story back to
    ready with feedback injected. Returns True if collection OK, False if
    the story was reverted from pending_acceptance to ready.

    Called right after merge_completed transitions story to pending_acceptance.
    Idempotent-ish: if the story is already not in pending_acceptance, we
    log the collection status but don't force a transition.

    Fail-open: any exception in the gate returns True (don't block work
    on infrastructure hiccups).
    """
    try:
        worktree = workspace.integration_worktree
    except Exception:
        return True

    try:
        ok, broken, error_tail = check_collection(worktree, timeout=timeout)
    except Exception as e:
        try:
            emitter.emit(
                "collection_gate_error", story_id=story_id,
                summary=f"gate error: {e}"[:200],
            )
        except Exception:
            pass
        return True

    if ok:
        return True

    # Collection is broken. Emit the event so the human sees it.
    try:
        cmd_desc = gate_command(worktree)
    except Exception:
        cmd_desc = "the integration test command"
    try:
        emitter.emit(
            "integration_collection_broken",
            story_id=story_id,
            broken_files=broken,
            summary=(
                f"integration check `{cmd_desc}` failed after {story_id} "
                f"merged"
                + (f": {len(broken)} unparseable file(s): {broken[:3]}"
                   if broken else "")
            )[:300],
        )
    except Exception:
        pass

    # Try to send the story back to ready with feedback injected.
    try:
        story = board.read(story_id)
    except Exception:
        return False
    if story.state != "pending_acceptance":
        # Someone else already moved it (PO accepted, or another gate blocked).
        # Nothing more to do — the event is emitted for the record.
        return False

    try:
        fresh = board.read(story_id)
        feedback = (
            "\n---\n"
            "## PREVIOUS ATTEMPT BROKE THE INTEGRATION BRANCH\n\n"
            f"The commit merged but `{cmd_desc}` now fails on the "
            "integration branch — broken syntax/imports, a compile error, "
            "or failing tests introduced by the merge.\n\n"
            + (f"Unparseable files: {broken}\n\n" if broken else "")
            + "### error tail\n"
            "```\n"
            f"{error_tail[:600]}\n"
            "```\n\n"
            "Fix the failure. Do NOT rewrite files from scratch — the "
            "existing content is mostly correct.\n"
        )
        fresh.body = (fresh.body or "") + feedback
        fresh.commit_sha = ""
        board._write_story(fresh)
        board.transition(
            story_id, "ready", actor="collection_gate",
            reason=f"collection_broken: {broken[:2]}",
        )
        try:
            emitter.emit(
                "story_reopened_collection", story_id=story_id,
                broken_files=broken,
                summary=(
                    f"{story_id} reopened: broken files {broken[:2]} — "
                    "sent back to ready with fix instructions"
                ),
            )
        except Exception:
            pass
        return False
    except Exception as e:
        try:
            emitter.emit(
                "collection_gate_error", story_id=story_id,
                summary=f"failed to reopen story: {e}"[:200],
            )
        except Exception:
            pass
        return False
