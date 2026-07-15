"""Solo-developer baseline runner — single-shot LLM, no team, no wiki, no memory.

Same worktree machinery as run_pull_sprint, same evaluator, but ONE agent doing
the whole job in one spawn. This is the fair baseline for the team benchmark.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from orgos.agile.benchmark import BenchmarkRun, diff_stats, pytest_stats
from orgos.agile.pricing import cost_usd
import subprocess
from orgos.agile.sprint import (
    Sprint, _extract_json_objects, _make_worktree, _new_sprint_id, write_snapshot,
)
from orgos.spawn import PermissionTier, RoleSpec, TaskBrief, spawn
from orgos.tools.bash import BashTool


_SOLO_SYSTEM_PROMPT = """You are a solo senior developer. You handle the whole job yourself:
scope the story, write the code, write the tests, run pytest, commit.

You have BashTool only. Use unix commands (cat, ls, cat > file <<'EOF', pytest, git).
No wiki, no board, no other agents. Just you and the worktree.

Bias hard toward action: your first bash call should write a file, not explore.
Then run tests, then commit, then emit the envelope.
"""


_SOLO_BRIEF_TEMPLATE = """You are a solo developer. Do the whole job in one shot.

STORY:
  title: {title}
  description: {body}

WORKTREE: {worktree}  (branch {branch})
Shell is UNIX bash.

DO THIS:

1. Write the file(s) the story asks for using heredoc:
     cat > path/to/target <<'EOF'
     <full contents>
     EOF

2. If the story implies tests, write them too, then run:
     pytest <path> -v

3. Commit:
     git add -A
     git -c user.name=orgos-solo -c user.email=solo@orgos.local commit -m "feat: {title}"

4. git rev-parse HEAD

5. Output ONLY this envelope JSON. No prose, no markdown fences.

{{
  "role": "solo",
  "status": "completed",
  "summary": "<what you did>",
  "success_criteria_met": true,
  "requires_human_approval": false,
  "payload": {{
    "commit_sha": "<sha>",
    "files_touched": ["<paths>"],
    "test_command": "<cmd or empty>",
    "test_output": "<tail>",
    "test_passed": true
  }}
}}

HARD RULES:
  - First bash call must write a file, not explore.
  - No wiki tools, no board tools — you don't have any.
  - If you cannot infer the target path, write NOTES.md and commit that.
"""


def _solo_role(model: str) -> RoleSpec:
    return RoleSpec(
        name="Solo_Developer",
        description="Single-shot solo developer baseline for benchmark.",
        tier=PermissionTier.WORKER,
        system_prompt=_SOLO_SYSTEM_PROMPT,
        model=model,
        max_iter=25,
        success_criteria=[
            "Wrote the requested code.",
            "Produced a commit with a valid SHA.",
            "Emitted the envelope JSON.",
        ],
        structured_output=False,  # DeepSeek doesn't support json_schema
    )


def run_solo(
    repo_path: Path,
    issue: dict,
    *,
    model: str,
    run_budget_tokens: int = 1_500_000,
) -> tuple[Sprint, BenchmarkRun]:
    """Run one issue with a single solo agent. Returns (Sprint, BenchmarkRun)."""
    from datetime import datetime, timezone

    sprint_id = _new_sprint_id()
    started_at = datetime.now(timezone.utc).isoformat()
    branch = f"solo/{sprint_id}"
    worktree = _make_worktree(repo_path, sprint_id, branch)
    repo = Path(repo_path)

    write_snapshot(Sprint(id=sprint_id, started_at=started_at, repo_path=repo,
                          worktree_path=worktree, branch=branch, picked_issue=issue,
                          envelopes={}, status="in_progress"),
                   backlog=[], heuristics=[])

    # Baseline SHA — the .gitignore commit _make_worktree just wrote. Diff
    # against this so the agent's diff is exactly what it produced ON TOP.
    baseline_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(worktree), capture_output=True, text=True, timeout=10,
    ).stdout.strip()

    role = _solo_role(model)
    role.tools = [BashTool(default_working_dir=str(worktree))]

    brief = TaskBrief(
        objective=_SOLO_BRIEF_TEMPLATE.format(
            title=issue.get("title", ""),
            body=issue.get("body", ""),
            worktree=str(worktree),
            branch=branch,
        ),
        expected_output="A HandoffEnvelope JSON.",
        success_criteria=["Solo developer completed the task."],
    )

    t0 = time.time()
    envelope = {}
    raw_output = ""
    error = ""
    tokens_input = 0
    tokens_output = 0

    try:
        result = spawn(role, brief, run_budget_tokens=run_budget_tokens)
        tokens_input = (result.token_usage or {}).get("prompt_tokens", 0)
        tokens_output = (result.token_usage or {}).get("completion_tokens", 0)
        for tout in result.tasks_output:
            raw = getattr(tout, "raw", "") or ""
            raw_output = raw_output + raw
            for blob in _extract_json_objects(raw):
                try:
                    data = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("role"):
                    envelope = data
                    break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    wall = time.time() - t0

    # Diff stats — compare against the actual baseline SHA we captured.
    files, added, removed, diff_text = diff_stats(worktree, baseline_sha)

    # Parse pytest counts from the envelope's test_output (if any).
    test_output = ""
    if envelope:
        payload = envelope.get("payload", {}) or {}
        test_output = payload.get("test_output", "") or ""
    tests_run, tests_passed, tests_failed = pytest_stats(test_output)

    commit_sha = ""
    if envelope:
        commit_sha = (envelope.get("payload", {}) or {}).get("commit_sha", "") or ""

    # Actual commit-on-top check: did HEAD advance past baseline?
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(worktree), capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    commit_produced = bool(current_head) and current_head != baseline_sha

    # Quality — reuse the same evaluator on this diff.
    quality_ac = quality_code = quality_tests = None
    quality_summary = ""
    try:
        from orgos.agile.evaluator import QualityEvaluator
        evaluator = QualityEvaluator(model=model)
        sprint_stub = Sprint(id=sprint_id, started_at=started_at, repo_path=repo,
                             worktree_path=worktree, branch=branch, picked_issue=issue,
                             envelopes={"solo": envelope}, status="completed",
                             spawn_result=None)
        q = evaluator.evaluate(sprint_stub, issue)
        # QualityEvaluator returns an object with `.llm_scores` dict.
        scores = q.llm_scores or {}
        quality_ac = scores.get("ac_compliance")
        quality_code = scores.get("code_quality")
        quality_tests = scores.get("test_relevance")
        quality_summary = q.llm_summary or ""
    except Exception as e:
        quality_summary = f"evaluator error: {e}"

    sprint = Sprint(
        id=sprint_id, started_at=started_at, repo_path=repo,
        worktree_path=worktree, branch=branch, picked_issue=issue,
        envelopes={"solo": envelope} if envelope else {},
        status="completed" if envelope else "failed",
        spawn_result=None,
    )

    run = BenchmarkRun(
        issue_id=issue.get("issue_id", "?"),
        approach="solo",
        model=model,
        started_at=started_at,
        wall_seconds=round(wall, 2),
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_total=tokens_input + tokens_output,
        cost_usd=round(cost_usd(model, tokens_input, tokens_output), 6),
        commit_produced=commit_produced,
        commit_sha=commit_sha,
        files_changed=files,
        loc_added=added,
        loc_removed=removed,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        quality_ac=quality_ac,
        quality_code=quality_code,
        quality_tests=quality_tests,
        quality_summary=quality_summary,
        diff_text=diff_text,
        envelope_trail=[envelope] if envelope else [],
        raw_output=raw_output[-4000:],
        error=error,
    )

    return sprint, run
